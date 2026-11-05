import argparse
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from docu.normalize import (ascii_digits, digits_only, norm_amount, norm_date, norm_for_match)
from docu.schema import AMOUNT_FIELDS, DATE_FIELDS, ID_FIELDS, TEXT_FIELDS

ROOT = Path(__file__).parent
DIGIT_FIELDS = {"mobile", "pin_code", "units_consumed", "consumer_number"}


def canon(field: str, s: str) -> str:
    s = s or ""
    if field in DATE_FIELDS:
        return norm_date(s) or norm_for_match(s)
    if field in AMOUNT_FIELDS:
        return norm_amount(s)
    if field in DIGIT_FIELDS:
        return digits_only(s)
    if field in ID_FIELDS:
        return re.sub(r"[^A-Z0-9]", "", ascii_digits(s).upper())
    return norm_for_match(s)


def field_match(field, preds, golds, lenient=False) -> bool:
    for p in preds:
        cp = canon(field, p)
        if not cp:
            continue
        for g in golds:
            cg = canon(field, g)
            if cp == cg:
                return True
            if lenient and field in TEXT_FIELDS and fuzz.ratio(cp, cg) >= 85:
                return True
    return False


def cer(pred: str, gold: str) -> float:
    p, g = norm_for_match(pred), norm_for_match(gold)
    return Levenshtein.distance(p, g) / max(1, len(g))


def answer_match(field, answer_texts, golds) -> tuple[bool, bool, float]:
    exact = field_match(field, answer_texts, golds)
    correct = exact
    if not correct:
        for a in answer_texts:
            if field in DATE_FIELDS:
                ds = {norm_date(m.group(0)) for m in re.finditer(r"\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*\d{2,4}", ascii_digits(a))}
                correct |= any(norm_date(g) in ds for g in golds)
            elif field in AMOUNT_FIELDS | DIGIT_FIELDS:
                nums = {n.replace(",", "") for n in re.findall(r"\d[\d,]*", ascii_digits(a))}
                correct |= any(canon(field, g) in nums for g in golds)
            elif field in ID_FIELDS:
                correct |= any(canon(field, g) in canon(field, a) for g in golds)
            else:
                na = norm_for_match(a)
                correct |= any(norm_for_match(g) in na or fuzz.partial_ratio(norm_for_match(g), na) >= 90
                               for g in golds if g)
    f1 = 0.0
    for a in answer_texts:
        at = norm_for_match(a).split()
        for g in golds:
            gt = norm_for_match(g).split()
            common = sum((Counter(at) & Counter(gt)).values())
            if common:
                pr, rc = common / len(at), common / len(gt)
                f1 = max(f1, 2 * pr * rc / (pr + rc))
    return exact, correct, f1


def field_error_category(field, golds, pred, doc) -> str:
    in_ocr = field_match(field, [doc.ocr_text], golds) or any(
        canon(field, g) and canon(field, g) in canon(field, doc.ocr_text) for g in golds)
    if not in_ocr:
        return "ocr_error"
    if pred is None:
        for label, label_en, value, fname in doc.extraction.pairs:
            if fname is None or fname == field:
                continue
            if field_match(field, [value], golds):
                return "label_mapped_to_wrong_field"
        for label, label_en, value, fname in doc.extraction.pairs:
            if field_match(field, [value], golds) and fname is None:
                return "label_translation_unmatched"
        return "label_value_not_paired"
    return "value_split_or_normalisation"


def qa_error_category(row, doc, gold_field_ok) -> str:
    if row["tool"] == "field_lookup":
        if row["routed_field"] != row["field"]:
            return "routed_to_wrong_field"
        return "extracted_field_wrong" if not gold_field_ok else "answer_format"
    if row["tool"] == "none":
        return "no_answer"
    if row["tool"].startswith("patram"):
        return "patram_wrong"
    return "rag_reader_wrong"


