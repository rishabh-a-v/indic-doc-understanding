import threading
from dataclasses import dataclass

import numpy as np

from . import config

_lock = threading.Lock()
_embedder = None
_qa = None


def embedder():
    global _embedder
    with _lock:
        if _embedder is None:
            from sentence_transformers import SentenceTransformer
            _embedder = SentenceTransformer(config.EMBED_MODEL, device="cpu")
    return _embedder


def qa_pipeline():
    global _qa
    with _lock:
        if _qa is None:
            from transformers import pipeline
            _qa = pipeline("question-answering", model=config.QA_MODEL, device=-1)
    return _qa


@dataclass
class Chunk:
    text_en: str
    text_native: str
    kind: str


class DocIndex:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = [c for c in chunks if c.text_en.strip()]
        self.emb = (embedder().encode([c.text_en for c in self.chunks], normalize_embeddings=True)
                    if self.chunks else np.zeros((0, 384)))

    def search(self, query_en: str, k: int = 4) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        q = embedder().encode([query_en], normalize_embeddings=True)[0]
        sims = self.emb @ q
        order = np.argsort(-sims)[:k]
        return [(self.chunks[i], float(sims[i])) for i in order]


def extractive_answer(question_en: str, context_en: str) -> tuple[str, float]:
    if not context_en.strip():
        return "", 0.0
    res = qa_pipeline()(question=question_en, context=context_en, handle_impossible_answer=False)
    return res["answer"].strip(), float(res["score"])
