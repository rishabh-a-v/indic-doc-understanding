import re
from dataclasses import dataclass, field

import pytesseract
from PIL import Image

from . import config
from .ingest import preprocess
from .langid import detect_language, tess
from .normalize import clean

if config.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD

OSD_SCRIPT_TO_TESS = {
    "Devanagari": "hin+mar",
    "Bengali": "ben",
    "Gujarati": "guj",
    "Gurmukhi": "pan",
    "Oriya": "ori",
    "Tamil": "tam",
    "Telugu": "tel",
    "Kannada": "kan",
    "Malayalam": "mal",
    "Latin": "eng",
}
CANDIDATES = ["hin", "ben", "tam", "tel", "kan", "guj", "mal", "pan", "ori"]


@dataclass
class Word:
    text: str
    x0: int
    x1: int
    conf: float
    top: int = 0
    height: int = 0


@dataclass
class Line:
    words: list = field(default_factory=list)
    top: int = 0

    @property
    def text(self) -> str:
        return clean(" ".join(w.text for w in self.words))

    @property
    def conf(self) -> float:
        cs = [w.conf for w in self.words if w.conf >= 0]
        return sum(cs) / len(cs) if cs else 0.0

    def cells(self, gap_chars: float = 4.0) -> list[str]:
        if len(self.words) < 2:
            return [self.text] if self.words else []
        widths = sorted(max(1, w.x1 - w.x0) / max(1, len(w.text)) for w in self.words)
        char_w = widths[len(widths) // 2]
        cells, cur = [], [self.words[0]]
        for prev, w in zip(self.words, self.words[1:]):
            if w.x0 - prev.x1 > gap_chars * char_w:
                cells.append(cur)
                cur = []
            cur.append(w)
        cells.append(cur)
        return [clean(" ".join(w.text for w in c)) for c in cells]


@dataclass
class OCRResult:
    lang: str
    tess_lang: str
    lines: list
    mean_conf: float

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines if l.text)


TESS_TO_SCRIPT = {"hin": "Devanagari", "ben": "Bengali", "tam": "Tamil", "tel": "Telugu",
                  "kan": "Kannada", "guj": "Gujarati", "mal": "Malayalam", "pan": "Gurmukhi",
                  "ori": "Oriya"}


def _detect_tess_lang(img: Image.Image) -> str:
    from .langid import script_histogram

    crop = img.crop((0, 0, img.width, max(200, int(img.height * 0.4))))
    best, best_score = "eng", 0.0
    for lang in CANDIDATES:
        d = pytesseract.image_to_data(crop, lang=lang, config="--psm 4",
                                      output_type=pytesseract.Output.DICT)
        words = [(t, float(c)) for t, c in zip(d["text"], d["conf"]) if t.strip() and float(c) >= 0]
        if not words:
            continue
        hist = script_histogram("".join(t for t, _ in words))
        total = sum(hist.values()) or 1
        in_script = hist.get(TESS_TO_SCRIPT[lang], 0) / total
        conf = sum(c for _, c in words) / len(words) / 100
        score = conf * in_script * min(1.0, hist.get(TESS_TO_SCRIPT[lang], 0) / 20)
        if score > best_score:
            best, best_score = lang, score
    return "hin+mar" if best == "hin" else best


ID_LIKE = re.compile(r"^[A-Za-z0-9|()\[\]{}<>§¥।/\\.-]*[/-][A-Za-z0-9|()\[\]{}<>§¥।/\\.-]*$")


def _rerecognise_latin(g: Image.Image, words) -> None:
    for w in words:
        if not ID_LIKE.match(w.text) or not any(c.isdigit() for c in w.text):
            continue
        pad = max(4, w.height // 4)
        crop = g.crop((max(0, w.x0 - pad), max(0, w.top - pad), w.x1 + pad, w.top + w.height + pad))
        d = pytesseract.image_to_data(crop, lang="eng", config="--psm 7",
                                      output_type=pytesseract.Output.DICT)
        toks = [(t, float(c)) for t, c in zip(d["text"], d["conf"]) if t.strip()]
        if len(toks) == 1 and toks[0][1] > w.conf and re.search(r"\d", toks[0][0]):
            w.text, w.conf = toks[0]


def run_ocr(img: Image.Image, lang_hint: str | None = None) -> OCRResult:
    g = preprocess(img)
    tess_lang = tess(lang_hint) if lang_hint and lang_hint != "auto" else _detect_tess_lang(g)
    if "eng" not in tess_lang:
        tess_lang += "+eng"
    d = pytesseract.image_to_data(g, lang=tess_lang, config="--psm 4",
                                  output_type=pytesseract.Output.DICT)
    groups: dict = {}
    for i, t in enumerate(d["text"]):
        if not t.strip():
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        ln = groups.setdefault(key, Line(top=d["top"][i]))
        ln.words.append(Word(t, d["left"][i], d["left"][i] + d["width"][i], float(d["conf"][i]),
                             d["top"][i], d["height"][i]))
    if tess_lang.split("+")[0] != "eng":
        _rerecognise_latin(g, [w for ln in groups.values() for w in ln.words])
    lines = sorted(groups.values(), key=lambda l: (l.top, l.words[0].x0))
    for ln in lines:
        ln.words.sort(key=lambda w: w.x0)
    text = "\n".join(l.text for l in lines)
    lang = lang_hint if lang_hint and lang_hint != "auto" else detect_language(text)
    confs = [l.conf for l in lines if l.words]
    return OCRResult(lang, tess_lang, lines, sum(confs) / len(confs) if confs else 0.0)
