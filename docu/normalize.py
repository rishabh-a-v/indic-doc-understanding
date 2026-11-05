import re
import unicodedata

_DIGIT_ZEROS = [0x0966, 0x09E6, 0x0A66, 0x0AE6, 0x0B66, 0x0BE6, 0x0C66, 0x0CE6, 0x0D66]
_DIGIT_MAP = {z + i: str(i) for z in _DIGIT_ZEROS for i in range(10)}


def ascii_digits(s: str) -> str:
    return s.translate(_DIGIT_MAP)


def clean(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "")
    s = ascii_digits(s)
    s = s.replace("‌", "").replace("‍", "")
    return re.sub(r"\s+", " ", s).strip()


def norm_for_match(s: str) -> str:
    s = clean(s).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def digits_only(s: str) -> str:
    return re.sub(r"\D", "", ascii_digits(s or ""))


DATE_RE = re.compile(r"\b(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{2,4})\b")
MOBILE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?([6-9]\d{4}\s?\d{5})(?!\d)")
PIN_RE = re.compile(r"(?<!\d)([1-9]\d{2}\s?\d{3})(?!\d)")
AMOUNT_RE = re.compile(r"(?:₹|rs\.?|inr|रु\.?|रुपये)\s*([\d,]+(?:\.\d{1,2})?)", re.I)


def norm_date(s: str) -> str:
    m = DATE_RE.search(ascii_digits(s or ""))
    if not m:
        return ""
    d, mth, y = m.groups()
    if len(y) == 2:
        y = "20" + y
    return f"{int(d):02d}/{int(mth):02d}/{y}"


def norm_amount(s: str) -> str:
    s = ascii_digits(s or "")
    m = re.search(r"\d[\d,]*(?:\.\d+)?", s)
    if not m:
        return ""
    v = m.group(0).replace(",", "")
    if v.endswith(".00"):
        v = v[:-3]
    return v
