from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

MAX_PAGES = 5


def load_pages(path: str, dpi: int = 200) -> list[Image.Image]:
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        import fitz

        pages = []
        with fitz.open(p) as doc:
            for page in list(doc)[:MAX_PAGES]:
                pix = page.get_pixmap(dpi=dpi)
                pages.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        return pages
    img = Image.open(p)
    img = ImageOps.exif_transpose(img)
    return [img.convert("RGB")]


def _normalise_background(g: np.ndarray) -> np.ndarray:
    k = max(31, (g.shape[1] // 30) | 1)
    bg = cv2.morphologyEx(g, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    bg = cv2.GaussianBlur(bg, (k, k), 0)
    return cv2.divide(g, bg, scale=255)


def _remove_rules(bw: np.ndarray) -> np.ndarray:
    inv = 255 - bw
    h_len, v_len = max(40, bw.shape[1] // 12), max(40, bw.shape[0] // 25)
    h = cv2.morphologyEx(inv, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (h_len, 1)))
    v = cv2.morphologyEx(inv, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, v_len)))
    lines = cv2.dilate(cv2.bitwise_or(h, v), np.ones((3, 3), np.uint8))
    return cv2.bitwise_or(bw, lines)


def _deskew_angle(bw: np.ndarray, max_angle: float = 5.0, step: float = 0.25) -> float:
    small = cv2.resize(255 - bw, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    h, w = small.shape
    best, best_score = 0.0, -1.0
    for a in np.arange(-max_angle, max_angle + step, step):
        m = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
        rot = cv2.warpAffine(small, m, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
        prof = rot.sum(axis=1).astype(np.float64)
        score = float(np.var(prof))
        if score > best_score:
            best, best_score = float(a), score
    return best


def preprocess(img: Image.Image, target_width: int = 2000) -> Image.Image:
    g = np.array(ImageOps.grayscale(img))
    if g.shape[1] < target_width:
        s = target_width / g.shape[1]
        g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    g = _normalise_background(g)
    g = cv2.fastNlMeansDenoising(g, None, h=12, templateWindowSize=7, searchWindowSize=21)
    _, bw = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw = _remove_rules(bw)
    angle = _deskew_angle(bw)
    if abs(angle) > 0.2:
        h, w = bw.shape
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        bw = cv2.warpAffine(bw, m, (w, h), flags=cv2.INTER_CUBIC, borderValue=255)
    return Image.fromarray(bw)