def evaluate(testset: Path, out: Path, use_patram: bool, limit: int | None, ablate: bool):
    from docu.pipeline import analyze
    from docu.qa import answer_question
    from docu.schema import QUESTION_RULES, match_rules, resolve_for_doc
    from docu.translate import translate

    manifest = json.loads((testset / "manifest.json").read_text())[:limit]
    frows, qrows = [], []
    t_start = time.time()
    for n, m in enumerate(manifest, 1):
        t0 = time.time()
        doc = analyze(str(testset / m["image"]), use_patram=use_patram)
        dt = time.time() - t0
        meta = {k: m.get(k) for k in ("id", "lang", "doc_type", "layout", "degradation", "native_digits")}
        field_ok = {}
        for f, golds in m["fields"].items():
            fv = doc.extraction.fields.get(f)
            preds = [fv.value, fv.value_en] if fv else []
            strict = field_match(f, preds, golds)
            lenient = field_match(f, preds, golds, lenient=True)
            field_ok[f] = strict
            frows.append({**meta, "field": f, "gold": golds[0], "pred": fv.value if fv else "",
                          "pred_en": fv.value_en if fv else "", "source": fv.source if fv else "",
                          "strict": strict, "lenient": lenient,
                          "cer": cer(fv.value if fv else "", golds[0]) if f in TEXT_FIELDS else None,
                          "error": "" if strict else field_error_category(f, golds, fv, doc),
                          "pred_doc_type": doc.extraction.doc_type, "pred_lang": doc.lang,
                          "ocr_conf": doc.ocr_conf})
        for q in m["questions"]:
            a = answer_question(q["q"], doc, use_patram=use_patram)
            q_en = a.trace[0].split(": ", 1)[1] if q["lang"] != "en" else q["q"]
            routed = resolve_for_doc(match_rules(q_en, QUESTION_RULES), doc.extraction.doc_type)
            exact, correct, f1 = answer_match(q["field"], [a.text, a.text_en], q["gold"])
            row = {**meta, "question": q["q"], "q_lang": "native" if q["lang"] != "en" else "en",
                   "field": q["field"], "gold": q["gold"][0], "answer": a.text, "answer_en": a.text_en,
                   "tool": a.tool, "routed_field": routed, "exact": exact, "correct": correct,
                   "f1": f1, "trace": " || ".join(a.trace)}
            if ablate:
                b = answer_question(q["q"], doc, use_patram=use_patram, use_router=False)
                row["norouter_answer"] = b.text_en
                row["norouter_correct"] = answer_match(q["field"], [b.text, b.text_en], q["gold"])[1]
            row["error"] = "" if correct else qa_error_category(row, doc, field_ok.get(q["field"], True))
            qrows.append(row)
        acc = sum(r["strict"] for r in frows if r["id"] == m["id"]) / len(m["fields"])
        print(f"[{n}/{len(manifest)}] {m['id']:<30} lang={doc.lang} type={doc.extraction.doc_type:<18} "
              f"fields={acc:.0%} {dt:.1f}s", flush=True)
    fdf, qdf = pd.DataFrame(frows), pd.DataFrame(qrows)
    out.mkdir(parents=True, exist_ok=True)
    fdf.to_csv(out / "fields.csv", index=False)
    qdf.to_csv(out / "qa.csv", index=False)
    metrics = summarise(fdf, qdf, manifest, time.time() - t_start, use_patram)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=1, ensure_ascii=False))
    charts(fdf, qdf, out)
    write_report(fdf, qdf, metrics, out)
    print(json.dumps(metrics["headline"], indent=1))
    return metrics


def _by(df, col, metric):
    return {str(k): round(float(v), 3) for k, v in df.groupby(col)[metric].mean().items()}


