import json
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTCollection, TTFont
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from eval.lexicon import (DEPARTMENTS, DISTRICTS, EN_Q, LABELS, LANGS, NAMES, NATIVE_Q,
                          NOTICE_BODY, SIGNATURE, TITLES)

OUT = Path(__file__).parent / "testset"
SEED = 7
W, H = 1240, 1754

SYS = "/System/Library/Fonts/"
SUP = SYS + "Supplemental/"
FONTS = {
    "hi": SYS + "Kohinoor.ttc", "mr": SYS + "Kohinoor.ttc", "bn": SYS + "KohinoorBangla.ttc",
    "gu": SYS + "KohinoorGujarati.ttc", "te": SYS + "KohinoorTelugu.ttc",
    "kn": SYS + "NotoSansKannada.ttc", "ta": SUP + "Tamil Sangam MN.ttc",
}
LATIN_FONT = SUP + "Arial Unicode.ttf"
NATIVE_DIGIT_ZERO = {"hi": 0x0966, "mr": 0x0966, "bn": 0x09E6, "gu": 0x0AE6}
DEGRADATIONS = ["clean", "scan", "photo", "lowres"]


class MixedFont:

    def __init__(self, path, size):
        local = Path(__file__).parent / "fonts" / Path(path).name
        path = str(local) if local.exists() else path
        self.main = ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)
        self.fb = ImageFont.truetype(LATIN_FONT, size, layout_engine=ImageFont.Layout.RAQM)
        tt = TTCollection(path).fonts[0] if path.endswith(".ttc") else TTFont(path)
        self.cmap = set(tt.getBestCmap())
        self.size = size

    def runs(self, text):
        out, cur, cur_main = [], "", None
        for ch in text:
            is_main = ord(ch) in self.cmap or ch.isspace()
            if cur and is_main != cur_main:
                out.append((cur, cur_main))
                cur = ""
            cur, cur_main = cur + ch, is_main
        if cur:
            out.append((cur, cur_main))
        return out

    def length(self, draw, text):
        return sum(draw.textlength(t, font=self.main if m else self.fb) for t, m in self.runs(text))

    def draw(self, draw, xy, text, fill=(20, 20, 30)):
        x, y = xy
        for t, m in self.runs(text):
            f = self.main if m else self.fb
            draw.text((x, y), t, font=f, fill=fill)
            x += draw.textlength(t, font=f)


def native_digits(s, lang):
    z = NATIVE_DIGIT_ZERO[lang]
    return "".join(chr(z + int(c)) if c.isdigit() else c for c in s)


def inr(n):
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    return ",".join([head] + parts + [tail]) if head else ",".join(parts + [tail])


def rdate(rng, start, end):
    d = start + timedelta(days=rng.randint(0, (end - start).days))
    return d.strftime("%d/%m/%Y")


def make_values(rng, doc_type, lang):
    person = rng.choice(NAMES[lang])
    dist = rng.choice(DISTRICTS[lang])
    dept = rng.choice(DEPARTMENTS[lang])
    v = {}
    if doc_type == "application_form":
        v["name"] = (person[0], [person[0], person[1]])
        v["father_name"] = (person[2], [person[2], person[3]])
        d = rdate(rng, date(1975, 1, 1), date(2006, 12, 31))
        v["date_of_birth"] = (d, [d])
        mob = str(rng.choice([6, 7, 8, 9])) + "".join(str(rng.randint(0, 9)) for _ in range(9))
        v["mobile"] = (mob, [mob])
        v["district"] = (dist[0], [dist[0], dist[1]])
        pin = str(rng.randint(110001, 799999))
        v["pin_code"] = (pin, [pin])
        an = f"{rng.choice(['APP', 'SCH', 'REG'])}/2025/{rng.randint(10000, 99999)}"
        v["application_number"] = (an, [an])
    elif doc_type == "public_notice":
        nn = f"{rng.choice(['EDU', 'SW', 'RD'])}/{rng.randint(100, 999)}/2025"
        v["notice_number"] = (nn, [nn])
        d = rdate(rng, date(2025, 1, 1), date(2025, 6, 30))
        v["date"] = (d, [d])
        v["department"] = (dept[0], [dept[0], dept[1]])
        ld = rdate(rng, date(2025, 7, 1), date(2025, 12, 31))
        v["last_date"] = (ld, [ld])
        fee = rng.choice([100, 200, 250, 500, 1000])
        v["fee"] = (f"₹ {inr(fee)}", [str(fee)])
    elif doc_type == "income_certificate":
        cn = f"IC/{rng.randint(2023, 2025)}/{rng.randint(100000, 999999)}"
        v["certificate_number"] = (cn, [cn])
        v["name"] = (person[0], [person[0], person[1]])
        v["father_name"] = (person[2], [person[2], person[3]])
        inc = rng.randint(48, 480) * 1000
        v["annual_income"] = (f"₹ {inr(inc)}", [str(inc)])
        v["district"] = (dist[0], [dist[0], dist[1]])
        d = rdate(rng, date(2024, 1, 1), date(2025, 10, 31))
        v["issue_date"] = (d, [d])
    else:
        cn = "".join(str(rng.randint(0, 9)) for _ in range(12))
        v["consumer_number"] = (cn, [cn])
        v["name"] = (person[0], [person[0], person[1]])
        units = rng.randint(40, 650)
        v["units_consumed"] = (str(units), [str(units)])
        amt = int(units * rng.choice([5.5, 6.25, 7.1]) + rng.choice([50, 75, 120]))
        v["bill_amount"] = (f"₹ {inr(amt)}.00", [str(amt)])
        d = rdate(rng, date(2025, 1, 1), date(2025, 12, 31))
        v["due_date"] = (d, [d])
    return v, dept


