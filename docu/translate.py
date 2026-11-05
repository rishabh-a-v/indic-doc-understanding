import re
import threading

from . import config
from .langid import flores

try:
    from IndicTransToolkit.processor import IndicProcessor
except ImportError:
    from IndicTransToolkit import IndicProcessor

_lock = threading.Lock()
_models: dict = {}
_cache: dict = {}


def _load(ckpt: str):
    with _lock:
        if ckpt not in _models:
            import torch
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

            try:
                tok = AutoTokenizer.from_pretrained(ckpt, trust_remote_code=True)
            except OSError as e:
                if "gated" in str(e).lower() or "401" in str(e):
                    raise RuntimeError(
                        f"{ckpt} is a gated model. Accept its terms at https://huggingface.co/{ckpt} "
                        "and run `hf auth login` (or set HF_TOKEN), then retry.") from e
                raise
            model = AutoModelForSeq2SeqLM.from_pretrained(ckpt, trust_remote_code=True,
                                                          torch_dtype=torch.float32)
            model.to(config.torch_device()).eval()
            _models[ckpt] = (tok, model, IndicProcessor(inference=True))
    return _models[ckpt]


def translate(sentences: list[str], src: str, tgt: str, num_beams: int = 4,
              batch_size: int = 16) -> list[str]:
    if src == tgt:
        return list(sentences)
    import torch

    ckpt = config.IT2_INDIC_EN if tgt == "en" else config.IT2_EN_INDIC
    if src != "en" and tgt != "en":
        return translate(translate(sentences, src, "en"), "en", tgt)
    tok, model, ip = _load(ckpt)
    s_code, t_code = flores(src), flores(tgt)
    out = [None] * len(sentences)
    todo = []
    for i, s in enumerate(sentences):
        key = (s, src, tgt)
        if not s.strip():
            out[i] = ""
        elif key in _cache:
            out[i] = _cache[key]
        else:
            todo.append(i)
    for b in range(0, len(todo), batch_size):
        idx = todo[b:b + batch_size]
        batch = ip.preprocess_batch([sentences[i] for i in idx], src_lang=s_code, tgt_lang=t_code)
        enc = tok(batch, truncation=True, padding="longest", return_tensors="pt",
                  return_attention_mask=True).to(model.device)
        with torch.inference_mode():
            gen = model.generate(**enc, use_cache=True, min_length=0, max_length=256,
                                 num_beams=num_beams, num_return_sequences=1)
        dec = tok.batch_decode(gen, skip_special_tokens=True, clean_up_tokenization_spaces=True)
        dec = ip.postprocess_batch(dec, lang=t_code)
        for i, d in zip(idx, dec):
            out[i] = d.strip()
            _cache[(sentences[i], src, tgt)] = out[i]
    return out


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[।.!?॥])\s+|\n+", text)
    return [p.strip() for p in parts if p.strip()]


def translate_text(text: str, src: str, tgt: str) -> str:
    sents = split_sentences(text)
    return "\n".join(translate(sents, src, tgt))
