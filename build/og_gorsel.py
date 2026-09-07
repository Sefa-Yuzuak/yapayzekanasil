# -*- coding: utf-8 -*-
"""Varsayılan paylaşım görselini üretir: static/og.jpg (1200x630).

Sayfa başına görsel üretmek bu iş için fazla karmaşık; tek markalı görsel
WhatsApp/X/Facebook kartlarını boş bırakmaz. Sayılar veriden gelir.
Kullanım: python build/og_gorsel.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")
KOK = Path(__file__).resolve().parent.parent
HEDEF = KOK / "static" / "og.jpg"
BOYUT = (1200, 630)
MOR, VURGU, ACIK, SARI = (43, 31, 102), (124, 92, 255), (239, 234, 254), (245, 185, 66)
YAZI = Path(r"C:\Windows\Fonts")


def font(ad: str, boy: int) -> ImageFont.FreeTypeFont:
    for aday in (ad, "segoeuib.ttf", "arialbd.ttf"):
        if (YAZI / aday).exists():
            return ImageFont.truetype(str(YAZI / aday), boy)
    return ImageFont.load_default()


def main() -> int:
    site = json.loads((KOK / "data" / "site.json").read_text(encoding="utf-8"))
    rehberler = json.loads((KOK / "data" / "rehberler.json").read_text(encoding="utf-8"))
    im = Image.new("RGB", BOYUT, MOR)
    d = ImageDraw.Draw(im)
    for y in range(BOYUT[1]):
        t = y / BOYUT[1]
        d.line([(0, y), (BOYUT[0], y)],
               fill=tuple(round(a + (b - a) * t * 0.45) for a, b in zip(MOR, VURGU)))
    d.rectangle([0, BOYUT[1] - 14, BOYUT[0], BOYUT[1]], fill=SARI)
    d.text((80, 150), site["ad"], font=font("segoeuib.ttf", 92), fill="white")
    d.text((80, 268), "Yapay zekâ araçları adım adım, resmî kaynağıyla",
           font=font("seguisb.ttf", 42), fill=ACIK)
    alt = (f"{len(rehberler)} rehber   ·   ücretsiz sınırlar, fiyatlar, Türkçe desteği"
           if rehberler else "Ücretsiz sınırlar · fiyatlar · Türkçe desteği · adım adım")
    d.text((80, 356), alt, font=font("seguisb.ttf", 34), fill=ACIK)
    d.text((80, 468), "Her bilgi şirketin kendi sayfasından · kontrol tarihiyle",
           font=font("seguisb.ttf", 30), fill=(205, 195, 245))
    im.save(HEDEF, "JPEG", quality=86, optimize=True)
    print(f"✓ {HEDEF.relative_to(KOK)} ({HEDEF.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
