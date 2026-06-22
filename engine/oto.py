"""UTAU音源の原音設定（oto.ini）パーサー。

oto.ini の各行は以下の形式:
    ファイル名.wav=エイリアス,オフセット,子音部,ブランク,先行発声,オーバーラップ

単位はすべてミリ秒。各値の意味:
    offset     : ファイル先頭から見た、サンプル領域の開始位置（左ブランク）
    consonant  : 伸縮させない固定範囲（子音部）。offset からの長さ
    cutoff     : 右ブランク。 >=0 ならファイル末尾からの距離、 <0 なら offset からの長さ(=-cutoff)
    preutter   : 先行発声
    overlap    : オーバーラップ（前の音と重ねる量）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class OtoEntry:
    wav: str          # wav ファイル名
    alias: str        # エイリアス（"あ" など）。空なら wav 名（拡張子なし）
    offset: float     # ms
    consonant: float  # ms
    cutoff: float     # ms（符号に注意。上記コメント参照）
    preutter: float   # ms
    overlap: float    # ms


def _to_float(s: str) -> float:
    s = s.strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_oto(voicebank_dir: str | Path) -> dict[str, OtoEntry]:
    """音源フォルダの oto.ini を読み込み、エイリアス→OtoEntry の辞書を返す。

    複数エンコーディングに対応（UTF-8 / Shift-JIS）。
    同じエイリアスが複数あれば最初のものを採用する。
    """
    voicebank_dir = Path(voicebank_dir)
    oto_path = voicebank_dir / "oto.ini"
    if not oto_path.exists():
        raise FileNotFoundError(f"oto.ini が見つかりません: {oto_path}")

    raw: bytes = oto_path.read_bytes()
    text = None
    for enc in ("utf-8-sig", "cp932", "shift_jis", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="ignore")

    entries: dict[str, OtoEntry] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        wav, _, params = line.partition("=")
        parts = params.split(",")
        # parts: alias, offset, consonant, cutoff, preutter, overlap
        parts += [""] * (6 - len(parts))
        alias = parts[0].strip() or Path(wav).stem
        entry = OtoEntry(
            wav=wav.strip(),
            alias=alias,
            offset=_to_float(parts[1]),
            consonant=_to_float(parts[2]),
            cutoff=_to_float(parts[3]),
            preutter=_to_float(parts[4]),
            overlap=_to_float(parts[5]),
        )
        entries.setdefault(alias, entry)
    return entries
