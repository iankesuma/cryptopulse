# Deploy ke GitHub Pages (versi statis)

**Status: SUDAH LIVE** → https://iankesuma.github.io/cryptopulse/ (branch `main`, folder `/docs`,
HTTPS aktif). Update konten = commit + push; Pages rebuild otomatis ~1 menit.


GitHub Pages hanya menyajikan file statis — tidak bisa menjalankan Python/FastAPI.
Karena itu ada versi statis di folder **`docs/`**: seluruh perhitungan indikator
dipindah ke JavaScript (`docs/engine.js`), data diambil langsung dari API publik
Binance oleh browser, dan riwayat prediksi disimpan di `localStorage`.

## Yang jalan di versi statis

- 23 instrumen (22 crypto + XAUT/USDT), 12 indikator, bobot IC, gate, horizon 15/30/60.
- Harga live: WebSocket `wss://data-stream.binance.vision` (kline 1m + depth20).
- Klines/ticker: REST `data-api.binance.vision` (CORS `*`, sudah diuji dari browser).
- Fear & Greed: `api.alternative.me` (CORS ok).
- Riwayat prediksi + hit rate: `localStorage` (per browser, bukan SQLite).

## Yang tidak ada di versi statis

- Panel **LightGBM** → `n/a` (model Python tidak ikut; di server dia info-only juga,
  AUC 0.499).
- Hit rate tidak dibagi antar-device (localStorage lokal).
- Tidak ada `/api/*`; semua dihitung di klien.

## Langkah deploy

```bash
cd "C:\Users\Evaluation Software\Projects\cryptopulse"

git init -b main
git add .
git commit -m "CryptoPulse: dashboard sinyal crypto + XAUT (engine Python + versi statis GitHub Pages)"

# buat repo kosong di GitHub dulu (mis. cryptopulse), lalu:
git remote add origin https://github.com/<username>/cryptopulse.git
git push -u origin main
```

Lalu di GitHub: **Settings → Pages → Build and deployment**
- Source: *Deploy from a branch*
- Branch: `main`, folder: **`/docs`**
- Save → tunggu 1–2 menit → buka `https://<username>.github.io/cryptopulse/`

## Tes lokal sebelum push

```bash
cd docs
python -m http.server 8100
# buka http://127.0.0.1:8100
```

## Kalau mau backend Python ikut online

GitHub Pages tidak bisa. Pakai host yang menjalankan Python (Render / Fly.io /
Railway / VPS), jalankan `python app.py` (port dari env `CRYPTOPULSE_PORT`),
lalu arahkan `docs/app.js` ke URL backend itu — atau tetap pakai versi statis
yang sekarang, karena datanya sudah real-time tanpa server.
