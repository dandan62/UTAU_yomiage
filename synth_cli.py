"""Discord を使わずに、テキスト→wav の合成を試すCLI。

使い方:
    python synth_cli.py "こんにちは" --voicebank ./voicebank -o out.wav
    python synth_cli.py "ゆっくりしていってね" --pitch 180 --mora 160

音源を入れたら、まずこれで声を確認・調整するのがおすすめです。
"""

import argparse
from pathlib import Path

from scipy.io import wavfile

from engine import UtauSpeaker
from engine.kana import text_to_moras


def main():
    ap = argparse.ArgumentParser(description="UTAU音源で読み上げ音声を生成")
    ap.add_argument("text", help="読み上げるテキスト")
    ap.add_argument("--voicebank", "-v", default="./voicebank", help="音源フォルダ")
    ap.add_argument("--out", "-o", default="out.wav", help="出力wav")
    ap.add_argument("--pitch", type=float, default=130.0, help="基本ピッチ(Hz)")
    ap.add_argument("--mora", type=float, default=200.0, help="1モーラの長さ(ms)")
    args = ap.parse_args()

    speaker = UtauSpeaker(args.voicebank, pitch_hz=args.pitch, mora_ms=args.mora)
    print(f"音源: {args.voicebank}（{len(speaker.oto)} エントリ）")
    print(f"モーラ: {text_to_moras(args.text)}")

    wav, fs = speaker.speak(args.text)
    wavfile.write(args.out, fs, wav)
    print(f"書き出し: {Path(args.out).resolve()}  ({len(wav)/fs:.2f}秒)")


if __name__ == "__main__":
    main()
