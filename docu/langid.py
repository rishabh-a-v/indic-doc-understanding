from collections import Counter

SCRIPTS = {
    "Devanagari": ((0x0900, 0x097F), "hi"),
    "Bengali": ((0x0980, 0x09FF), "bn"),
    "Gurmukhi": ((0x0A00, 0x0A7F), "pa"),
    "Gujarati": ((0x0A80, 0x0AFF), "gu"),
    "Oriya": ((0x0B00, 0x0B7F), "or"),
    "Tamil": ((0x0B80, 0x0BFF), "ta"),
    "Telugu": ((0x0C00, 0x0C7F), "te"),
    "Kannada": ((0x0C80, 0x0CFF), "kn"),
    "Malayalam": ((0x0D00, 0x0D7F), "ml"),
    "Latin": ((0x0041, 0x007A), "en"),
}

LANGS = {
    "hi": ("Hindi", "hin_Deva", "hin"),
    "mr": ("Marathi", "mar_Deva", "mar"),
    "bn": ("Bengali", "ben_Beng", "ben"),
    "pa": ("Punjabi", "pan_Guru", "pan"),
    "gu": ("Gujarati", "guj_Gujr", "guj"),
    "or": ("Odia", "ory_Orya", "ori"),
    "ta": ("Tamil", "tam_Taml", "tam"),
    "te": ("Telugu", "tel_Telu", "tel"),
    "kn": ("Kannada", "kan_Knda", "kan"),
    "ml": ("Malayalam", "mal_Mlym", "mal"),
    "en": ("English", "eng_Latn", "eng"),
}

MARATHI_MARKERS = ["आहे", "च्या", "ळ", "नाव", "चे ", "ची ", "करावे", "अर्ज", "जिल्हा", "क्रमांक", "दाखला", "तारीख"]
HINDI_MARKERS = ["है", "का ", "की ", "के ", "नाम", "जिला", "संख्या", "तिथि", "प्रमाण पत्र", "द्वारा"]


def script_histogram(text: str) -> Counter:
    c = Counter()
    for ch in text:
        cp = ord(ch)
        for name, ((lo, hi), _) in SCRIPTS.items():
            if lo <= cp <= hi:
                if name == "Latin" and not ch.isalpha():
                    break
                c[name] += 1
                break
    return c


def detect_language(text: str) -> str:
    hist = script_histogram(text)
    if not hist:
        return "en"
    indic = {k: v for k, v in hist.items() if k != "Latin"}
    if indic and max(indic.values()) >= 0.2 * sum(hist.values()):
        script = max(indic, key=indic.get)
    else:
        script = hist.most_common(1)[0][0]
    lang = SCRIPTS[script][1]
    if script == "Devanagari":
        mr = sum(text.count(m) for m in MARATHI_MARKERS)
        hi = sum(text.count(m) for m in HINDI_MARKERS)
        lang = "mr" if mr > hi else "hi"
    return lang


def lang_name(code: str) -> str:
    return LANGS.get(code, (code,))[0]


def flores(code: str) -> str:
    return LANGS[code][1]


def tess(code: str) -> str:
    return LANGS[code][2]
