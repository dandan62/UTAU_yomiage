"""テキストを「読み（かな）」へ変換し、モーラ単位に分割するモジュール。

読み変換は 2 系統に対応:
  - pyopenjtalk（高品質・推奨。辞書のダウンロードが必要）
  - pykakasi（軽量フォールバック）

英語は UTAU 音源では発音できないため、カタカナ英語に変換してから
日本語と同じモーラ処理へ流す。変換は次の優先順位（すべて任意・無ければ自動でスキップ）:
  - alkana       … 約5万語の辞書ベース（既知語は綺麗）
  - e2k          … RNN モデルで未知語を推定（依存は numpy のみ）
  - alphabet2kana… 1文字ずつのスペル読み（略語・最終フォールバック）

どの変換器も無ければ、入力をそのままかなとして扱う。
"""

from __future__ import annotations

import re

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


# ─────────────────────────────────────────────────────────────
# 英語 → カタカナ
# ─────────────────────────────────────────────────────────────

# 英字の連続（語）を拾う。アポストロフィ・ハイフンは語内に含める。
_EN_RUN = re.compile(r"[A-Za-z][A-Za-z'\-]*")

_USE_E2K = True       # 一度失敗したら無効化して再試行しない
_e2k_c2k = None
_e2k_ngram = None


def _spell_out(word: str) -> str:
    """1文字ずつの英字読み（ABC → エービーシー）。最終フォールバック。"""
    try:
        from alphabet2kana import a2k
        return a2k(word.upper())
    except Exception:
        return word  # 何も無ければそのまま（pykakasi 等が拾うことも）


def _english_word_to_kana(word: str) -> str:
    # 1) alkana 辞書（約5万語）
    try:
        import alkana
        kana = alkana.get_kana(word.lower())
        if kana:
            return kana
    except Exception:
        pass

    # 2) e2k（辞書に無い語を機械学習で推定）
    global _USE_E2K, _e2k_c2k, _e2k_ngram
    if _USE_E2K:
        try:
            if _e2k_c2k is None:
                from e2k import C2K, NGram
                _e2k_c2k = C2K()
                _e2k_ngram = NGram()
            # NGram が True なら通常のスペル読み、False ならスペルアウト寄り
            if _e2k_ngram(word):
                return _e2k_c2k(word)
            return _e2k_ngram.as_is(word.lower())
        except Exception:
            _USE_E2K = False  # 未インストール等 → 以降は試さない

    # 3) スペル読み
    return _spell_out(word)


def replace_english(text: str) -> str:
    """文中の英単語をカタカナへ置換する。先頭から順に処理（部分一致の誤爆を防ぐ）。"""
    out: list[str] = []
    pos = 0
    for m in _EN_RUN.finditer(text):
        out.append(text[pos:m.start()])
        w = m.group()
        # 1〜2文字、または全大文字の略語はスペル読みのほうが自然なことが多い
        if len(w.replace("'", "").replace("-", "")) <= 2 or w.isupper():
            out.append(_spell_out(w))
        else:
            out.append(_english_word_to_kana(w))
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


# ─────────────────────────────────────────────────────────────

_USE_OPENJTALK = True  # 一度失敗したら無効化して再試行しない


def text_to_kana(text: str) -> str:
    """日本語＋英語テキストをカタカナの読みに変換する。"""
    global _USE_OPENJTALK

    # 0) 英単語を先にカタカナへ（UTAU音源は英語音素を出せないため）
    text = replace_english(text)

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
