import json
import tempfile
from pathlib import Path

import gradio as gr

from docu import config, patram
from docu.langid import LANGS, lang_name
from docu.pipeline import analyze
from docu.qa import answer_question, suggested_questions
from docu.schema import FIELD_LABELS
from docu.summarize import summarize

ROOT = Path(__file__).parent
EXAMPLES = sorted((ROOT / "samples").glob("*.png"))[:8] or sorted((ROOT / "eval/testset").glob("*.png"))[:8]
RESULTS = ROOT / "eval/results"

LANG_CHOICES = [("Auto-detect", "auto")] + [(v[0], k) for k, v in LANGS.items() if k != "en"]


def status_md():
    up = patram.available()
    p = (f"🟢 Patram-7B endpoint connected (`{config.PATRAM_API_BASE}`)" if up else
         "⚪ Patram-7B not connected — running the CPU pipeline (Tesseract OCR + IndicTrans2 + RAG). "
         "Set `PATRAM_API_BASE` to enable the vision-language model.")
    return p


def run_analysis(file, lang, use_patram):
    if file is None:
        raise gr.Error("Upload an image or PDF first.")
    try:
        doc = analyze(file, lang_hint=lang, use_patram=use_patram)
    except RuntimeError as e:
        raise gr.Error(str(e)) from e
    ex = doc.extraction
    rows = [[FIELD_LABELS.get(k, k), v.value, v.value_en if v.value_en != v.value else "",
             v.source, f"{v.confidence:.2f}"] for k, v in ex.fields.items()]
    en, native, method = summarize(doc)
    summary = (f"**Document type:** {ex.doc_type.replace('_', ' ')}  ·  **Language:** {lang_name(doc.lang)}"
               f"  ·  **OCR confidence:** {doc.ocr_conf:.0f}%  ·  **Method:** {method}\n\n"
               f"### English\n{en}\n")
    if native:
        summary += f"\n### {lang_name(doc.lang)}\n{native}\n"
    data = {"document_type": ex.doc_type, "language": doc.lang,
            "fields": {k: {"value": v.value, "english": v.value_en, "source": v.source,
                           "confidence": round(v.confidence, 2)} for k, v in ex.fields.items()},
            "summary_en": en, "summary_native": native}
    out = Path(tempfile.mkdtemp()) / "extraction.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    ocr_view = "\n".join(f"{n}\n   → {e}" for n, e in zip(doc.lines_native, doc.lines_en))
    timing = " · ".join(f"{k} {v:.1f}s" for k, v in doc.timings.items())
    sugg = suggested_questions(doc)
    return (doc, rows, summary, str(out), ocr_view, f"⏱ {timing}", [],
            gr.update(samples=[[q] for q in sugg]) if sugg else gr.update())


def ask(question, history, doc, use_patram):
    if doc is None:
        raise gr.Error("Analyse a document first.")
    if not question.strip():
        return history, "", ""
    a = answer_question(question, doc, use_patram=use_patram and doc.patram_on)
    reply = a.text if a.text == a.text_en else f"{a.text}\n\n_({a.text_en})_"
    reply += f"\n\n<sub>tool: {a.tool} · confidence {a.confidence:.2f}</sub>"
    history = history + [{"role": "user", "content": question},
                         {"role": "assistant", "content": reply}]
    trace = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(a.trace))
    return history, "", trace


def eval_md():
    for run in ("patram", "final", "local"):
        rep = RESULTS / run / "report.md"
        if rep.exists():
            txt = rep.read_text()
            for png in (RESULTS / run).glob("*.png"):
                txt = txt.replace(f"({png.name})", f"(/gradio_api/file={png})")
            return f"_Run: `{run}`_\n\n" + txt
    return "No evaluation run yet. Run `python -m eval.run_eval`."


with gr.Blocks(title="Indian Document Understanding") as demo:
    doc_state = gr.State(None)
    gr.Markdown("# 📄 Indian Document Understanding Tool\n"
                "Upload a notice, form, certificate or bill in an Indian language — extract fields, "
                "read a summary in English and in the original language, and ask questions in either.")
    status = gr.Markdown(status_md())
    with gr.Row():
        with gr.Column(scale=4):
            file = gr.File(label="Document (image or PDF)", file_types=["image", ".pdf"], type="filepath")
            preview = gr.Image(label="Preview", interactive=False, height=360)
            with gr.Row():
                lang = gr.Dropdown(LANG_CHOICES, value="auto", label="Language")
                use_patram = gr.Checkbox(value=True, label="Use Patram VLM if connected")
            go = gr.Button("Analyse document", variant="primary")
            timing = gr.Markdown()
            if EXAMPLES:
                gr.Examples([[str(p)] for p in EXAMPLES], inputs=[file], label="Sample documents")
        with gr.Column(scale=6):
            with gr.Tabs():
                with gr.Tab("Fields"):
                    table = gr.Dataframe(headers=["Field", "Value (as printed)", "English", "Source",
                                                  "Confidence"], interactive=False, wrap=True)
                    dl = gr.File(label="Download JSON")
                with gr.Tab("Summary"):
                    summary = gr.Markdown()
                with gr.Tab("Ask questions"):
                    chat = gr.Chatbot(height=340, label="Document Q&A")
                    q = gr.Textbox(placeholder="Ask in English or the document's language, e.g. "
                                               "'What is the last date?' / 'अंतिम तिथि क्या है?'",
                                   show_label=False)
                    sugg = gr.Dataset(components=[q], samples=[["What is the name?"]],
                                      label="Suggested questions")
                    with gr.Accordion("Agent trace", open=False):
                        trace = gr.Markdown()
                with gr.Tab("OCR + translation"):
                    ocr_box = gr.Textbox(lines=18, label="OCR line → IndicTrans2 English", max_lines=40)
                with gr.Tab("Evaluation"):
                    gr.Markdown(eval_md())

    file.change(lambda f: f if f and not str(f).lower().endswith(".pdf") else None, file, preview)
    go.click(run_analysis, [file, lang, use_patram],
             [doc_state, table, summary, dl, ocr_box, timing, chat, sugg])
    q.submit(ask, [q, chat, doc_state, use_patram], [chat, q, trace])
    sugg.click(lambda s: s[0], sugg, q)
    demo.load(status_md, None, status)

if __name__ == "__main__":
    demo.queue().launch(allowed_paths=[str(RESULTS)], show_error=True)
