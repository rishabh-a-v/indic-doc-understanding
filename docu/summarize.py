from . import patram
from .langid import lang_name
from .schema import FIELD_LABELS
from .translate import translate

DOC_TYPE_NAMES = {
    "application_form": "an application form",
    "public_notice": "a public notice",
    "income_certificate": "an income certificate",
    "electricity_bill": "an electricity bill",
    "unknown": "a document",
}


def template_summary(doc) -> str:
    ex = doc.extraction
    f = {k: (v.value_en or v.value) for k, v in ex.fields.items()}
    s = [f"This is {DOC_TYPE_NAMES.get(ex.doc_type, 'a document')} written in {lang_name(doc.lang)}."]
    if ex.doc_type == "application_form":
        s.append(f"It was filed by {f.get('name', 'an applicant')}"
                 + (f" (child of {f['father_name']})" if "father_name" in f else "")
                 + (f" from {f['district']} district" if "district" in f else "") + ".")
    elif ex.doc_type == "public_notice":
        s.append(f"It is issued by {f.get('department', 'a government office')}"
                 + (f" on {f['date']}" if "date" in f else "") + ".")
        if "last_date" in f:
            s.append(f"The last date is {f['last_date']}"
                     + (f" and the fee is Rs. {f['fee']}" if "fee" in f else "") + ".")
    elif ex.doc_type == "income_certificate":
        s.append(f"It certifies that {f.get('name', 'the holder')}"
                 + (f" of {f['district']} district" if "district" in f else "")
                 + (f" has an annual income of Rs. {f['annual_income']}" if "annual_income" in f else "")
                 + ".")
    elif ex.doc_type == "electricity_bill":
        s.append(f"The bill for {f.get('name', 'the consumer')}"
                 + (f" is Rs. {f['bill_amount']}" if "bill_amount" in f else "")
                 + (f" for {f['units_consumed']} units" if "units_consumed" in f else "")
                 + (f", payable by {f['due_date']}" if "due_date" in f else "") + ".")
    body = [c.text_en for c in doc.index.chunks if c.kind == "line" and len(c.text_en) > 60]
    s += sorted(body, key=len, reverse=True)[:2]
    key = [f"{FIELD_LABELS[k]}: {v}" for k, v in f.items() if k in FIELD_LABELS]
    if key:
        s.append("Key details - " + "; ".join(key) + ".")
    return " ".join(s)


def summarize(doc) -> tuple[str, str, str]:
    method = "template+indictrans2"
    en = ""
    if doc.patram_on:
        try:
            en = patram.ask(doc.pages[0],
                            "Summarise this document in 3-4 plain English sentences for a citizen: "
                            "what it is, who issued it / who it concerns, key dates, amounts and "
                            "what action is required.\nOCR text translated to English:\n"
                            + doc.text_en[:2500], max_tokens=220)
            method = "patram+indictrans2"
        except Exception:
            en = ""
    if not en:
        en = template_summary(doc)
    native = ""
    if doc.lang != "en":
        from .translate import split_sentences
        native = " ".join(translate(split_sentences(en), "en", doc.lang))
    return en, native, method
