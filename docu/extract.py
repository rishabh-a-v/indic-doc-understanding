import re
from dataclasses import dataclass, field

from . import patram
from .normalize import (AMOUNT_RE, MOBILE_RE, PIN_RE, ascii_digits, clean, digits_only,
                        norm_amount, norm_date, norm_for_match)
from .schema import (ALL_FIELDS, AMOUNT_FIELDS, DATE_FIELDS, DOC_TYPE_KEYWORDS, DOC_TYPES,
                     FIELD_LABELS, ID_FIELDS, LABEL_RULES, TEXT_FIELDS, match_rules,
                     resolve_for_doc)
from .translate import translate

SEPARATORS = re.compile(r"\s*[:：]\s*|[ःঃઃఃಃ](?=\s|\d)\s*")


@dataclass
class FieldValue:
    value: str
    value_en: str = ""
    source: str = "ocr"
    confidence: float = 0.5
    evidence: str = ""
    raw: str = ""


@dataclass
class Extraction:
    doc_type: str
    fields: dict = field(default_factory=dict)
    pairs: list = field(default_factory=list)

    def as_dict(self):
        return {k: v.value for k, v in self.fields.items()}


DIGIT_LOOKALIKES = str.maketrans({"ર": "2", "र": "2"})
NUMERIC_FIELDS = DATE_FIELDS | AMOUNT_FIELDS | {"mobile", "pin_code", "units_consumed"}


def normalise_value(fname: str, value: str) -> str:
    v = clean(value).strip(" .,;-–|'\`\"‘’“”")
    if fname in NUMERIC_FIELDS:
        v = " ".join(t.translate(DIGIT_LOOKALIKES) if re.search(r"\d", t) or
                     re.fullmatch(r"[રर.,/0-9]+", t) else t for t in v.split())
    if fname in DATE_FIELDS:
        return norm_date(v) or v
    if fname == "mobile":
        m = MOBILE_RE.search(v)
        return digits_only(m.group(1)) if m else digits_only(v)
    if fname == "pin_code":
        m = PIN_RE.search(v.replace(" ", ""))
        return m.group(1).replace(" ", "") if m else digits_only(v)
    if fname in AMOUNT_FIELDS:
        return norm_amount(v) or v
    if fname == "units_consumed":
        return digits_only(v.split()[0]) if v.split() else v
    if fname in ID_FIELDS:
        return re.sub(r"\s*([/\-])\s*", r"\1", ascii_digits(v)).replace(" ", "")
    return v


def line_pairs(line) -> list[tuple[str, str]]:
    cells = line.cells()
    pairs, pending = [], None
    expanded = []
    for c in cells:
        segs = SEPARATORS.split(c)
        if len(segs) > 2:
            label = segs[0]
            for mid in segs[1:-1]:
                toks = mid.split()
                expanded.append(f"{label}: {toks[0]}" if toks else label)
                label = " ".join(toks[1:])
            expanded.append(f"{label}: {segs[-1]}")
        else:
            expanded.append(c)
    cells = expanded
    for c in cells:
        parts = SEPARATORS.split(c, maxsplit=1)
        if len(parts) == 2:
            lab, val = parts[0].strip(), parts[1].strip()
            if lab and val:
                pairs.append((lab, val))
                pending = None
            elif lab:
                pending = lab
        elif c.endswith((":", "：")):
            pending = c.rstrip(":： ")
        elif pending:
            pairs.append((pending, c))
            pending = None
    if not pairs and len(cells) == 2:
        pairs = [(cells[0], cells[1])]
    return pairs


