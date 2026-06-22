"""UTAU音源で読み上げる Discord BOT。

ボイスチャンネルに参加し、対象テキストチャンネルのメッセージを
UTAU音源の声で読み上げる。合成は engine.UtauSpeaker（WORLDベース）。
"""

import asyncio
import logging
import re
import tempfile
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from scipy.io import wavfile

from config import settings
from engine import UtauSpeaker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("yomiage")

URL_RE = re.compile(r"https?://\S+")
CUSTOM_EMOJI_RE = re.compile(r"<a?:(\w+):\d+>")
MENTION_RE = re.compile(r"<@!?\d+>|<@&\d+>|<#\d+>")


def clean_text(message: discord.Message) -> str:
    """メッセージを読み上げ用に整形する。"""
    text = message.content
    text = URL_RE.sub("、URL省略、", text)
    text = CUSTOM_EMOJI_RE.sub(lambda m: m.group(1), text)  # 絵文字は名前読み
    # メンションは表示名に置換
    for user in message.mentions:
        text = text.replace(f"<@{user.id}>", user.display_name)
        text = text.replace(f"<@!{user.id}>", user.display_name)
    text = MENTION_RE.sub("", text)
    text = text.strip()
    if len(text) > settings.max_chars:
        text = text[: settings.max_chars] + "、以下省略"
    return text


class GuildSession:
    """1サーバー分の読み上げ状態。"""

    def __init__(self, bot: commands.Bot, vc: discord.VoiceClient, channel_id: int):
        self.bot = bot
        self.vc = vc
        self.text_channel_id = channel_id
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker = bot.loop.create_task(self._run())

    async def _run(self):
        while True:
            text = await self.queue.get()
            try:
                await self._speak(text)
            except Exception:
                logger.exception("読み上げ中にエラー")
            finally:
                self.queue.task_done()

    async def _speak(self, text: str):
        speaker = self.bot.speaker
        if speaker is None:
            return
        # 合成は重いので別スレッドで
        wav, fs = await self.bot.loop.run_in_executor(None, speaker.speak, text)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            path = f.name
        wavfile.write(path, fs, wav)

        done = asyncio.Event()

        def after(err):
            if err:
                logger.error("再生エラー: %s", err)
            self.bot.loop.call_soon_threadsafe(done.set)

        source = discord.FFmpegPCMAudio(path)
        if self.vc.is_playing():
            self.vc.stop()
        self.vc.play(source, after=after)
        await done.wait()
        Path(path).unlink(missing_ok=True)

    async def close(self):
        self.worker.cancel()
        if self.vc.is_connected():
            await self.vc.disconnect()


class YomiageBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # メッセージ本文の取得に必要（特権インテント）
        intents.voice_states = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.sessions: dict[int, GuildSession] = {}
        self.speaker: UtauSpeaker | None = None

    async def setup_hook(self):
        # UTAU音源を読み込み（失敗してもBOT自体は起動する）
        try:
            self.speaker = UtauSpeaker(
                settings.voicebank_dir,
                pitch_hz=settings.pitch_hz,
                mora_ms=settings.mora_ms,
            )
            logger.info(
                "音源を読み込みました: %s (%d エントリ)",
                settings.voicebank_dir,
                len(self.speaker.oto),
            )
        except Exception as e:
            logger.warning("音源の読み込みに失敗: %s （VOICEBANK_DIR を確認）", e)

        await self.add_cog(Yomiage(self))
        if settings.guild_id:
            guild = discord.Object(id=settings.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self):
        logger.info("ログイン: %s", self.user)


@app_commands.guild_only()
class Yomiage(commands.GroupCog, name="yomiage"):
    def __init__(self, bot: YomiageBot):
        self.bot = bot
        super().__init__()

    @app_commands.command(name="join", description="ボイスチャンネルに参加して読み上げを開始します")
    async def join(self, interaction: discord.Interaction):
        if self.bot.speaker is None:
            await interaction.response.send_message(
                "⚠️ 音源が読み込まれていません。`VOICEBANK_DIR` の設定を確認してください。",
                ephemeral=True,
            )
            return
        voice = getattr(interaction.user, "voice", None)
        if voice is None or voice.channel is None:
            await interaction.response.send_message(
                "先にボイスチャンネルに参加してください。", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild_id
        if gid in self.bot.sessions:
            await self.bot.sessions[gid].close()

        vc = await voice.channel.connect()
        self.bot.sessions[gid] = GuildSession(self.bot, vc, interaction.channel_id)
        await interaction.followup.send(
            f"🔊 {voice.channel.mention} に参加しました。"
            f"このチャンネルのメッセージを読み上げます。",
            ephemeral=True,
        )

    @app_commands.command(name="leave", description="読み上げを終了して退出します")
    async def leave(self, interaction: discord.Interaction):
        session = self.bot.sessions.pop(interaction.guild_id, None)
        if session:
            await session.close()
            await interaction.response.send_message("👋 退出しました。", ephemeral=True)
        else:
            await interaction.response.send_message(
                "読み上げ中ではありません。", ephemeral=True
            )

    @app_commands.command(name="skip", description="読み上げ中の音声をスキップします")
    async def skip(self, interaction: discord.Interaction):
        session = self.bot.sessions.get(interaction.guild_id)
        if session and session.vc.is_playing():
            session.vc.stop()
            await interaction.response.send_message("⏭️ スキップしました。", ephemeral=True)
        else:
            await interaction.response.send_message(
                "再生中の音声はありません。", ephemeral=True
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        session = self.bot.sessions.get(message.guild.id)
        if session is None or message.channel.id != session.text_channel_id:
            return
        if message.content.startswith(("!", "/", ".")):  # コマンドは読まない
            return
        text = clean_text(message)
        if text:
            await session.queue.put(text)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # VCに人がいなくなったら自動退出
        for gid, session in list(self.bot.sessions.items()):
            ch = session.vc.channel
            if ch and len([m for m in ch.members if not m.bot]) == 0:
                await session.close()
                self.bot.sessions.pop(gid, None)


async def main():
    bot = YomiageBot()
    async with bot:
        await bot.start(settings.token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
