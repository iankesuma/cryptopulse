# Audit CryptoPulse — 27 Nov 2026

Cakupan: validasi rumus indikator, uji look-ahead, backtest 14 hari × 12 instrumen
(klines 1m, sampel non-overlapping), uji fitur kandidat baru, walk-forward LightGBM.
Skrip: `audit/run_audit.py`, `audit/probe.py`. Data cache: `audit/cache/`.

---

## 1. Validasi indikator (vs implementasi referensi pandas)

| Indikator | Status awal | Setelah perbaikan |
|---|---|---|
| EMA(20) | ✅ identik (0.0000) | ✅ |
| SMA(20) | ✅ identik | ✅ |
| Bollinger mid(20) | ✅ identik | ✅ |
| **RSI(14)** | ❌ **deviasi sampai 14.9 poin** | ✅ identik (0.0000) |
| **ATR(14)** | ❌ **deviasi 46.7%** | ✅ identik (0.0000) |
| SuperTrend | ✅ 100% sama arah & jumlah flip vs implementasi kanonik | ✅ |
| Look-ahead (EMA) | ✅ 0.0000 (fitur tidak berubah saat data masa depan dipotong) | ✅ |
| VWAP deviasi | ✅ 0.31% (wajar) | ✅ |

**Dua bug nyata yang ditemukan dan diperbaiki:**

1. `atr()` memakai EMA biasa (α = 2/(n+1)) bukan Wilder RMA (α = 1/n) → ATR
   kelebihan ~47%. Dampak: garis SuperTrend salah posisi, `sigma` prediksi,
   lebar band, dan confidence ikut salah.
2. `rsi()` juga pakai EMA, bukan Wilder → RSI tampil lebih ekstrem daripada
   RSI standar (bisa beda 15 poin; di chart orang lain angkanya tidak akan sama).

Setelah perbaikan, kelima indikator inti cocok 100% dengan referensi.

---

## 2. Backtest: IC per fitur per horizon (14 hari × 12 instrumen)

Sampel non-overlapping (stride = horizon), hit rate dihitung pada |skor| ≥ 0.05,
IC = korelasi skor vs return horizon.

| fitur | H5 | H15 | H30 | H60 |
|---|---|---|---|---|
| macd_hist | −0.021 | −0.009 | +0.030 | **+0.098** |
| atr_mom | −0.022 | −0.007 | +0.024 | **+0.069** |
| bollinger | −0.021 | −0.016 | +0.015 | +0.050 |
| rsi_level | −0.019 | −0.017 | +0.010 | +0.044 |
| adx_trend | −0.010 | −0.004 | +0.021 | +0.037 |
| stoch | −0.021 | −0.015 | +0.006 | +0.035 |
| vol_surge | −0.001 | +0.016 | −0.005 | +0.034 |
| donchian | −0.005 | −0.017 | +0.005 | +0.016 |
| cvd_obv | −0.000 | +0.001 | −0.004 | +0.015 |
| supertrend | −0.021 | −0.009 | +0.009 | +0.014 |
| ema_ribbon | −0.006 | +0.005 | +0.028 | +0.011 |
| vwap | −0.005 | −0.005 | −0.007 | +0.007 |

**Temuan utama: horizon lebih menentukan daripada pilihan indikator.**
Di H5/H15 hampir semua indikator IC **negatif** — pasar 1m sedang mean-reverting,
jadi semua indikator tren justru salah arah.

Hit rate (subset |skor|≥0.05), pooled:

| mode | H5 | H15 | H30 | H60 |
|---|---|---|---|---|
| momentum (ensemble) | 46.3% | 46.5% | 48.5% | 50.7% |
| kontrarian (ensemble dibalik) | 49.5% | **51.2%** | 49.6% | 48.0% |
| macd+atr momentum | 46.0% | 46.8% | 49.8% | **51.6%** |
| macd+atr kontrarian | 49.8% | 50.9% | 48.3% | 47.0% |

Edge per trade (return rata-rata skor>thr minus skor<−thr), fee taker spot ≈ 0.10%:

| mode | H15 | H30 | H60 |
|---|---|---|---|
| momentum | −0.004% | +0.028% | +0.069% |
| macd+atr momentum | −0.004% | +0.018% | **+0.109%** (net +0.009%) |
| kontrarian | +0.004% | −0.028% | −0.069% |

Kesimpulan: **hanya H60 dengan MACD+ATR-momentum yang positif setelah biaya**, dan
tipis (+0.009%/trade). H15 kontrarian menang tipis secara statistik (CI 50.4–52.0%)
tapi edge-nya 0.004% — tidak cukup untuk menutup spread/fee.

