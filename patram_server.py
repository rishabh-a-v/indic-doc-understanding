import base64
import io
import os
import time

import torch
import uvicorn
from fastapi import FastAPI
from PIL import Image
from pydantic import BaseModel

MODEL_ID = os.getenv("PATRAM_MODEL", "bharatgenai/patram-7b-instruct")
FOUR_BIT = os.getenv("PATRAM_4BIT", "0") == "1"

app = FastAPI(title="Patram server")
pipe = None


def load():
    global pipe
    from transformers import pipeline

    kw = {"device_map": "auto"}
    if FOUR_BIT:
        from transformers import BitsAndBytesConfig
        kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                       bnb_4bit_compute_dtype=torch.float16)
    else:
        kw["torch_dtype"] = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    pipe = pipeline("image-text-to-text", model=MODEL_ID, trust_remote_code=True, model_kwargs=kw)


class ChatRequest(BaseModel):
    model: str = MODEL_ID
    messages: list
    max_tokens: int = 512
    temperature: float = 0.0


def _decode_image(url: str) -> Image.Image:
    if url.startswith("data:"):
        return Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB")
    import requests
    return Image.open(io.BytesIO(requests.get(url, timeout=30).content)).convert("RGB")


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": MODEL_ID, "object": "model"}]}


@app.post("/v1/chat/completions")
def chat(req: ChatRequest):
    msgs = []
    for m in req.messages:
        content = m["content"]
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        parts = []
        for c in content:
            if c["type"] == "image_url":
                parts.append({"type": "image", "image": _decode_image(c["image_url"]["url"])})
            else:
                parts.append(c)
        msgs.append({"role": m["role"], "content": parts})
    gen = {"max_new_tokens": req.max_tokens, "do_sample": req.temperature > 0}
    if req.temperature > 0:
        gen["temperature"] = req.temperature
    out = pipe(text=msgs, generate_kwargs=gen, return_full_text=False)
    text = out[0]["generated_text"]
    if isinstance(text, list):
        text = text[-1]["content"]
    return {"id": f"chatcmpl-{int(time.time() * 1000)}", "object": "chat.completion",
            "model": MODEL_ID,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": str(text).strip()}}]}


if __name__ == "__main__":
    load()
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
