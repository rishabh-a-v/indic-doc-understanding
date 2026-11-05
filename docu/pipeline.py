import time
from dataclasses import dataclass, field

from PIL import Image

from . import patram
from .extract import Extraction, add_english_values, merge, patram_extract, rule_extract
from .ingest import load_pages
from .normalize import norm_for_match
from .ocr import run_ocr
from .rag import Chunk, DocIndex
from .schema import FIELD_LABELS
from .translate import translate


@dataclass
class DocState:
    pages: list
    lang: str
    ocr_text: str
    ocr_conf: float
    lines_native: list
    lines_en: list
    extraction: Extraction
    index: DocIndex
    patram_on: bool
    timings: dict = field(default_factory=dict)

    @property
    def text_en(self) -> str:
        return "\n".join(self.lines_en)

    @property
    def ocr_norm(self) -> str:
        return norm_for_match(self.ocr_text)


def analyze(path_or_img, lang_hint: str = "auto", use_patram: bool | None = None) -> DocState:
    t = {}
    t0 = time.time()
    pages = [path_or_img] if isinstance(path_or_img, Image.Image) else load_pages(path_or_img)
    lines, confs, lang = [], [], None
    for p in pages:
        r = run_ocr(p, lang_hint)
        lines += [l for l in r.lines if l.text]
        confs.append(r.mean_conf)
        lang = lang or r.lang
    t["ocr"] = time.time() - t0

    t0 = time.time()
    native = [l.text for l in lines]
    english = translate(native, lang, "en") if lang != "en" else native
    t["translate"] = time.time() - t0

    t0 = time.time()
    ex = rule_extract(lines, lang)
    patram_on = patram.available() if use_patram is None else (use_patram and patram.available())
    if patram_on:
        try:
            vlm = patram_extract(pages[0], ex.doc_type, "\n".join(english))
            ex = merge(ex, vlm, "\n".join(native))
            add_english_values(ex, lang)
        except Exception as e:
            ex.pairs.append(("patram_error", str(e), "", None))
    t["extract"] = time.time() - t0

    chunks = [Chunk(e, n, "line") for n, e in zip(native, english)]
    chunks += [Chunk(f"{FIELD_LABELS.get(k, k)}: {v.value_en or v.value}", v.value, "fact")
               for k, v in ex.fields.items()]
    idx = DocIndex(chunks)
    return DocState(pages, lang, "\n".join(native), sum(confs) / max(1, len(confs)),
                    native, english, ex, idx, patram_on, t)
