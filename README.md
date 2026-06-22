現状 python 3.12 推奨（pyworldが未対応のため(2026/6)）
# UTAU音源 読み上げBOT（Discord）

UTAU音源の声で、Discordのテキストチャンネルを読み上げるBOTです。
歌声合成ツールUTAUの音源を **WORLDボコーダー（pyworld）で「喋り」に転用**しているため、
Windows製の resampler / wavtool（exe）に依存せず、Linuxサーバーでも動きます。

>  **CV（単独音）と VCV（連続音）の両方に自動対応**します。音源のエイリアスを見て
> どちらかを自動判別します（音高サフィックス例 `D3` も自動で処理）。CVVC は未対応です。
> また、抑揚は付かず一定ピッチの「棒読み」です。これはUTAUを喋りに使う性質上の割り切りです。
> VCVの繋ぎは簡易実装（オーバーラップでクロスフェード）なので、UTAU本体ほど滑らかではありません。

---

## 仕組み

```
メッセージ
  → テキストを「読み（かな）」に変換   （pyopenjtalk / pykakasi）
  → モーラ単位に分割                   （きゃ / っ / ー / ん などを処理）
  → 各モーラのサンプルを oto.ini で切り出し
  → WORLDで解析（f0・スペクトル・非周期性）
  → 子音部を固定したまま母音部を伸縮し、ピッチを一定化
  → WORLDで再合成 → クロスフェードで連結 → wav
  → FFmpeg経由でボイスチャンネルに再生
```

## ファイル構成

```
utau-yomiage/
├── bot.py              # Discord BOT本体（VC参加・読み上げ・キュー）
├── config.py           # .env 読み込み
├── synth_cli.py        # Discordなしで音源を試すCLI
├── test_engine.py      # ダミー音源での通しテスト
├── requirements.txt
├── .env.example
├── engine/
│   ├── __init__.py
│   ├── oto.py          # oto.ini パーサー
│   ├── kana.py         # テキスト→かな→モーラ
│   └── synth.py        # WORLDベースの合成エンジン（UtauSpeaker）
└── voicebank/          # ここにUTAU音源を置く（oto.ini + wav）
```

---

## セットアップ

### 1. FFmpeg をインストール

音声再生に必須です。
- Windows: `winget install Gyan.FFmpeg` など
- Mac: `brew install ffmpeg`
- Linux: `sudo apt install ffmpeg`

### 2. 依存をインストール

```bash
pip install -r requirements.txt
# 読みの精度を上げたい場合（任意・推奨）:
pip install pyopenjtalk
```

### 3. UTAU音源を置く

`voicebank/` フォルダに音源（`oto.ini` と `*.wav`）を入れます。**CV（単独音）でも VCV（連続音）でもOK**で、
種類は自動判別されます。`VOICEBANK_DIR` を変えれば別の場所も指定できます。

> 🔸 **利用規約に注意**: 自作音源なら自由ですが、配布音源を使う場合は
> 「ソフトウェア組み込み・読み上げ用途」が許可されているか、各音源の規約を必ず確認してください。

### 4. 音源を単体でテスト（Discord前に推奨）

```bash
python synth_cli.py "こんにちは、てすとです" -o out.wav
python synth_cli.py "ゆっくりしていってね" --pitch 180 --mora 160
```

`out.wav` を再生して、声・速さ・ピッチを `--pitch` / `--mora` で調整します。

### 5. Bot を作成して招待

1. [Discord Developer Portal](https://discord.com/developers/applications) で New Application → Bot
2. **Privileged Gateway Intents** で以下を ON:
   - **MESSAGE CONTENT INTENT**（メッセージ本文の読み取りに必須）
   - **SERVER MEMBERS INTENT**
3. OAuth2 → URL Generator で `bot` と `applications.commands` を選択、権限に
   `Connect` / `Speak` / `Send Messages` / `Read Message History` を付与して招待

### 6. トークンを設定して起動

```bash
cp .env.example .env   # DISCORD_TOKEN を記入
python bot.py
```

---

## 使い方（スラッシュコマンド）

| コマンド | 説明 |
|---|---|
| `/yomiage join` | 自分がいるVCに参加し、そのチャンネルの読み上げを開始 |
| `/yomiage leave` | 読み上げを終了して退出 |
| `/yomiage skip` | 再生中の音声をスキップ |

`join` 後、対象テキストチャンネルに書き込むと順番に読み上げます。
VCから全員いなくなると自動で退出します。

---

## 声を良くするための調整ポイント

- **`PITCH_HZ`**: 音源の地声に近い高さに合わせると自然になります。
- **`MORA_MS`**: 大きいとゆっくり、小さいと早口。
- **読みの精度**: `pyopenjtalk` を入れると漢字の読み・分かち書きが大きく改善します。

## さらに発展させるなら

- **VCV / CVVC 対応**: `engine/synth.py` の `_find_entry` とモーラ分割を拡張し、
  音素の前後関係（`a か` のようなエイリアス）を解決する。
- **抑揚（アクセント）**: `pyopenjtalk` のアクセント情報から `pitch_hz` を
  モーラごとに動かせば、棒読みから自然な抑揚に近づきます。
- **辞書機能**: 読み間違いを登録できる置換辞書を `clean_text` の前に挟む。
