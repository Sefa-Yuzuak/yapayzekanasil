# -*- coding: utf-8 -*-
"""yapayzekanasil.com — statik site üreteci.

Girdi : data/site.json, data/alanlar.json, data/rehberler.json, data/sayfalar.json
Çıktı : dist/

Sitenin ayrışma noktası — Türkçe yapay zekâ içeriğinin çoğunda olmayan üç şey:
  1. Her olgu şirketin KENDİ sayfasına bağlı ve o kaynağın son kontrol tarihi yazılı
  2. Her rehber yaygın bir yanlışı düzeltir (kaynağıyla)
  3. Puan/sıralama yok; yalnız ölçülebilir bilgi (ücretsiz sınır, fiyat, Türkçe, veri)

Rehber kaydı (rehberler.json):
  slug, alan, baslik, ozet, cevap (kısa cevap), hedef_sorgu, guncelleme (YYYY-MM-DD),
  yanlis {iddia, dogru, kaynak}      · sayfada "Yaygın yanlış / Doğrusu" kutusu
  bolumler [ {tur: baslik|altbaslik|metin|madde|adim|uyari|tablo, ...} ]
  sss [ {s, c} ]                     · boşsa FAQPage yayımlanmaz
  kaynaklar [ {ad, url, dogrulama} ] · dogrulama: kaynağın son kontrol tarihi

İlke: kaynağı olmayan sayı yazılmaz. Rehber yokken site noindex'tir (ince sayfa
indekslenmesin); ilk rehber girince kendiliğinden açılır.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.stdout.reconfigure(encoding="utf-8")

KOK = Path(__file__).resolve().parent.parent
DATA = KOK / "data"
DIST = KOK / "dist"
STATIC = KOK / "static"
TEMPLATES = KOK / "templates"

AYLAR = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
         "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
# Türkçe harfler önce ASCII'ye çevrilir; Python'un lower()'ı İ/I'yı bozar
# (bkz. hafıza: turkce-metin-tuzaklari), o yüzden lower() en sonda ve ASCII üstünde.
TR_ASCII = str.maketrans("çğıöşüâîûÇĞİÖŞÜÂÎÛI", "cgiosuaiucgiosuaiui")

AI_TARAYICILAR = ("GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-SearchBot",
                  "PerplexityBot", "Google-Extended", "Applebot-Extended", "CCBot")

# Bu sayıya ulaşana kadar site noindex kalır (rehber + görev toplamı).
EN_AZ_SAYFA = 8


def slugify(metin: str) -> str:
    metin = unicodedata.normalize("NFKD", (metin or "").translate(TR_ASCII))
    metin = metin.encode("ascii", "ignore").decode().lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", metin)).strip("-")


def tarih_yaz(iso: str) -> str:
    try:
        g = date.fromisoformat(iso)
        return f"{g.day} {AYLAR[g.month]} {g.year}"
    except (TypeError, ValueError):
        return iso or ""


def kisalt(metin: str, en: int = 158) -> str:
    """Meta açıklamayı kırpar; mümkünse CÜMLE sonunda biter, yoksa kelime sonunda."""
    metin = " ".join((metin or "").split())
    if len(metin) <= en:
        return metin
    kesik = metin[:en]
    nokta = max(kesik.rfind(". "), kesik.rfind("! "), kesik.rfind("? "))
    if nokta > en * 0.55:
        return kesik[:nokta + 1]
    bosluk = kesik.rfind(" ")
    return (kesik[:bosluk] if bosluk > en * 0.6 else kesik).rstrip(" ,.;:") + "…"


def duz_metin(r: dict) -> str:
    parcalar = [r.get("ozet", ""), r.get("cevap", "")]
    y = r.get("yanlis") or {}
    parcalar += [y.get("iddia", ""), y.get("dogru", "")]
    for b in r.get("bolumler", []):
        parcalar.append(b.get("metin", ""))
        parcalar += b.get("maddeler", [])
        for a in b.get("adimlar", []):
            parcalar += [a.get("baslik", ""), a.get("metin", "")]
        for satir in b.get("satirlar", []):
            parcalar += [str(h) for h in satir]
    for s in r.get("sss", []):
        parcalar += [s.get("s", ""), s.get("c", "")]
    for a in r.get("araclar", []):
        parcalar += [a.get(k, "") for k in ("ad", "ucretsiz", "turkce", "filigran", "ticari", "not")]
    return " ".join(p for p in parcalar if p)


def yukle(ad: str, varsayilan=None):
    yol = DATA / ad
    if not yol.exists():
        if varsayilan is None:
            sys.exit(f"Eksik veri dosyası: {yol}")
        return varsayilan
    return json.loads(yol.read_text(encoding="utf-8"))


def yaz(yol: str, icerik: str) -> None:
    hedef = DIST / yol.strip("/") / "index.html" if yol != "/" else DIST / "index.html"
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_text(icerik, encoding="utf-8")


# ---------------------------------------------------------------- schema.org
def kirintilar(site: dict, *adimlar: tuple[str, str]) -> dict:
    ogeler = [{"@type": "ListItem", "position": 1, "name": "Ana sayfa", "item": site["url"] + "/"}]
    for i, (ad, yol) in enumerate(adimlar, 2):
        ogeler.append({"@type": "ListItem", "position": i, "name": ad, "item": site["url"] + yol})
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": ogeler}


def sss_schema(sorular: list[dict]) -> dict | None:
    """Boş FAQPage yayımlanmaz: Google en az bir Question ister."""
    if not sorular:
        return None
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": s["s"],
                            "acceptedAnswer": {"@type": "Answer", "text": s["c"]}}
                           for s in sorular]}


def makale_schema(site: dict, r: dict, alan: dict) -> dict:
    s = {"@context": "https://schema.org", "@type": "Article", "headline": r["baslik"],
         "description": r["ozet"], "inLanguage": "tr-TR", "url": site["url"] + r["yol"],
         "mainEntityOfPage": site["url"] + r["yol"], "wordCount": r["kelime"],
         "articleSection": alan.get("ad", ""),
         "publisher": {"@type": "Organization", "name": site["ad"], "url": site["url"] + "/"}}
    if r.get("guncelleme"):
        s["dateModified"] = r["guncelleme"]
    if r.get("kaynaklar"):
        s["citation"] = [{"@type": "CreativeWork", "name": k["ad"], "url": k["url"]}
                         for k in r["kaynaklar"]]
    return s


def liste_schema(site: dict, ad: str, yol: str, rehberler: list[dict]) -> dict:
    return {"@context": "https://schema.org", "@type": "ItemList", "name": ad,
            "url": site["url"] + yol, "numberOfItems": len(rehberler),
            "itemListElement": [{"@type": "ListItem", "position": i, "name": r["baslik"],
                                 "url": site["url"] + r["yol"]} for i, r in enumerate(rehberler, 1)]}


# ---------------------------------------------------------------- ana akış
def main() -> int:
    site = yukle("site.json")
    alanlar = yukle("alanlar.json", [])
    rehberler = yukle("rehberler.json", [])
    gorevler = yukle("gorevler.json", [])
    sayfalar = yukle("sayfalar.json", [])
    alan_dizin = {a["slug"]: a for a in alanlar}

    # Görev sayfaları sitenin omurgası: her biri bir "yapay zeka ile X nasıl
    # yapılır" sorgusuna karşılık gelir. Ayrışma noktası `araclar` tablosu —
    # ücretsiz katmanda gerçekte ne kadar iş yapılabildiği, Türkçe desteği,
    # çıktıda filigran olup olmadığı ve ticari kullanım izni. Rakiplerin hiçbiri
    # bu dört sütunu kaynaklı ve tarihli vermiyor.
    for g in gorevler:
        g["yol"] = f"/nasil/{g['slug']}/"
        g["kelime"] = len(duz_metin(g).split())
        g["okuma"] = max(1, round(g["kelime"] / 200))
        g["icindekiler"] = []
        for b in g.get("bolumler", []):
            if b.get("tur") == "baslik":
                b["id"] = slugify(b["metin"])
                g["icindekiler"].append({"ad": b["metin"], "id": b["id"]})
        # Tabloda kaynağı olmayan araç satırı yayımlanmaz: doğrulanmamış bir
        # "ücretsiz" iddiası, sitenin tüm güvenilirliğini götürür.
        kaynaksiz = [a["ad"] for a in g.get("araclar", []) if not a.get("kaynak")]
        if kaynaksiz:
            sys.exit(f"HATA: {g['slug']} görevinde kaynaksız araç satırı: {kaynaksiz}")
    for g in gorevler:
        # Sabit ilk üçü vermek, listenin başındaki görevlere bütün iç bağlantıyı
        # yığıp sonrakileri öksüz bırakıyordu. Önce aynı konudan, sonra sırayı
        # kendi konumundan başlatarak dolaş: her görev hem bağlantı alıyor hem veriyor.
        i = gorevler.index(g)
        sira = gorevler[i + 1:] + gorevler[:i]          # kendisi hariç, kendinden sonra başla
        ayni = [x for x in sira if x.get("alan") == g.get("alan")]
        diger = [x for x in sira if x.get("alan") != g.get("alan")]
        # Üç yuvanın en fazla ikisi aynı konudan: hepsini aynı konuya verirsek
        # kalabalık konular kendi içine kapanıyor ve tek görevli bir konu
        # (ör. ogrenci-ve-ogretmen) hiç bağlantı almıyor.
        g["ilgili"] = (ayni[:2] + diger)[:3]

    for r in rehberler:
        r.setdefault("slug", slugify(r["baslik"]))
        r["yol"] = f"/rehber/{r['slug']}/"
        r["kelime"] = len(duz_metin(r).split())
        r["okuma"] = max(1, round(r["kelime"] / 200))
        r["alan_ad"] = alan_dizin.get(r.get("alan"), {}).get("ad", "")
        r["icindekiler"] = []
        for b in r.get("bolumler", []):
            if b.get("tur") == "baslik":
                b["id"] = slugify(b["metin"])
                r["icindekiler"].append({"ad": b["metin"], "id": b["id"]})
    for a in alanlar:
        a["yol"] = f"/{a['slug']}/"
        a["rehberler"] = [r for r in rehberler if r.get("alan") == a["slug"]]
        # Görevler de bir konuya bağlı: konu merkezi ikisini birden toplamazsa
        # /nasil/ kümesi sitenin geri kalanından kopuk kalıyor.
        a["gorevler"] = [g for g in gorevler if g.get("alan") == a["slug"]]
        # Şablonlar bir konuya bağlantı vermeden önce buna bakar: sayfası
        # üretilmeyen konuya menüden bağlantı verilirse kırık bağlantı olur.
        a["dolu"] = bool(a["gorevler"] or a["rehberler"])
    for r in rehberler:
        ayni = [x for x in rehberler if x.get("alan") == r.get("alan") and x is not r]
        diger = [x for x in rehberler if x.get("alan") != r.get("alan")]
        r["ilgili"] = (ayni + diger)[:3]

    bugun = date.today().isoformat()
    site["derleme_zamani"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    site["yil"] = bugun[:4]
    site["guncelleme"] = max([x.get("guncelleme") or "" for x in rehberler + gorevler] + [bugun])
    site["guncelleme_tr"] = tarih_yaz(site["guncelleme"])
    # Yeterli içerik birikene kadar arama motorlarına kapalı. Tek sayfayla
    # indekslenmek, siteyi "ince içerik" olarak damgalatır ve AdSense onayını da
    # riske atar; eşiği geçince kendiliğinden açılır.
    site["noindex"] = len(rehberler) + len(gorevler) < EN_AZ_SAYFA
    # Ana sayfa sayacı yalnız rehberleri sayıyordu: 17 görev varken site
    # kendini "3 rehber" diye tanıtıyordu. Asıl ölçü kaynaklı araç satırı.
    site["arac_sayisi"] = sum(len(g.get("araclar", [])) for g in gorevler)

    env = Environment(loader=FileSystemLoader(TEMPLATES),
                      autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
    env.filters["tarih"] = tarih_yaz
    env.filters["json"] = lambda v: json.dumps(v, ensure_ascii=False)

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    shutil.copytree(STATIC, DIST / "static")
    if (STATIC / "favicon.svg").exists():
        shutil.copy(STATIC / "favicon.svg", DIST / "favicon.svg")

    # CSS içerik damgasıyla adlandırılır; nginx bunu bir yıl immutable veriyor.
    # Sabit adla yayımlansaydı stil değişikliği geri gelen ziyaretçiye bir yıl ulaşmazdı.
    css = DIST / "static" / "s.css"
    ozet = hashlib.sha256(css.read_bytes()).hexdigest()[:8]
    css = css.rename(DIST / "static" / f"s.{ozet}.css")
    ortak = {"site": site, "alanlar": alanlar, "rehberler": rehberler, "gorevler": gorevler,
             "css_url": f"/static/{css.name}"}
    yollar: list[tuple[str, str, str | None]] = []

    def tam_baslik(b: str) -> str:
        ekli = f"{b} | {site['ad']}"
        return ekli if len(ekli) <= 60 else b

    def sayfa(yol, sablon, baslik, aciklama, schema, oncelik="0.6", lastmod=None, **kw):
        yaz(yol, env.get_template(sablon).render(
            baslik=baslik, tam_baslik=tam_baslik(baslik), meta_desc=kisalt(aciklama),
            canonical=yol, schema=[x for x in schema if x], **ortak, **kw))
        yollar.append((yol, oncelik, lastmod))

    sayfa("/", "home.html", f"Yapay Zekâ Nasıl Kullanılır? Adım Adım Türkçe Rehber ({site['yil']})",
          site["aciklama"],
          [{"@context": "https://schema.org", "@type": "WebSite", "name": site["ad"],
            "url": site["url"] + "/", "inLanguage": "tr-TR"},
           {"@context": "https://schema.org", "@type": "Organization", "name": site["ad"],
            "url": site["url"] + "/", "email": site["eposta"]}],
          oncelik="1.0", one_cikan=rehberler[:9])

    if gorevler:
        sayfa("/nasil/", "gorevler.html", f"Yapay Zeka ile Ne Yapılır? {len(gorevler)} Konu",
              f"Yapay zekâyla video, sunum, çeviri ve daha fazlası nasıl yapılır: "
              f"{len(gorevler)} görev, her birinde hangi aracın ücretsiz katmanında "
              f"gerçekte ne kadar iş yapılabildiği kaynağıyla yazılı.",
              [liste_schema(site, "Yapay zekâ ile nasıl yapılır", "/nasil/", gorevler),
               kirintilar(site, ("Nasıl yapılır", "/nasil/"))],
              oncelik="0.9", kirinti=[("Nasıl yapılır", "/nasil/")])

    for g in gorevler:
        sayfa(g["yol"], "gorev.html", g["baslik"], g["ozet"],
              [makale_schema(site, g, {"ad": "Nasıl yapılır"}),
               sss_schema(g.get("sss", [])),
               kirintilar(site, ("Nasıl yapılır", "/nasil/"), (g["baslik"], g["yol"]))],
              oncelik="0.9", lastmod=g.get("guncelleme"), g=g,
              kirinti=[("Nasıl yapılır", "/nasil/"), (g["baslik"], g["yol"])])

    if rehberler:
        sayfa("/rehberler/", "rehberler.html", f"Tüm Rehberler ({len(rehberler)})",
              f"{site['ad']} sitesindeki {len(rehberler)} rehberin tam listesi; konuya göre.",
              [liste_schema(site, "Tüm rehberler", "/rehberler/", rehberler),
               kirintilar(site, ("Rehberler", "/rehberler/"))],
              oncelik="0.9", kirinti=[("Rehberler", "/rehberler/")])

    for a in alanlar:
        if not a["dolu"]:
            continue     # boş hub = ince sayfa
        icerik = a["gorevler"] + a["rehberler"]
        sayfa(a["yol"], "alan.html", f"{a['ad']}: {len(icerik)} Sayfa", a["aciklama"],
              [liste_schema(site, a["ad"], a["yol"], icerik),
               kirintilar(site, (a["ad"], a["yol"]))],
              oncelik="0.8", alan=a, kirinti=[(a["ad"], a["yol"])])

    for r in rehberler:
        alan = alan_dizin.get(r.get("alan"), {})
        kir = [(alan["ad"], alan["yol"])] if alan else []
        sayfa(r["yol"], "rehber.html", r["baslik"], r["ozet"],
              [makale_schema(site, r, alan), sss_schema(r.get("sss", [])),
               kirintilar(site, *kir, (r["baslik"], r["yol"]))],
              oncelik="0.8", lastmod=r.get("guncelleme"), r=r, alan=alan,
              kirinti=kir + [(r["baslik"], r["yol"])])

    for p in sayfalar:
        sayfa(p["url"], "sayfa.html", p["baslik"], p["meta"],
              [kirintilar(site, (p["baslik"], p["url"]))], oncelik="0.4", p=p,
              kirinti=[(p["baslik"], p["url"])])

    (DIST / "404.html").write_text(env.get_template("404.html").render(
        baslik="Sayfa bulunamadı", tam_baslik=f"Sayfa bulunamadı | {site['ad']}",
        meta_desc="Aradığınız sayfa yok ya da taşındı.", canonical="/404.html", schema=[], **ortak),
        encoding="utf-8")

    # ---------------------------------------------------------------- sitemap / robots / llms
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for yol, onc, lastmod in yollar:
        sm.append(f"  <url><loc>{site['url']}{yol}</loc>"
                  f"<lastmod>{lastmod or site['guncelleme']}</lastmod>"
                  f"<priority>{onc}</priority></url>")
    sm.append("</urlset>")
    (DIST / "sitemap.xml").write_text("\n".join(sm), encoding="utf-8")

    if site["noindex"]:
        robots = "User-agent: *\nDisallow: /\n"
    else:
        robots = "User-agent: *\nAllow: /\n\n# Yapay zekâ tarayıcıları (GEO): alıntılanmaya açık\n"
        robots += "".join(f"User-agent: {b}\nAllow: /\n" for b in AI_TARAYICILAR)
    (DIST / "robots.txt").write_text(robots + f"\nSitemap: {site['url']}/sitemap.xml\n",
                                     encoding="utf-8")

    if site.get("adsense"):
        (DIST / "ads.txt").write_text(
            f"google.com, {site['adsense'].removeprefix('ca-')}, DIRECT, f08c47fec0942fa0\n",
            encoding="utf-8")

    llms = [f"# {site['ad']}", "", f"> {site['aciklama']}", "",
            f"Her olgu şirketin kendi sayfasından; son kontrol tarihi sayfada yazılı. "
            f"Son güncelleme: {site['guncelleme']}. Araçlara puan verilmez.", ""]
    if gorevler:
        llms += ["## Nasıl yapılır",
                 "Her sayfa bir görevi anlatır ve araçların ücretsiz katmanında gerçekte ne "
                 "kadar iş yapılabildiğini kaynağıyla verir."]
        llms += [f"- [{g['baslik']}]({site['url']}{g['yol']}): {g['ozet']}" for g in gorevler]
        llms.append("")
    for a in alanlar:
        if not a["rehberler"]:
            continue
        llms += [f"## {a['ad']}", a["aciklama"]]
        llms += [f"- [{r['baslik']}]({site['url']}{r['yol']}): {r['ozet']}" for r in a["rehberler"]]
        llms.append("")
    (DIST / "llms.txt").write_text("\n".join(llms), encoding="utf-8")

    (DIST / "veri").mkdir(exist_ok=True)
    disari = ("slug", "alan", "baslik", "ozet", "cevap", "hedef_sorgu", "guncelleme", "yanlis",
              "kaynaklar", "yol")
    (DIST / "veri" / "rehberler.json").write_text(json.dumps(
        [{k: r.get(k) for k in disari} for r in rehberler], ensure_ascii=False), encoding="utf-8")
    # Araç karşılaştırma tablosu açık veri olarak da yayımlanıyor: sitenin en
    # değerli katmanı bu ve kimse tarihli haliyle yayımlamıyor.
    (DIST / "veri" / "araclar.json").write_text(json.dumps(
        [{"gorev": g["slug"], "gorev_url": site["url"] + g["yol"], **a}
         for g in gorevler for a in g.get("araclar", [])],
        ensure_ascii=False, indent=1), encoding="utf-8")

    kelime = sum(x["kelime"] for x in rehberler + gorevler)
    arac = sum(len(g.get("araclar", [])) for g in gorevler)
    print(f"✓ {len(yollar)} sayfa | {len(alanlar)} alan | {len(rehberler)} rehber | "
          f"{len(gorevler)} görev ({arac} doğrulanmış araç satırı) | {kelime} kelime -> {DIST}")
    print(f"  arama motoruna kapalı (noindex): {site['noindex']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
