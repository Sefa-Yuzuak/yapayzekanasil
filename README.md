# yapayzekanasil.com

Yapay zekâ araçlarını Türkiye'deki kullanıcı için adım adım anlatan statik rehber sitesi.

**İlke:** her olgu şirketin kendi sayfasına bağlı ve kaynağın son kontrol tarihi yazılı;
her rehber yaygın bir yanlışı düzeltir; puan/sıralama yok; kaynağı olmayan sayı yazılmaz.

```
python build/derle.py      # dist/ üretir (rehber yokken noindex)
python build/denetle.py    # yayın öncesi denetim; çıkış 1 ise deploy etme
python build/og_gorsel.py  # static/og.jpg (paylaşım görseli)
```

Yayın: GitHub `main` → Actions → Coolify deploy API (`force=true`) → Docker (python:3.12-slim derler,
nginx:alpine yayımlar). Alan adı Coolify'da `domains` ile tanımlı; nginx `absolute_redirect off`,
www→apex 301, güvenlik başlıkları her `location`'da tekrar.