def summarise(fdf, qdf, manifest, secs, use_patram):
    docs = fdf.groupby("id").agg(all_ok=("strict", "all"), lang=("lang", "first"),
                                 pred_lang=("pred_lang", "first"), dt=("doc_type", "first"),
                                 pdt=("pred_doc_type", "first"))
    head = {
        "documents": len(manifest), "gold_fields": len(fdf), "questions": len(qdf),
        "field_accuracy_strict": round(fdf.strict.mean(), 3),
        "field_accuracy_lenient": round(fdf.lenient.mean(), 3),
        "documents_fully_correct": round(docs.all_ok.mean(), 3),
        "doc_type_accuracy": round((docs.dt == docs.pdt).mean(), 3),
        "language_id_accuracy": round((docs.lang == docs.pred_lang).mean(), 3),
        "text_field_mean_cer": round(fdf.cer.dropna().mean(), 3),
        "qa_accuracy": round(qdf.correct.mean(), 3),
        "qa_exact_match": round(qdf.exact.mean(), 3),
        "qa_token_f1": round(qdf.f1.mean(), 3),
        "patram": use_patram, "seconds_total": round(secs, 1),
        "seconds_per_doc": round(secs / max(1, len(manifest)), 1),
    }
    if "norouter_correct" in qdf:
        head["qa_accuracy_without_router"] = round(qdf.norouter_correct.mean(), 3)
    return {
        "headline": head,
        "field_by_language": _by(fdf, "lang", "strict"),
        "field_by_degradation": _by(fdf, "degradation", "strict"),
        "field_by_layout": _by(fdf, "layout", "strict"),
        "field_by_native_digits": _by(fdf, "native_digits", "strict"),
        "field_by_field": _by(fdf, "field", "strict"),
        "field_by_doc_type": _by(fdf, "doc_type", "strict"),
        "qa_by_language": _by(qdf, "lang", "correct"),
        "qa_by_question_language": _by(qdf, "q_lang", "correct"),
        "qa_by_tool": _by(qdf, "tool", "correct"),
        "qa_tool_usage": qdf.tool.value_counts().to_dict(),
        "field_errors": fdf[fdf.error != ""].error.value_counts().to_dict(),
        "qa_errors": qdf[qdf.error != ""].error.value_counts().to_dict(),
    }


BLUE, ORANGE, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df"


