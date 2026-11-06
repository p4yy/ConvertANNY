"""Language selection, RTL detection, translation lookup/fallback/formatting and stylesheet font substitution."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import i18n


def check():
    original = i18n.language()
    try:
        some = next(code for code in i18n.T if code != "en")
        i18n.set_language(some)
        assert i18n.language() == some
        i18n.set_language("en")
        assert i18n.language() == "en" and not i18n.is_rtl()
        i18n.set_language("xx-not-a-language")
        assert i18n.language() == "en"                      # unknown codes fall back to English
        i18n.set_language("ar")
        assert i18n.language() == "ar" and i18n.is_rtl()
        i18n.set_language("fr")
        assert i18n.language() == "fr" and not i18n.is_rtl()
        for empty in ("", None):                            # empty = follow the system; always lands on a known language
            i18n.set_language(empty)
            assert i18n.language() == "en" or i18n.language() in i18n.T

        # lookup order: current language -> English table -> the key itself
        i18n.set_language("en")
        key = next(iter(i18n.EN))
        assert i18n.tr(key) == i18n.EN[key]
        assert i18n.tr("never translated text") == "never translated text"
        i18n.set_language("fr")
        fr_key = next(k for k, v in i18n.T["fr"].items() if v)
        assert i18n.tr(fr_key) == i18n.T["fr"][fr_key]
        # formatting: placeholders fill, bad/missing placeholders leave the text intact
        assert i18n.tr("Hello {name}", name="Ann") == "Hello Ann"
        assert i18n.tr("Hello {name}", other=1) == "Hello {name}"
        assert i18n.tr("Hello {0}", x=1) == "Hello {0}"
        assert i18n.tr("100% {x", x=1) == "100% {x"
        assert i18n.tr("Plain text") == "Plain text"

        # stylesheet templates get the interface font in place of the Segoe UI placeholder
        out = i18n.css("QLabel { font-family: 'Segoe UI'; }")
        assert "'Segoe UI'" not in out and f"'{i18n.ui_font()}'" in out
    finally:
        i18n.set_language(original)
    print("i18n language selection, RTL, lookup fallback, formatting and stylesheet font passed")


if __name__ == "__main__":
    check()
