import base64
import io
import json
import re

import requests
from PIL import Image

from . import config


def available() -> bool:
    if not config.PATRAM_API_BASE:
        return False
    try:
        r = requests.get(f"{config.PATRAM_API_BASE}/models", timeout=5,
                         headers={"Authorization": f"Bearer {config.PATRAM_API_KEY}"})
        return r.ok
    except requests.RequestException:
        return False


def _data_url(img: Image.Image, max_side: int = 1600) -> str:
    img = img.convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def ask(img: Image.Image, prompt: str, max_tokens: int = 512, temperature: float = 0.0) -> str:
    payload = {
        "model": config.PATRAM_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": _data_url(img)}},
                {"type": "text", "text": prompt},
            ],
        }],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    r = requests.post(f"{config.PATRAM_API_BASE}/chat/completions", json=payload,
                      timeout=config.PATRAM_TIMEOUT,
                      headers={"Authorization": f"Bearer {config.PATRAM_API_KEY}"})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    blob = m.group(0)
    for attempt in (blob, re.sub(r",\s*}", "}", blob)):
        try:
            obj = json.loads(attempt)
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            continue
    return {}