def render(doc_type, lang, values, dept, layout, use_native_digits, rng):
    img = Image.new("RGB", (W, H), (255, 255, 252))
    d = ImageDraw.Draw(img)
    fp = FONTS[lang]
    f_head, f_title, f_body = MixedFont(fp, 40), MixedFont(fp, 52), MixedFont(fp, 34)
    shown = {k: (native_digits(v[0], lang) if use_native_digits and k not in ("name", "father_name",
             "district", "department") else v[0]) for k, v in values.items()}
    d.rectangle([40, 40, W - 40, H - 40], outline=(60, 60, 60), width=3)
    head = dept[0]
    f_head.draw(d, ((W - f_head.length(d, head)) / 2, 90), head)
    title = TITLES[doc_type][lang]
    f_title.draw(d, ((W - f_title.length(d, title)) / 2, 170), title)
    d.line([100, 260, W - 100, 260], fill=(80, 80, 80), width=2)
    y = 320
    fields = [k for k in values if not (doc_type == "public_notice" and k == "department")]

    if doc_type == "public_notice":
        f_body.draw(d, (110, y), f"{LABELS['notice_number'][lang]}: {shown['notice_number']}")
        right = f"{LABELS['date'][lang]}: {shown['date']}"
        f_body.draw(d, (W - 110 - f_body.length(d, right), y), right)
        y += 110
        body = NOTICE_BODY[lang].format(dept=dept[0])
        line = ""
        for word in body.split():
            if f_body.length(d, line + " " + word) > W - 240:
                f_body.draw(d, (110, y), line.strip())
                y += 62
                line = ""
            line += " " + word
        f_body.draw(d, (110, y), line.strip())
        y += 120
        fields = ["last_date", "fee"]

    if layout == "table":
        x0, x1, x2 = 100, 540, W - 100
        row_h = 86
        for k in fields:
            d.rectangle([x0, y, x2, y + row_h], outline=(90, 90, 90), width=2)
            d.line([x1, y, x1, y + row_h], fill=(90, 90, 90), width=2)
            f_body.draw(d, (x0 + 24, y + 18), LABELS[k][lang])
            f_body.draw(d, (x1 + 24, y + 18), shown[k])
            y += row_h
    else:
        for k in fields:
            f_body.draw(d, (110, y), f"{LABELS[k][lang]} : {shown[k]}")
            y += 78
    sig = SIGNATURE[lang]
    f_body.draw(d, (W - 140 - f_body.length(d, sig), min(H - 160, y + 180)), sig)
    return img


def degrade(img, kind, rng):
    if kind == "clean":
        return img
    nrng = np.random.default_rng(rng.randint(0, 10**6))
    if kind == "scan":
        img = img.rotate(rng.uniform(-1.5, 1.5), expand=False, fillcolor=(250, 250, 245),
                         resample=Image.BICUBIC)
        a = np.asarray(img).astype(np.float32)
        a += nrng.normal(0, 12, a.shape)
        img = Image.fromarray(a.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
    elif kind == "photo":
        img = img.rotate(rng.uniform(-3.5, 3.5), expand=True, fillcolor=(120, 110, 100),
                         resample=Image.BICUBIC)
        a = np.asarray(img).astype(np.float32)
        h, w = a.shape[:2]
        grad = np.linspace(0.65, 1.0, w)[None, :, None] * np.linspace(0.85, 1.0, h)[:, None, None]
        a = a * grad + nrng.normal(0, 6, a.shape)
        img = Image.fromarray(a.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.1))
        img = img.resize((int(img.width * 0.75), int(img.height * 0.75)), Image.BILINEAR)
    elif kind == "lowres":
        small = img.resize((W // 2 - 60, H // 2 - 80), Image.BILINEAR)
        img = small.filter(ImageFilter.GaussianBlur(0.5))
    return img


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    out = Path(a.out)
    rng = random.Random(a.seed)
    out.mkdir(parents=True, exist_ok=True)
    doc_types = list(TITLES)
    manifest = []
    i = 0
    for lang in LANGS:
        for j in range(6):
            doc_type = doc_types[j % 4]
            layout = "table" if ((i + a.seed - SEED) % 3 == 1) else "colon"
            native = lang in NATIVE_DIGIT_ZERO and rng.random() < 0.35
            deg = DEGRADATIONS[(i + a.seed - SEED) % 4]
            values, dept = make_values(rng, doc_type, lang)
            if doc_type == "public_notice":
                values["department"] = (dept[0], [dept[0], dept[1]])
            img = degrade(render(doc_type, lang, values, dept, layout, native, rng), deg, rng)
            doc_id = f"{i:02d}_{lang}_{doc_type}"
            img.save(out / f"{doc_id}.png")

            qs = []
            pool = list(EN_Q[doc_type].items())
            rng.shuffle(pool)
            for fname, variants in pool[:3]:
                qs.append({"q": rng.choice(variants), "field": fname, "lang": "en",
                           "gold": values[fname][1]})
            nf, nq = NATIVE_Q[doc_type]
            qs.append({"q": nq[lang], "field": nf, "lang": lang, "gold": values[nf][1]})
            manifest.append({
                "id": doc_id, "image": f"{doc_id}.png", "lang": lang, "doc_type": doc_type,
                "layout": layout, "native_digits": native, "degradation": deg,
                "fields": {k: v[1] for k, v in values.items()}, "questions": qs,
            })
            i += 1
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    nf = sum(len(m["fields"]) for m in manifest)
    nq = sum(len(m["questions"]) for m in manifest)
    print(f"wrote {len(manifest)} documents, {nf} gold fields, {nq} QA pairs -> {out}")


if __name__ == "__main__":
    main()
