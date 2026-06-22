"""環境変数から設定を読み込む。"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    token: str
    guild_id: int | None
    voicebank_dir: str
    pitch_hz: float
    mora_ms: float
    max_chars: int  # 1メッセージで読み上げる最大文字数


def _load() -> Settings:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("DISCORD_TOKEN が未設定です（.env を確認）。")

    guild_raw = os.getenv("GUILD_ID", "").strip()
    return Settings(
        token=token,
        guild_id=int(guild_raw) if guild_raw.isdigit() else None,
        voicebank_dir=os.getenv("VOICEBANK_DIR", "./voicebank").strip(),
        pitch_hz=float(os.getenv("PITCH_HZ", "100")),
        mora_ms=float(os.getenv("MORA_MS", "600")),
        max_chars=int(os.getenv("MAX_CHARS", "60")),
    )


settings = _load()
