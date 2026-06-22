"""ダミーの CV単独音 音源を生成してエンジンを通しで検証する。

本物の音源が無くても、oto.ini解析 / WORLD解析 / 伸縮 / 連結 / 出力が
エラーなく動くかを確認するためのスモークテスト。
"""

import tempfile
from pathlib import Path

import numpy as np
from scipy.io import wavfile

import sys
sys.path.insert(0, str(Path(__file__).parent))
from engine.synth import UtauSpeaker
from engine.kana import text_to_moras

FS = 44100


def make_sample(path: Path, f0=150.0, dur=0.45, cons_ms=30):
    """子音ノイズ + 母音トーン の擬似サンプルを書き出す。"""
    n_cons = int(FS * cons_ms / 1000)
    cons = np.random.randn(n_cons) * 0.05  # 子音っぽいノイズ
    t = np.arange(int(FS * dur)) / FS
    vowel = np.zeros_like(t)
    for h, amp in enumerate([1.0, 0.6, 0.4, 0.3, 0.2, 0.15, 0.1], start=1):
        vowel += amp * np.sin(2 * np.pi * f0 * h * t)
    env = np.minimum(1.0, np.minimum(t * 30, (dur - t) * 10))
    vowel *= env
    sig = np.concatenate([cons, vowel])
    sig = (sig / np.max(np.abs(sig)) * 0.8 * 32767).astype(np.int16)
    wavfile.write(path, FS, sig)
    total_ms = len(sig) / FS * 1000
    return total_ms, cons_ms


def build_voicebank(d: Path):
    # ひらがなエイリアスで生成（kata→hira フォールバックも検証）
    moras = list("あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほ"
                 "まみむめもやゆよらりるれろわをん")
    lines = []
    for i, m in enumerate(moras):
        wav = f"{i:02d}_{m}.wav"
        total_ms, cons_ms = make_sample(d / wav, f0=140 + (i % 5) * 8)
        cutoff = -total_ms  # offset からの長さ指定（負値）
        # ファイル名=エイリアス,offset,consonant,cutoff,preutter,overlap
        lines.append(f"{wav}={m},0,{cons_ms},{cutoff:.1f},30,10")
    (d / "oto.ini").write_text("\n".join(lines), encoding="utf-8")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        vb = Path(tmp)
        build_voicebank(vb)
        print(f"ダミー音源を生成: {len(list(vb.glob('*.wav')))} サンプル")

        speaker = UtauSpeaker(vb, pitch_hz=130, mora_ms=170)
        print(f"oto.ini エントリ数: {len(speaker.oto)}")

        for text in ["こんにちは", "ゆっくりしていってね", "てすとです、よろしく"]:
            moras = text_to_moras(text)
            wav, fs = speaker.speak(text)
            dur = len(wav) / fs
            peak = int(np.max(np.abs(wav)))
            print(f"\n入力: {text}")
            print(f"  モーラ: {moras}")
            print(f"  出力: {len(wav)} samples / {dur:.2f}s @ {fs}Hz / peak={peak}")
            assert dur > 0.1 and peak > 1000, "出力が異常です"

        # 実ファイルとして1つ書き出して確認
        out = Path(tmp) / "out.wav"
        wav, fs = speaker.speak("おはようございます")
        wavfile.write(out, fs, wav)
        print(f"\n書き出しOK: {out.name} ({out.stat().st_size} bytes)")
        print("\n=== エンジン通しテスト 成功 ===")


if __name__ == "__main__":
    main()
