"""WORLD ボコーダーを使って UTAU音源を「喋らせる」合成エンジン。

UTAU の resampler / wavtool（Windows製 exe）に頼らず、pyworld でクロスプラットフォームに
合成する。CV（単独音）と VCV（連続音）の両方に自動対応する。

処理の流れ:
  テキスト → モーラ列 → エイリアス解決（CV: "か" / VCV: "前母音 か" + 語頭 "- か"）
  → oto.ini でサンプル領域を切り出し → WORLD で解析
  → 子音部を保ったまま母音部を伸縮 → ピッチを一定化（棒読み）
  → 再合成 → オーバーラップ量でクロスフェード連結
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pyworld as pw
from scipy.io import wavfile

from .oto import OtoEntry, parse_oto
from .kana import text_to_moras, mora_vowel, _hira_to_kata, _kata_to_hira

FRAME_PERIOD = 5.0  # ms（WORLDの標準）
_PITCH_RE = re.compile(r"\s*[A-G]#?\d+\s*$")  # 末尾の音高（D3, C4, A#3 ...）


def _strip_pitch(alias: str) -> str:
    return _PITCH_RE.sub("", alias).strip()


def load_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    """wav を float64 モノラル [-1,1] + サンプリングレートで返す。"""
    fs, data = wavfile.read(path)
    if data.dtype == np.int16:
        x = data.astype(np.float64) / 32768.0
    elif data.dtype == np.int32:
        x = data.astype(np.float64) / 2147483648.0
    elif data.dtype == np.uint8:
        x = (data.astype(np.float64) - 128.0) / 128.0
    else:
        x = data.astype(np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return np.ascontiguousarray(x), fs


def _stretch_frames(arr: np.ndarray, fixed: int, target_total: int) -> np.ndarray:
    """先頭 fixed フレームは固定、残り（母音部）を伸縮して合計 target_total に。"""
    fixed = max(0, min(fixed, len(arr)))
    head = arr[:fixed]
    tail = arr[fixed:]
    target_tail = max(1, target_total - fixed)
    if len(tail) == 0:
        tail = arr[-1:].repeat(target_tail, axis=0)
    else:
        idx = np.linspace(0, len(tail) - 1, target_tail)
        lo = np.floor(idx).astype(int)
        hi = np.minimum(lo + 1, len(tail) - 1)
        frac = (idx - lo).reshape([-1] + [1] * (tail.ndim - 1))
        tail = tail[lo] * (1 - frac) + tail[hi] * frac
    return np.concatenate([head, tail], axis=0)


class UtauSpeaker:
    """UTAU音源を読み込み、テキストを音声波形へ変換する。CV/VCV 自動対応。"""

    def __init__(
        self,
        voicebank_dir: str | Path,
        pitch_hz: float = 130.0,
        mora_ms: float = 200.0,
        pause_ms: float = 220.0,
        sokuon_ms: float = 120.0,
        max_fixed_ms: float = 90.0,  # 固定範囲の上限（喋りを間延びさせない）
    ):
        self.dir = Path(voicebank_dir)
        self.oto = parse_oto(self.dir)
        self.pitch_hz = pitch_hz
        self.mora_ms = mora_ms
        self.pause_ms = pause_ms
        self.sokuon_ms = sokuon_ms
        self.max_fixed_ms = max_fixed_ms
        self._wav_cache: dict[str, tuple[np.ndarray, int]] = {}
        self.fs: int | None = None

        # 音高サフィックスを除去した core でも引けるようにする
        self.core_lookup: dict[str, OtoEntry] = {}
        for entry in self.oto.values():
            self.core_lookup.setdefault(_strip_pitch(entry.alias), entry)

        # VCV（連続音）かどうか自動判別
        self.is_vcv = any(
            " " in c and not c.startswith("- ") for c in self.core_lookup
        )

    # ---- エイリアス解決 ----
    def _lookup(self, *cands: str) -> OtoEntry | None:
        for c in cands:
            e = self.core_lookup.get(c) or self.oto.get(c)
            if e:
                return e
        return None

    def _find(self, mora: str, prev_vowel: str) -> tuple[OtoEntry | None, bool]:
        """モーラのエントリと「語頭か」を返す。"""
        hira = _kata_to_hira(mora)
        kata = _hira_to_kata(mora)
        if self.is_vcv:
            e = self._lookup(f"{prev_vowel} {hira}", f"{prev_vowel} {kata}")
            if e:
                return e, False
            e = self._lookup(f"- {hira}", f"- {kata}", hira, kata)
            return e, True
        # CV（単独音）
        e = self._lookup(hira, kata, f"- {hira}", f"- {kata}")
        return e, True

    def _get_wav(self, name: str) -> tuple[np.ndarray, int]:
        if name not in self._wav_cache:
            self._wav_cache[name] = load_wav_mono(self.dir / name)
        return self._wav_cache[name]

    # ---- 1モーラを合成 ----
    def _synth(self, entry: OtoEntry, target_ms: float, is_start: bool):
        x, fs = self._get_wav(entry.wav)
        self.fs = fs
        file_ms = len(x) / fs * 1000.0

        offset = max(0.0, entry.offset)
        if entry.cutoff >= 0:
            region_end = file_ms - entry.cutoff
        else:
            region_end = offset + (-entry.cutoff)
        region_end = min(file_ms, max(region_end, offset + 10))

        # VCVは前母音の繋ぎ部分(offset〜preutter)を削り、overlap分だけリードインを残す
        if self.is_vcv and not is_start:
            play_start = offset + max(0.0, entry.preutter - entry.overlap)
        else:
            play_start = offset
        play_start = min(play_start, region_end - 10)

        s = int(play_start / 1000 * fs)
        e = int(region_end / 1000 * fs)
        seg = np.ascontiguousarray(x[s:e])
        if len(seg) < fs * 0.02:
            seg = np.pad(seg, (0, int(fs * 0.02)))

        f0, t = pw.harvest(seg, fs, frame_period=FRAME_PERIOD)
        f0 = pw.stonemask(seg, f0, t, fs)
        sp = pw.cheaptrick(seg, f0, t, fs)
        ap = pw.d4c(seg, f0, t, fs)

        # 固定範囲（子音/オンセット）。喋り用に上限でキャップ
        fixed_ms = (offset + entry.consonant) - play_start
        fixed_ms = min(max(fixed_ms, 20.0), self.max_fixed_ms)
        fixed = int(round(fixed_ms / FRAME_PERIOD))
        target_total = max(fixed + 1, int(round(target_ms / FRAME_PERIOD)))

        f0_s = _stretch_frames(f0, fixed, target_total)
        sp_s = _stretch_frames(sp, fixed, target_total)
        ap_s = _stretch_frames(ap, fixed, target_total)

        voiced = f0_s > 0
        f0_s = np.where(voiced, self.pitch_hz, 0.0)

        y = pw.synthesize(f0_s, sp_s, ap_s, fs, frame_period=FRAME_PERIOD)
        fade_ms = entry.overlap if self.is_vcv and not is_start else 12.0
        return y, max(5.0, fade_ms)

    # ---- テキスト全体を合成 ----
    def speak(self, text: str) -> tuple[np.ndarray, int]:
        moras = text_to_moras(text)
        fs = self.fs or 44100
        notes: list[tuple[np.ndarray, float]] = []  # (audio, fade_ms)
        prev_vowel = "-"

        for mora in moras:
            if mora == "_PAUSE":
                notes.append((np.zeros(int(fs * self.pause_ms / 1000)), 0.0))
                prev_vowel = "-"
                continue
            if mora == "_SOKUON":
                notes.append((np.zeros(int(fs * self.sokuon_ms / 1000)), 0.0))
                continue
            if mora == "_CHOON":
                if notes and len(notes[-1][0]) > fs * 0.05:
                    seg, fd = notes[-1]
                    extra = int(fs * self.mora_ms / 1000)
                    tail = seg[-int(fs * 0.05):]
                    rep = np.tile(tail, max(1, extra // max(1, len(tail))))[:extra]
                    notes[-1] = (np.concatenate([seg, rep]), fd)
                continue

            entry, is_start = self._find(mora, prev_vowel)
            prev_vowel = mora_vowel(mora)
            if entry is None:
                notes.append((np.zeros(int(fs * 0.05)), 0.0))
                continue
            y, fade = self._synth(entry, self.mora_ms, is_start)
            fs = self.fs or fs
            notes.append((y, fade))

        if not notes:
            return np.zeros(1, dtype=np.int16), fs

        out = _concat([a for a, _ in notes], [f for _, f in notes], fs)
        out = _normalize(out)
        return (out * 32767).astype(np.int16), fs


def _concat(segs: list[np.ndarray], fades: list[float], fs: int) -> np.ndarray:
    out = segs[0].astype(np.float64)
    for seg, fade_ms in zip(segs[1:], fades[1:]):
        seg = seg.astype(np.float64)
        fade = int(fs * fade_ms / 1000)
        if fade > 0 and len(out) >= fade and len(seg) >= fade:
            ramp = np.linspace(0, 1, fade)
            out[-fade:] = out[-fade:] * (1 - ramp) + seg[:fade] * ramp
            out = np.concatenate([out, seg[fade:]])
        else:
            out = np.concatenate([out, seg])
    return out


def _normalize(x: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = np.max(np.abs(x)) if len(x) else 0.0
    return x * (peak / m) if m > 1e-6 else x