def classify_doc_type(title_en: str, found_fields: set) -> str:
    t = title_en.lower()
    for dt, kws in DOC_TYPE_KEYWORDS:
        if any(k in t for k in kws):
            return dt
    scores = {dt: len(found_fields & set(fs)) / len(fs) for dt, fs in DOC_TYPES.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"


LABEL_VOCAB = set("""name names full father father's fathers mother husband guardian parent date of
birth dob mobile phone telephone cell contact number no num serial reference ref id district
pin code postal zip post application applicant notice notification fee fees charge charges
department office certificate annual yearly income issue issued issuing grant granted given
consumer customer account units unit consumed consumption used usage bill amount total payable
due payment pay last deadline final closing day the a an s by for to on electricity""".split())


def _label_score(text_en: str) -> float:
    toks = [t.strip("'") for t in re.findall(r"[a-z']+", text_en.lower())]
    toks = [t for t in toks if t]
    return sum(t in LABEL_VOCAB for t in toks) / len(toks) if toks else 0.0


def _tr(texts, lang):
    uniq = list(dict.fromkeys(texts))
    out = translate(uniq, lang, "en") if lang != "en" else uniq
    return dict(zip(uniq, out))


def find_pairs(lines, lang):
    cand, orphans = [], []
    for i, ln in enumerate(lines):
        ps = [(l, v) for l, v in line_pairs(ln) if len(l) <= 60]
        if ps:
            cand += [(l, v, ln.text) for l, v in ps]
        elif 1 <= len(ln.words) <= 8:
            orphans.append(i)
    prefixes = {}
    for i in orphans:
        ws = lines[i].text.split()
        for k in range(1, min(4, len(ws)) + 1):
            prefixes[(i, k)] = " ".join(ws[:k])
        prefixes[(i, "full")] = lines[i].text
    tr = _tr([c[0] for c in cand] + list(prefixes.values()), lang)
    out = [(l, tr[l], v, raw) for l, v, raw in cand]

    title_words = [k for _, kws in DOC_TYPE_KEYWORDS for k in kws] + ["form"]

    def label_split(i):
        ws = lines[i].text.split()
        best = None
        full_en = tr[prefixes[(i, "full")]].lower()
        if any(re.search(rf"\b{re.escape(t)}\b", full_en) for t in title_words) and \
                not any(c.isdigit() for c in lines[i].text):
            return None
        for k in range(1, min(4, len(ws)) + 1):
            if any(c.isdigit() for c in ascii_digits(prefixes[(i, k)])):
                break
            en = tr[prefixes[(i, k)]]
            if match_rules(en, LABEL_RULES) and _label_score(en) >= 0.99:
                best = (k, en)
        return best

    used = set()
    for n, i in enumerate(orphans):
        if i in used:
            continue
        best = label_split(i)
        if not best:
            continue
        ws = lines[i].text.split()
        k, en = best
        if k < len(ws):
            value = " ".join(ws[k:])
        else:
            j = orphans[n + 1] if n + 1 < len(orphans) else None
            if j != i + 1 or label_split(j):
                continue
            value = lines[j].text
            used.add(j)
        used.add(i)
        out.append((" ".join(ws[:k]), en, value, lines[i].text))
    return out


def rule_extract(lines, lang: str) -> Extraction:
    pairs = find_pairs(lines, lang)
    title_lines = [l.text for l in lines[:3] if l.text]
    titles_en = translate(title_lines, lang, "en") if lang != "en" else title_lines

    unmatched = [(lab, val) for lab, en, val, _ in pairs if not match_rules(en, LABEL_RULES)]
    ctx_src = [f"{lab} : {val}" for lab, val in unmatched]
    ctx_en = dict(zip(ctx_src, translate(ctx_src, lang, "en"))) if ctx_src and lang != "en" else {}

    fields: dict = {}
    trace = []
    for label, label_en, value, raw in pairs:
        fname = match_rules(label_en, LABEL_RULES)
        if not fname and f"{label} : {value}" in ctx_en:
            head = re.split(r"[:：-]", ctx_en[f"{label} : {value}"], maxsplit=1)[0]
            if (f := match_rules(head, LABEL_RULES)) and _label_score(head) >= 0.99:
                fname, label_en = f, head + " (from context)"
        trace.append((label, label_en, value, fname))
        if fname and fname not in fields:
            fields[fname] = FieldValue(normalise_value(fname, value), source="ocr+indictrans2",
                                       confidence=0.6, evidence=raw, raw=value)
    doc_type = classify_doc_type(" ".join(titles_en), set(fields))

    if doc_type in DOC_TYPES:
        for f in list(fields):
            g = resolve_for_doc(f, doc_type)
            if g != f and g not in fields:
                fields[g] = fields.pop(f)
                fields[g].value = normalise_value(g, fields[g].raw or fields[g].value)

    if doc_type == "public_notice" and "department" not in fields and len(lines) >= 2:
        head = lines[0].text
        if not line_pairs(lines[0]) and len(head.split()) <= 8:
            fields["department"] = FieldValue(head, source="layout:letterhead", confidence=0.5,
                                              evidence=head, raw=head)

    full = ascii_digits("\n".join(l.text for l in lines))
    wanted = DOC_TYPES.get(doc_type, ALL_FIELDS)
    if "mobile" in wanted and "mobile" not in fields and (m := MOBILE_RE.search(full)):
        fields["mobile"] = FieldValue(digits_only(m.group(1)), source="regex", confidence=0.4)
    if "pin_code" in wanted and "pin_code" not in fields:
        cands = [c for c in PIN_RE.findall(full) if len(digits_only(c)) == 6]
        if cands:
            fields["pin_code"] = FieldValue(digits_only(cands[-1]), source="regex", confidence=0.3)
    for f in AMOUNT_FIELDS & set(wanted):
        if f not in fields and (m := AMOUNT_RE.search(full)):
            fields[f] = FieldValue(norm_amount(m.group(1)), source="regex", confidence=0.3)
    ex = Extraction(doc_type, fields, trace)
    add_english_values(ex, lang)
    return ex


def add_english_values(ex: Extraction, lang: str):
    keys = [k for k in ex.fields if k in TEXT_FIELDS and ex.fields[k].value]
    if lang != "en" and keys:
        outs = translate([ex.fields[k].value for k in keys], lang, "en")
        for k, o in zip(keys, outs):
            ex.fields[k].value_en = o
    for k, v in ex.fields.items():
        if not v.value_en:
            v.value_en = v.value


def patram_prompt(doc_type_hint: str, context_en: str) -> str:
    keys = DOC_TYPES.get(doc_type_hint, ALL_FIELDS)
    schema = ", ".join(f'"{k}"' for k in ["document_type"] + keys)
    return (
        "You are reading an Indian government document. Extract the key fields and return "
        f"ONLY a JSON object with these keys: {schema}. "
        "document_type must be one of application_form, public_notice, income_certificate, "
        "electricity_bill. Copy values exactly as printed (keep names in the original script), "
        "write dates as DD/MM/YYYY, amounts as plain numbers, and use null if a field is absent.\n"
        f"OCR text translated to English (may contain errors):\n{context_en[:2500]}"
    )


def patram_extract(img, doc_type_hint: str, context_en: str) -> Extraction:
    raw = patram.ask(img, patram_prompt(doc_type_hint, context_en), max_tokens=400)
    obj = patram.parse_json(raw)
    dt = obj.pop("document_type", None) or doc_type_hint
    fields = {}
    for k, v in obj.items():
        if k in FIELD_LABELS and v not in (None, "", "null"):
            fields[k] = FieldValue(normalise_value(k, str(v)), source="patram", confidence=0.6, raw=str(v))
    return Extraction(dt if dt in DOC_TYPES else doc_type_hint, fields, [("patram_raw", raw, "", None)])


def _supported_by_ocr(value: str, ocr_text_norm: str) -> bool:
    v = norm_for_match(value)
    return bool(v) and (v in ocr_text_norm or digits_only(value) and digits_only(value) in
                        digits_only(ocr_text_norm))


def merge(rule: Extraction, vlm: Extraction | None, ocr_text: str) -> Extraction:
    if vlm is None:
        return rule
    ocr_norm = norm_for_match(ocr_text)
    doc_type = vlm.doc_type if vlm.doc_type in DOC_TYPES else rule.doc_type
    out = {}
    for k in set(rule.fields) | set(vlm.fields):
        a, b = rule.fields.get(k), vlm.fields.get(k)
        if a and b:
            if norm_for_match(a.value) == norm_for_match(b.value):
                a.confidence, a.source = 0.95, "ocr+patram"
                out[k] = a
            elif _supported_by_ocr(b.value, ocr_norm) and not _supported_by_ocr(a.value, ocr_norm):
                b.confidence = 0.7
                out[k] = b
            else:
                a.confidence = 0.55
                out[k] = a
        else:
            out[k] = a or b
    ex = Extraction(doc_type, out, rule.pairs + vlm.pairs)
    return ex