def _style(ax, title):
    ax.set_title(title, loc="left", fontsize=11, color=INK, pad=10)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def charts(fdf, qdf, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def grouped(col, title, fname, order=None):
        a = fdf.groupby(col).strict.mean()
        b = qdf.groupby(col).correct.mean()
        keys = order or list(a.index)
        fig, ax = plt.subplots(figsize=(7, 3.2), dpi=150)
        x = range(len(keys))
        w = 0.38
        ax.bar([i - w / 2 - 0.01 for i in x], [a.get(k, 0) for k in keys], w, color=BLUE,
               label="Field extraction (strict)")
        ax.bar([i + w / 2 + 0.01 for i in x], [b.get(k, 0) for k in keys], w, color=ORANGE,
               label="QA accuracy")
        ax.set_xticks(list(x), [str(k) for k in keys])
        ax.set_ylim(0, 1.05)
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        _style(ax, title)
        ax.legend(frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(0, -0.12), ncol=2,
                  labelcolor=MUTED)
        fig.tight_layout()
        fig.savefig(out / fname)
        plt.close(fig)

    grouped("lang", "Accuracy by document language", "by_language.png")
    grouped("degradation", "Accuracy by image degradation", "by_degradation.png",
            [k for k in ["clean", "scan", "photo", "lowres"] if k in set(fdf.degradation)])

    errs = pd.concat([fdf[fdf.error != ""].error.map(lambda e: "field: " + e),
                      qdf[qdf.error != ""].error.map(lambda e: "QA: " + e)]).value_counts()
    if len(errs):
        fig, ax = plt.subplots(figsize=(7, 0.35 * len(errs) + 1), dpi=150)
        ax.barh(list(errs.index)[::-1], list(errs.values)[::-1], color=BLUE, height=0.6)
        for i, v in enumerate(list(errs.values)[::-1]):
            ax.text(v + 0.3, i, str(v), va="center", fontsize=8, color=MUTED)
        _style(ax, "Failure categories (count)")
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        fig.tight_layout()
        fig.savefig(out / "failures.png")
        plt.close(fig)


ERROR_EXPLANATIONS = {
    "ocr_error": "the gold value never appears in the OCR text (misread characters, lost rows, digit/letter confusion)",
    "label_value_not_paired": "value is in the OCR text but no label/value pair was formed (missing ':' or table row split oddly)",
    "label_translation_unmatched": "a pair was formed but IndicTrans2's English label matched no field rule",
    "label_mapped_to_wrong_field": "the translated label matched a different field's rule",
    "value_split_or_normalisation": "a value was extracted but differs from gold (extra/missing tokens, normalisation)",
    "routed_to_wrong_field": "the QA agent's router sent the question to the wrong field",
    "extracted_field_wrong": "router chose the right field but the extracted value itself was wrong",
    "rag_reader_wrong": "no field matched; retrieval + extractive reader picked the wrong span",
    "patram_wrong": "Patram's answer did not contain the gold value",
    "no_answer": "the agent found nothing",
    "answer_format": "correct field and value, but the answer string did not match",
}


def write_report(fdf, qdf, metrics, out):
    h = metrics["headline"]
    L = [f"# Evaluation report\n",
         f"- Documents: **{h['documents']}**, gold fields: **{h['gold_fields']}**, questions: **{h['questions']}**",
         f"- Patram VLM enabled: **{h['patram']}**; runtime {h['seconds_per_doc']} s/doc\n",
         "## Headline metrics\n", "| Metric | Value |", "|---|---|"]
    for k, v in h.items():
        if isinstance(v, float):
            L.append(f"| {k} | {v:.1%} |" if v <= 1 and "seconds" not in k and "cer" not in k else f"| {k} | {v} |")
    for name in ("field_by_language", "field_by_degradation", "field_by_layout", "field_by_native_digits",
                 "field_by_field", "qa_by_language", "qa_by_question_language", "qa_by_tool"):
        L += [f"\n### {name.replace('_', ' ')}\n", "| key | accuracy |", "|---|---|"]
        L += [f"| {k} | {v:.1%} |" for k, v in metrics[name].items()]
    L += ["\n![by language](by_language.png)\n", "![by degradation](by_degradation.png)\n",
          "## Failure analysis\n", "![failures](failures.png)\n", "| Category | Count | Meaning |", "|---|---|---|"]
    for k, v in {**{"field: " + a: b for a, b in metrics["field_errors"].items()},
                 **{"QA: " + a: b for a, b in metrics["qa_errors"].items()}}.items():
        L.append(f"| {k} | {v} | {ERROR_EXPLANATIONS.get(k.split(': ')[1], '')} |")
    L += ["\n### Example field errors (up to 25)\n", "| doc | field | gold | predicted | category |", "|---|---|---|---|---|"]
    for _, r in fdf[fdf.error != ""].head(25).iterrows():
        L.append(f"| {r['id']} | {r['field']} | {r['gold']} | {r['pred'] or '—'} | {r['error']} |")
    L += ["\n### Example QA errors (up to 20)\n", "| doc | question | gold | answer | tool | category |",
          "|---|---|---|---|---|---|"]
    for _, r in qdf[qdf.error != ""].head(20).iterrows():
        L.append(f"| {r['id']} | {r['question']} | {r['gold']} | {str(r['answer'])[:60]} | {r['tool']} | {r['error']} |")
    (out / "report.md").write_text("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--testset", default=str(ROOT / "testset"))
    ap.add_argument("--patram", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-ablation", action="store_true")
    ap.add_argument("--run", default=None, help="results sub-folder name")
    a = ap.parse_args()
    run = a.run or ("patram" if a.patram else "local")
    evaluate(Path(a.testset), ROOT / "results" / run, a.patram, a.limit, not a.no_ablation)


if __name__ == "__main__":
    main()
