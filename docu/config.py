import os

PATRAM_API_BASE = os.getenv("PATRAM_API_BASE", "").rstrip("/")
PATRAM_API_KEY = os.getenv("PATRAM_API_KEY", "EMPTY")
PATRAM_MODEL = os.getenv("PATRAM_MODEL", "bharatgenai/patram-7b-instruct")
PATRAM_TIMEOUT = int(os.getenv("PATRAM_TIMEOUT", "180"))

IT2_INDIC_EN = os.getenv("IT2_INDIC_EN", "ai4bharat/indictrans2-indic-en-dist-200M")
IT2_EN_INDIC = os.getenv("IT2_EN_INDIC", "ai4bharat/indictrans2-en-indic-dist-200M")

EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
QA_MODEL = os.getenv("QA_MODEL", "deepset/tinyroberta-squad2")

TESSERACT_CMD = os.getenv("TESSERACT_CMD", "")

DEVICE = os.getenv("DOCU_DEVICE", "")


def torch_device():
    import torch
    if DEVICE:
        return DEVICE
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"
