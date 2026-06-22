"""テキストを「読み（かな）」へ変換し、モーラ単位に分割するモジュール。

読み変換は 2 系統に対応:
  - pyopenjtalk（高品質・推奨。辞書のダウンロードが必要）
  - pykakasi（軽量フォールバック）

どちらも import できない/失敗する場合は、入力をそのままかなとして扱う。
"""

from __future__ import annotations

# 小書きかな（直前の文字と結合して 1 モーラになる）
_SMALL = set("ァィゥェォャュョヮ" "ぁぃぅぇぉゃゅょゎ")
# 特殊モーラ
_SOKUON = set("ッっ")   # 促音 → 無音ポーズ
_CHOON = "ー"           # 長音 → 直前の母音を伸ばす
_HATSUON = set("ンん")  # 撥音


def _hira_to_kata(s: str) -> str:
    out = []
    for ch in s:
        code = ord(ch)
        if 0x3041 <= code <= 0x3096:  # ひらがな → カタカナ
            out.append(chr(code + 0x60))
        else:
            out.append(ch)
    return "".join(out)


def _kata_to_hira(s: str) -> str:
    return "".join(
        chr(ord(c) - 0x60) if 0x30A1 <= ord(c) <= 0x30F6 else c for c in s
    )


# モーラ末尾のかな → 母音（VCV連続音のエイリアス組み立てに使う）
_VOWEL_MAP: dict[str, str] = {}
for _v, _row in {
    "a": "ぁあゃやかがさざただなはばぱまらわゎ",
    "i": "ぃいきぎしじちぢにひびぴみり",
    "u": "ぅうゅゆくぐすずつづぬふぶぷむる",
    "e": "ぇえけげせぜてでねへべぺめれ",
    "o": "ぉおょよこごそぞとどのほぼぽもろを",
}.items():
    for _ch in _row:
        _VOWEL_MAP[_ch] = _v
_VOWEL_MAP["ん"] = "n"


def mora_vowel(mora: str) -> str:
    """モーラの母音（a/i/u/e/o/n）を返す。VCVの「前の母音」推定に使う。"""
    hira = _kata_to_hira(mora)
    return _VOWEL_MAP.get(hira[-1], "a") if hira else "a"


_USE_OPENJTALK = True  # 一度失敗したら無効化して再試行しない


def text_to_kana(text: str) -> str:
    """日本語テキストをカタカナの読みに変換する。"""
    global _USE_OPENJTALK
    # 1) pyopenjtalk（高品質）
    if _USE_OPENJTALK:
        try:
            import pyopenjtalk

            kana = pyopenjtalk.g2p(text, kana=True)
            if kana:
                return _hira_to_kata(kana)
        except Exception:
            _USE_OPENJTALK = False  # 辞書未取得などで失敗 → 以降はフォールバック

    # 2) pykakasi（フォールバック）
    try:
        import pykakasi

        kks = pykakasi.kakasi()
        return "".join(r["kana"] for r in kks.convert(text))
    except Exception:
        pass

    # 3) 変換器が無ければ素通し（既にかなで来た場合など）
    return _hira_to_kata(text)


def split_mora(kana: str) -> list[str]:
    """カタカナ文字列をモーラのリストに分割する。

    記号や空白は "_PAUSE" として返し、ポーズ（無音）に使う。
    促音は "_SOKUON"、長音は "_CHOON" として返す。
    """
    moras: list[str] = []
    for ch in kana:
        if ch in _SMALL and moras and moras[-1] not in (
            "_PAUSE",
            "_SOKUON",
            "_CHOON",
        ):
            moras[-1] += ch  # 直前と結合（キャ など）
        elif ch in _SOKUON:
            moras.append("_SOKUON")
        elif ch == _CHOON:
            moras.append("_CHOON")
        elif ch in _HATSUON:
            moras.append(_hira_to_kata(ch))
        elif ch.isspace() or ch in "、。,.!?！？「」『』（）()…・":
            moras.append("_PAUSE")
        elif ch.strip():
            moras.append(ch)
    return moras


def text_to_moras(text: str) -> list[str]:
    return split_mora(text_to_kana(text))
