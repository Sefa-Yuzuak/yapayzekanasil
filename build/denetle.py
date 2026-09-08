# -*- coding: utf-8 -*-
"""dist/ çıktısını yayına vermeden önce denetler.

Kontroller: çift/uzun başlık, meta açıklama, tek robots ve canonical etiketi,
tek h1, bozuk JSON-LD, kırık iç bağlantı, yetim sayfa, sitemap tutarlılığı,
ince sayfa, kaynaksız sayı (rehberde rakam var ama kaynak listesi boş),
mobilde yatay taşmaya yol açan kırılamayan uzun dizi.
Hedef: 0 sorun. Çıkış kodu 1 ise deploy etme.
"""
from __future__ import annotations

import html
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

KOK = Path(__file__).resolve().parent.parent
DIST = KOK / "dist"
BASLIK_EN = 62
DESC_EN = 160
EN_AZ_METIN = 900
# 375px ekranda 16px yazıyla ~44 karakter bir satıra sığıyor; 54 karakterlik bir
# URL sayfayı 401px'e itmişti. CSS artık kırıyor, bu kural kaynağı yakalar.
EN_UZUN_SOZCUK = 45


def metin(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", h)
    return " ".join(re.sub(r"(?s)<[^>]+>", " ", h).split())


def main() -> int:
    if not DIST.exists():
        sys.exit("dist/ yok — önce build/derle.py çalıştırın.")
    sayfalar = sorted(DIST.rglob("*.html"))
    site = json.loads((KOK / "data" / "site.json").read_text(encoding="utf-8"))
    kok = site["url"].rstrip("/")
    # noindex kuralı BURADA yeniden hesaplanmaz: derle.py'nin eşiği değiştiğinde
    # iki yer sessizce ayrışıyordu. Tek doğruluk kaynağı üretilen robots.txt.
    noindex = "Disallow: /" in (DIST / "robots.txt").read_text(encoding="utf-8")

    sorunlar: list[str] = []
    basliklar: dict[str, list[str]] = defaultdict(list)
    descler: dict[str, list[str]] = defaultdict(list)
    ic_baglar: dict[str, set[str]] = defaultdict(set)

    def yol(p: Path) -> str:
        r = p.relative_to(DIST).as_posix()
        return "/" if r == "index.html" else "/" + r.removesuffix("index.html")

    for p in sayfalar:
        h = p.read_text(encoding="utf-8")
        u = yol(p)
        dis_404 = p.name == "404.html"

        t = re.search(r"<title>(.*?)</title>", h, re.S)
        if not t:
            sorunlar.append(f"{u}: <title> yok")
        else:
            b = html.unescape(t.group(1).strip())
            if not dis_404:
                basliklar[b].append(u)
            if len(b) > BASLIK_EN:
                sorunlar.append(f"{u}: başlık {len(b)} karakter (>{BASLIK_EN}) — {b[:70]}")

        d = re.search(r'<meta name="description" content="(.*?)">', h, re.S)
        if not d or not d.group(1).strip():
            sorunlar.append(f"{u}: meta description yok")
        else:
            dd = html.unescape(d.group(1))
            if not dis_404:
                descler[dd].append(u)
            if len(dd) > DESC_EN:
                sorunlar.append(f"{u}: description {len(dd)} karakter (>{DESC_EN})")

        n = len(re.findall(r'<meta name="robots"', h))
        if n != 1:
            sorunlar.append(f"{u}: robots etiketi {n} adet (1 olmalı)")
        if (dis_404 or noindex) and "noindex" not in h:
            sorunlar.append(f"{u}: noindex bekleniyordu")
        if not dis_404 and not noindex and "noindex" in h:
            sorunlar.append(f"{u}: içerik varken noindex")

        c = re.findall(r'<link rel="canonical" href="(.*?)"', h)
        if len(c) != 1:
            sorunlar.append(f"{u}: canonical {len(c)} adet")
        elif not dis_404 and c[0] != f"{kok}{u}":
            sorunlar.append(f"{u}: canonical uyuşmuyor -> {c[0]}")

        h1 = re.findall(r"(?s)<h1[^>]*>(.*?)</h1>", h)
        if len(h1) != 1:
            sorunlar.append(f"{u}: h1 sayısı {len(h1)}")

        for blok in re.findall(r'(?s)<script type="application/ld\+json">(.*?)</script>', h):
            try:
                json.loads(blok)
            except json.JSONDecodeError as e:
                sorunlar.append(f"{u}: bozuk JSON-LD ({e})")

        # İnce sayfa uyarısı yalnız yayına açık siteler için anlamlı: noindex
        # modunda hub'lar zaten az içerikle duruyor, uyarı gürültü oluyor.
        g = metin(h)
        if not dis_404 and not noindex and len(g) < EN_AZ_METIN:
            sorunlar.append(f"{u}: gövde metni {len(g)} karakter (ince sayfa şüphesi)")

        # Kırılamayan uzun dizi (çoğunlukla düz metin yazılmış URL) mobilde
        # sayfayı görüntü alanının dışına itiyor. CSS bunu artık kırıyor, ama
        # kaynağı düzeltmek daha iyi: uzun URL'yi bağlantı metnine sarın.
        for uzun in sorted({w for w in g.split() if len(w) > EN_UZUN_SOZCUK}):
            sorunlar.append(f"{u}: {len(uzun)} karakterlik kırılamayan dizi "
                            f"«{uzun[:55]}» — mobilde yatay taşma riski")

        # Rehberde yıl/fiyat/yüzde gibi rakam var ama kaynak bölümü yoksa: kaynaksız sayı.
        if u.startswith("/rehber/") and 'id="kaynaklar"' not in h and re.search(r"\d{2,}", g):
            sorunlar.append(f"{u}: rakam var ama Kaynaklar bölümü yok")

        for bag in re.findall(r'href="(/[^"#?]*)"', h):
            ic_baglar[bag].add(u)

    for b, yerler in basliklar.items():
        if len(yerler) > 1:
            sorunlar.append(f"ÇİFT BAŞLIK ({len(yerler)}): {b[:60]} -> {', '.join(yerler[:4])}")
    for d, yerler in descler.items():
        if len(yerler) > 1:
            sorunlar.append(f"ÇİFT DESCRIPTION ({len(yerler)}): {d[:55]}… -> {', '.join(yerler[:3])}")

    varlik = {yol(p) for p in sayfalar}
    for f in DIST.rglob("*"):
        if f.is_file() and f.suffix != ".html":
            varlik.add("/" + f.relative_to(DIST).as_posix())
    for bag, nereden in sorted(ic_baglar.items()):
        if bag not in varlik and bag.rstrip("/") + "/" not in varlik:
            sorunlar.append(f"KIRIK BAĞ: {bag} (örn. {sorted(nereden)[0]})")

    # Yetim sayfa: sitemap'te var ama hiçbir sayfadan bağlanmıyor.
    for u in sorted(varlik):
        if u.endswith("/") and u != "/" and not (ic_baglar.get(u, set()) - {u}):
            sorunlar.append(f"YETİM SAYFA (hiç iç bağlantı yok): {u}")

    sm = (DIST / "sitemap.xml").read_text(encoding="utf-8")
    sm_urls = re.findall(r"<loc>(.*?)</loc>", sm)
    if len(sm_urls) != len(set(sm_urls)):
        sorunlar.append(f"sitemap'te tekrar eden URL: {len(sm_urls) - len(set(sm_urls))}")
    for u in sm_urls:
        if not u.startswith(kok + "/") or u.startswith(kok + "//"):
            sorunlar.append(f"sitemap'te yanlış kök: {u}")
    eksik = {u.removeprefix(kok) for u in sm_urls} - varlik
    if eksik:
        sorunlar.append(f"sitemap'te olup dosyası olmayan: {sorted(eksik)[:5]}")

    print(f"denetlenen sayfa : {len(sayfalar)}")
    print(f"sitemap URL      : {len(sm_urls)}")
    print(f"benzersiz başlık : {len(basliklar)}")
    print(f"noindex modu     : {noindex}")
    if sorunlar:
        print(f"\n{len(sorunlar)} SORUN:")
        for s in sorunlar[:80]:
            print("  -", s)
        return 1
    print("\n✓ sorun yok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
