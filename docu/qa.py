from dataclasses import dataclass, field

from . import patram
from .langid import detect_language
from .normalize import digits_only, norm_for_match
from .rag import extractive_answer
from .schema import FIELD_LABELS, QUESTION_RULES, match_rules, resolve_for_doc
from .translate import translate


@dataclass
class Answer:
    text: str
    text_en: str
    tool: str
    confidence: float
    trace: list = field(default_factory=list)


def _supported(ans: str, doc) -> bool:
    a = norm_for_match(ans)
    if not a:
        return False
    hay = doc.ocr_norm + " " + norm_for_match(doc.text_en)
    if a in hay:
        return True
    d = digits_only(ans)
    return len(d) >= 3 and d in digits_only(doc.ocr_text)


def answer_question(question: str, doc, use_patram: bool | None = None,
                    use_router: bool = True) -> Answer:
    trace = []
    q_lang = detect_language(question)
    q_en = translate([question], q_lang, "en")[0] if q_lang != "en" else question
    if q_lang != "en":
        trace.append(f"translate question ({q_lang}->en): {q_en}")

    def finish(text_en, native, tool, conf):
        if q_lang != "en" and native is None:
            out = translate([text_en], "en", q_lang)[0]
        else:
            out = native if native is not None else text_en
        return Answer(out, text_en, tool, conf, trace)

    if use_router:
        f = resolve_for_doc(match_rules(q_en, QUESTION_RULES), doc.extraction.doc_type)
        fv = doc.extraction.fields.get(f) if f else None
        trace.append(f"field_lookup: routed to '{f}' -> {fv.value if fv else 'not extracted'}")
        if fv and fv.value:
            return finish(fv.value_en or fv.value, fv.value, "field_lookup", fv.confidence)

    hits = doc.index.search(q_en, k=5)
    context_en = "\n".join(c.text_en for c, _ in hits)
    trace.append("retrieve: " + " | ".join(f"{c.text_en[:50]} ({s:.2f})" for c, s in hits[:3]))

    if use_patram is None:
        use_patram = doc.patram_on
    if use_patram:
        prompt = (f"Answer the question about this document in a few words. "
                  f"Relevant OCR text (translated, may be noisy):\n{context_en}\n\n"
                  f"Question: {q_en}\nAnswer:")
        try:
            ans = patram.ask(doc.pages[0], prompt, max_tokens=64)
            ok = _supported(ans, doc)
            trace.append(f"patram_vqa: '{ans}' (verified in OCR: {ok})")
            if ans:
                return finish(ans, None, "patram_vqa", 0.8 if ok else 0.5)
        except Exception as e:
            trace.append(f"patram_vqa failed: {e}")

    ans, score = extractive_answer(q_en, context_en)
    trace.append(f"rag_extractive: '{ans}' (score {score:.2f})")
    if not ans:
        return finish("I could not find this in the document.", None, "none", 0.0)
    return finish(ans, None, "rag_extractive", score)


def suggested_questions(doc) -> list[str]:
    fs = list(doc.extraction.fields)[:4]
    return [f"What is the {FIELD_LABELS[f].lower()}?" for f in fs if f in FIELD_LABELS]