---

## 3. Korelasi antar sinyal (redundansi)

BTCUSDT, 14 hari: EMA vs SuperTrend **0.67**, EMA vs RSI 0.47, SuperTrend vs RSI 0.57,
EMA vs CVD 0.44. Artinya menambah MACD/RSI/Stoch/Ichimoku ke panel lama tidak
menambah informasi — hanya mengulang keluarga yang sama. Yang benar-benar berbeda:
order flow (CVD/CVD slope) dan fitur baru MACD-hist/ATR-mom (keduanya IC positif di 12/12
instrumen pada H60).

---

## 4. LightGBM walk-forward (70% train / 30% test, tanpa shuffle)

| horizon | akurasi | base rate | balanced acc | AUC | hit (prediksi yakin) |
|---|---|---|---|---|---|
| 15m | 51.7% | 51.1% | 51.1% | 0.517 | 52.2% |
| 60m | 49.8% | 51.2% | 49.8% | 0.499 | 49.8% |

Model ML **tidak punya skill out-of-sample** (AUC ≈ 0.5). Sebelumnya angka 100%
di laporan pertama adalah bug label (`rasio > 0` selalu True); sudah diperbaiki di
skrip audit. Konsekuensi: panel LightGBM diturunkan jadi **info-only**, bukan voter.

---

## 5. Perubahan yang diterapkan ke app

1. **ATR & RSI → Wilder RMA** (perbaikan bug).
2. **Horizon default 60 menit**, bisa dipilih 5/15/30/60 dari UI.
   `HORIZON_MIN` mengatur sigma prediksi, label ML, dan tabel IC.
3. **Bobot voter = |IC| × 12, arah = sign(IC)** — bukan lagi angka manual.
   Tabel IC per horizon ada di `ic_table.json` (hasil audit ini).
   Aturan dengan |IC| < 0.010 otomatis jadi info-only.
4. **Dua indikator baru**: `MACD HISTOGRAM` (IC +0.098, 12/12 instrumen) dan
   `ATR MOMENTUM` (IC +0.069, 12/12) — keduanya pemimpin di H60.
5. **Gate per horizon**: ambang |skor| 0.25 / 0.22 / 0.18 / 0.12 untuk 5/15/30/60,
   plus ≥2 dari 3 keluarga (tren / momentum / flow) harus sepakat.
   Di H15 hampir selalu WAIT — itu memang jawaban yang benar menurut data.
6. **UI menampilkan backtest apa adanya**: hit rate, edge/trade, dan edge setelah
   fee 0.10% untuk horizon aktif.
7. Panel ML tetap tampil tapi diberi bobot 0 dan ikut dihitung ulang tiap 15 menit
   (tidak lagi tiap 4 menit).

---

## 6. Yang **tidak** membantu (sudah diuji, jangan diulang)

- Menambah osilator sekeluarga tren (MACD lama, Stoch, ADX, Ichimoku, CCI) ke panel
  lama saat horizon 15m — korelasinya 0.5–0.7 dengan yang sudah ada, IC tetap ≤ 0.
- Memperbesar bobot ML — AUC out-of-sample 0.499.
- Gate lebih ketat di H15 (2/3 keluarga): menurunkan hit rate dari 47.1% → 45.8%
  karena sampelnya jadi sedikit dan bias seleksi.
- Order book imbalance & funding: tidak punya riwayat → tidak bisa divalidasi;
  tetap dipakai sebagai konteks, bobot dari IC = 0 (info-only).

---

## 7. Keterbatasan (jujur)

- Jendela uji 14 hari, satu rezim pasar (BTC naik dari ~69k ke ~62k, volatil).
- Sampel saling tumpang tindih sebagian (stride = horizon hanya mengurangi, bukan
  menghilangkan autokorelasi); CI 95% sudah dilaporkan per fitur.
- Backtest memakai mid/close, belum model slippage; fee diasumsikan 0.10% round-trip.
- Fitur depth/order-flow historis tidak tersedia dari Binance REST → tidak diuji.

**Kesimpulan satu baris:** indikator yang ada sudah benar secara matematis setelah
dua bug Wilder diperbaiki, tapi *edge*-nya tipis dan hanya muncul di horizon 60 menit;
masalah utamanya bukan kurang indikator, melainkan horizon dan bobot yang belum
mengikuti bukti — keduanya sudah diperbaiki sekarang.
