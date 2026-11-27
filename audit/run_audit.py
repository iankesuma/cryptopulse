"""Audit teknis + backtest besar CryptoPulse.

Bagian:
  1. VALIDASI  : cocokkan indikator sendiri vs implementasi referensi (pandas),
                 cek look-ahead, cek konsistensi supertrend/ATR.
  2. DATA      : tarik 14 hari klines 1m Binance untuk 10 instrumen (cache npz).
  3. BACKTEST  : IC + hit rate (Wilson CI) per fitur per horizon 5/15/30/60 mnt,
                 non-overlapping (stride = horizon), dipool lintas simbol.
  4. KOMBINASI : ensemble voter sekarang vs "semua fitur IC positif" vs versi gate.
  5. ML        : LightGBM walk-forward (70/30 tanpa shuffle), akurasi arah + AUC.
Output: audit/results.json + tabel ke stdout.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.request
from statistics import NormalDist

import numpy as np

ROOT = r"C:\Users\Evaluation Software\Projects\cryptopulse"
sys.path.insert(0, ROOT)
import indicators as I  # noqa: E402

REST = "https://data-api.binance.vision"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
DAYS = 14
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
        "LINKUSDT", "AVAXUSDT", "ADAUSDT", "XAUTUSDT", "LTCUSDT", "ARBUSDT"]
HORIZONS = [5, 15, 30, 60]
os.makedirs(CACHE, exist_ok=True)


# ------------------------------------------------------------------ data
def fetch_klines(sym: str, days: int = DAYS) -> dict:
    path = os.path.join(CACHE, f"{sym}_1m_{days}d.npz")
    if os.path.exists(path):
        z = np.load(path)
        return {k: z[k] for k in z.files}
    end = int(time.time() * 1000)
    want = days * 1440
    rows = []
    while len(rows) < want:
        limit = min(1000, want - len(rows))
        url = (f"{REST}/api/v3/klines?symbol={sym}&interval=1m&limit={limit}"
               f"&endTime={end}")
        with urllib.request.urlopen(url, timeout=30) as r:
            batch = json.loads(r.read().decode())
        if not batch:
            break
        rows = batch + rows
        end = batch[0][0] - 60000
        time.sleep(0.12)
    arr = {
        "t": np.array([r[0] for r in rows], dtype=np.int64),
        "o": np.array([float(r[1]) for r in rows]),
        "h": np.array([float(r[2]) for r in rows]),
        "l": np.array([float(r[3]) for r in rows]),
        "c": np.array([float(r[4]) for r in rows]),
        "v": np.array([float(r[5]) for r in rows]),
        "tb": np.array([float(r[9]) for r in rows]),
    }
    np.savez_compressed(path, **arr)
    return arr


# ------------------------------------------------------------------ referensi pandas
def validate_indicators(sym="BTCUSDT"):
    d = fetch_klines(sym, 2)
    c, h, l, v = d["c"], d["h"], d["l"], d["v"]
    import pandas as pd

    out = []
    s = pd.Series(c)

    mine = I.ema(c, 20)[-200:]
    ref = s.ewm(span=20, adjust=False).mean().values[-200:]
    out.append(("EMA(20)", float(np.max(np.abs(mine / ref - 1)))))

    mine = I.sma(c, 20)[-200:]
    ref = s.rolling(20).mean().values[-200:]
    m = np.isfinite(mine) & np.isfinite(ref)
    out.append(("SMA(20)", float(np.max(np.abs(mine[m] / ref[m] - 1)))))

    mine = I.rsi(c, 14)[-300:]
    delta = s.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    ref = (100 - 100 / (1 + up / dn)).values[-300:]
    out.append(("RSI(14)", float(np.max(np.abs(mine - ref)))))

    mid, upb, lob, pb, bw = I.bollinger(c, 20, 2.0)
    ref_mid = s.rolling(20).mean().values
    m = np.isfinite(mid) & np.isfinite(ref_mid)
    out.append(("BB mid(20)", float(np.max(np.abs(mid[m] / ref_mid[m] - 1)))))

    # ATR: engine pakai EMA-of-TR (bukan Wilder RMA) → ukur selisih relatif
    a_mine = I.atr(h, l, c, 14)
    tr = pd.concat([pd.Series(h) - pd.Series(l),
                    (pd.Series(h) - pd.Series(c).shift()).abs(),
                    (pd.Series(l) - pd.Series(c).shift()).abs()], axis=1).max(axis=1)
    a_wilder = tr.ewm(alpha=1 / 14, adjust=False).mean().values
    m = np.isfinite(a_mine) & np.isfinite(a_wilder) & (a_wilder > 0)
    out.append(("ATR(14) vs Wilder", float(np.max(np.abs(a_mine[m] / a_wilder[m] - 1)))))

    # supertrend: bandingkan dengan implementasi kanonik (band final + flip pakai band final)
    _st, direction = I.supertrend(h, l, c, 10, 3.0)
    atr10 = I.atr(h, l, c, 10)
    hl2 = (h + l) / 2
    upper, lower = hl2 + 3 * atr10, hl2 - 3 * atr10
    fu, fl = upper[0], lower[0]
    dref = np.ones(len(c))
    for i in range(1, len(c)):
        fu = upper[i] if (upper[i] < fu or c[i - 1] > fu) else fu
        fl = lower[i] if (lower[i] > fl or c[i - 1] < fl) else fl
        if c[i] > fu:
            dref[i] = 1
        elif c[i] < fl:
            dref[i] = -1
        else:
            dref[i] = dref[i - 1]
    agree = float((direction == dref).mean() * 100)
    flips = int((np.diff(direction) != 0).sum())
    flips_ref = int((np.diff(dref) != 0).sum())
    out.append(("SuperTrend agree% (100=identik)", agree))
    out.append(("SuperTrend flips mine/ref", float(flips - flips_ref)))

    # look-ahead test: fitur pada bar t tidak boleh berubah saat data masa depan dipotong
    cut = len(c) - 60
    e_full = I.ema(c, 9)[cut - 1]
    e_trunc = I.ema(c[:cut], 9)[-1]
    out.append(("look-ahead EMA (0=aman)", abs(e_full - e_trunc) / max(abs(e_full), 1e-9)))

    # VWAP sesi: deviasi tidak boleh > 5% untuk window 240 di data normal
    dev = abs(I.vwap_session(h[-240:], l[-240:], c[-240:], v[-240:]) / c[-1] - 1) * 100
    out.append(("VWAP dev% (wajar <5)", dev))
    return out


# ------------------------------------------------------------------ fitur kandidat
def feats(d) -> dict:
    o, h, l, c, v, tb = d["o"], d["h"], d["l"], d["c"], d["v"], d["tb"]
    n = len(c)
    f = {}
    e9, e21, e55 = I.ema(c, 9), I.ema(c, 21), I.ema(c, 55)
    f["ema_ribbon"] = np.where((e9 > e21) & (e21 > e55), 0.6,
                               np.where((e9 < e21) & (e21 < e55), -0.6, 0.0))

    _st, direction = I.supertrend(h, l, c, 10, 3.0)
    f["supertrend"] = direction * 0.7

    r = I.rsi(c, 14)
    f["rsi_level"] = np.clip((r - 50) / 60.0, -0.3, 0.3)
    r5 = I.rsi(c, 5)
    f["rsi5"] = np.clip((r5 - 50) / 50.0, -0.4, 0.4)

    _m, _u, _lo, pb, _bw = I.bollinger(c, 20, 2.0)
    f["bollinger"] = np.clip(np.nan_to_num((pb - 0.5) * 0.5, nan=0.0), -0.3, 0.3)

    # VWAP rolling 240 (vectorized)
    tp = (h + l + c) / 3.0
    pv = np.cumsum(tp * v)
    cv = np.cumsum(v)
    w = 240
    vw = np.full(n, np.nan)
    vw[w - 1:] = (pv[w - 1:] - np.r_[0, pv[:-w]]) / np.maximum(cv[w - 1:] - np.r_[0, cv[:-w]], 1e-12)
    dev = np.nan_to_num((c - vw) / np.where(vw > 0, vw, 1) * 100, nan=0.0)
    f["vwap"] = np.clip(dev / 2.0, -0.7, 0.7)

    # CVD/OBV slope 60 (difference-based, cepat)
    delta = 2 * tb - v
    cvd = np.cumsum(delta)
    ob = I.obv(c, v)
    sl = np.zeros(n)
    idx = np.arange(60, n)
    mv = np.array([v[i - 59:i + 1].mean() for i in idx])
    sl[idx] = (0.6 * (cvd[idx] - cvd[idx - 60]) / 60 + 0.4 * (ob[idx] - ob[idx - 60]) / 60) / np.maximum(mv, 1e-9)
    f["cvd_obv"] = np.clip(sl * 20, -0.8, 0.8)

    # MACD histogram (12/26/9) dinormalisasi ATR
    macd = I.ema(c, 12) - I.ema(c, 26)
    sig = I.ema(macd, 9)
    atr = np.maximum(I.atr(h, l, c, 14), 1e-9)
    f["macd_hist"] = np.clip((macd - sig) / atr * 1.5, -0.8, 0.8)

    # ADX / DI
    up_move = np.diff(h, prepend=h[0])
    dn_move = -np.diff(l, prepend=l[0])
    plus_dm = np.where((up_move > dn_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((dn_move > up_move) & (dn_move > 0), dn_move, 0.0)
    tr = I.true_range(h, l, c)
    atr14 = I.ema(tr, 14)
    pdi = 100 * I.ema(plus_dm, 14) / np.maximum(atr14, 1e-9)
    mdi = 100 * I.ema(minus_dm, 14) / np.maximum(atr14, 1e-9)
    dx = 100 * np.abs(pdi - mdi) / np.maximum(pdi + mdi, 1e-9)
    adx = I.ema(dx, 14)
    f["adx_trend"] = np.where(adx > 20, np.where(pdi > mdi, 0.6, -0.6), 0.0)

    # Stochastic 14
    lo14 = np.array([l[max(0, i - 13):i + 1].min() for i in range(n)])
    hi14 = np.array([h[max(0, i - 13):i + 1].max() for i in range(n)])
    k = (c - lo14) / np.maximum(hi14 - lo14, 1e-9)
    f["stoch"] = np.clip((k - 0.5) * 0.6, -0.3, 0.3)

    # Donchian breakout 20 (pakai bar sebelumnya, tanpa look-ahead)
    hh = np.array([h[max(0, i - 20):i].max() if i > 0 else h[0] for i in range(n)])
    ll = np.array([l[max(0, i - 20):i].min() if i > 0 else l[0] for i in range(n)])
    f["donchian"] = np.where(c > hh, 0.7, np.where(c < ll, -0.7, 0.0))

    # volume surge × arah ret5
    ret5 = np.r_[np.zeros(5), (c[5:] / c[:-5] - 1) * 100]
    vz = np.zeros(n)
    for i in range(60, n):
        seg = v[i - 59:i + 1]
        sd = seg.std()
        vz[i] = 0 if sd < 1e-12 else (v[i] - seg.mean()) / sd
    f["vol_surge"] = np.clip(np.sign(ret5) * np.minimum(vz, 3) / 3 * 0.5, -0.5, 0.5)

    # momentum ternormalisasi ATR
    ret10 = np.r_[np.zeros(10), (c[10:] / c[:-10] - 1) * 100]
    f["atr_mom"] = np.clip(ret10 / np.maximum(atr / c * 100 * 3, 1e-9), -0.8, 0.8)
    return f


# ------------------------------------------------------------------ metrik
def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((centre - margin) / den * 100, (centre + margin) / den * 100)


def score_metrics(score, fwd, thr=0.05):
    """non-overlapping: pemanggil sudah men-stride fwd/score."""
    ok = np.isfinite(score) & np.isfinite(fwd)
    s, f = score[ok], fwd[ok]
    if len(s) < 50:
        return None
    sel = np.abs(s) >= thr
    if sel.sum() < 30:
        return None
    hit = int(((np.sign(s[sel]) == np.sign(f[sel])).sum()))
    n = int(sel.sum())
    lo, hi = wilson(hit, n)
    ic = float(np.corrcoef(s, f)[0, 1]) if s.std() > 1e-9 else 0.0
    up = f[s > thr].mean() if (s > thr).sum() else 0.0
    dn = f[s < -thr].mean() if (s < -thr).sum() else 0.0
    return dict(n=n, hit=hit / n * 100, lo=lo, hi=hi, ic=ic, edge=float(up - dn))


def main():
    print("=" * 78)
    print("1) VALIDASI INDIKATOR (vs referensi pandas, data 2 hari BTCUSDT)")
    print("=" * 78)
    for name, val in validate_indicators():
        print(f"  {name:<28} {val:>12.6f}")

    print("\n" + "=" * 78)
    print(f"2) BACKTEST {len(SYMS)} instrumen × {DAYS} hari klines 1m")
    print("=" * 78)
    data = {}
    for s in SYMS:
        try:
            data[s] = fetch_klines(s)
            print(f"  data {s:<9} {len(data[s]['c']):>6} bar")
        except Exception as e:  # noqa: BLE001
            print("  gagal", s, e)

    print("  hitung fitur sekali per simbol...")
    F = {}
    t0 = time.time()
    for s_, d in data.items():
        F[s_] = feats(d)
    print(f"  fitur siap dalam {time.time() - t0:.1f}s")

    res = {}
    for H in HORIZONS:
        pooled = {}
        for s, d in data.items():
            c = d["c"]
            n = len(c)
            if n < 2000:
                continue
            fwd_full = np.full(n, np.nan)
            fwd_full[:-H] = (c[H:] / c[:-H] - 1) * 100
            idx = np.arange(400, n - H, H)          # stride = horizon
            f = F[s]
            for name, arr in f.items():
                m = score_metrics(arr[idx], fwd_full[idx])
                if not m:
                    continue
                pooled.setdefault(name, []).append(m)
        rows = {}
        for name, lst in pooled.items():
            n_tot = sum(x["n"] for x in lst)
            hit = sum(x["hit"] * x["n"] for x in lst) / n_tot
            k = round(hit / 100 * n_tot)
            lo, hi = wilson(k, n_tot)
            rows[name] = dict(
                n=n_tot, hit=hit, lo=lo, hi=hi,
                ic=float(np.mean([x["ic"] for x in lst])),
                edge=float(np.mean([x["edge"] for x in lst])),
                sym_hit_med=float(np.median([x["hit"] for x in lst])),
                sym_pos=int(sum(1 for x in lst if x["ic"] > 0)),
                sym=int(len(lst)),
            )
        res[f"H{H}"] = rows
        print(f"\n  --- horizon {H} menit (stride {H} bar, non-overlapping) ---")
        print(f"  {'fitur':<13}{'n':>8}{'hit%':>7}{'CI95':>15}{'IC':>8}{'edge%':>8}{'simbol+IC':>11}")
        for name, r in sorted(rows.items(), key=lambda kv: -kv[1]["ic"]):
            print(f"  {name:<13}{r['n']:>8}{r['hit']:>7.1f}"
                  f"{r['lo']:>7.1f}-{r['hi']:<7.1f}{r['ic']:>8.3f}{r['edge']:>8.3f}"
                  f"{r['sym_pos']:>6}/{r['sym']:<4}")

    # ---- kombinasi
    print("\n" + "=" * 78)
    print("3) KOMBINASI: voter sekarang vs IC-weighted vs gate kategori")
    print("=" * 78)
    for H in (15, 60):
        rows = res[f"H{H}"]
        pos = [k for k, v in rows.items() if v["ic"] > 0.02]
        print(f"\n  horizon {H}m — fitur IC>0.02: {pos}")
        agg = {"voter_now": [], "ic_weighted": [], "gate_2of3": []}
        for s, d in data.items():
            c = d["c"]
            n = len(c)
            if n < 2000:
                continue
            fwd = np.full(n, np.nan)
            fwd[:-H] = (c[H:] / c[:-H] - 1) * 100
            idx = np.arange(400, n - H, H)
            f = F[s]
            ens = 1.0 * f["ema_ribbon"] + 1.6 * f["cvd_obv"] + 0.8 * f["vwap"]
            m = score_metrics(ens[idx], fwd[idx])
            if m:
                agg["voter_now"].append(m)
            if pos:
                wsum = sum(max(rows[k]["ic"], 0) for k in pos)
                icw = sum(max(rows[k]["ic"], 0) / wsum * f[k] for k in pos)
                m = score_metrics(icw[idx], fwd[idx])
                if m:
                    agg["ic_weighted"].append(m)
            cats = {"tren": f["ema_ribbon"], "flow": 0.66 * f["cvd_obv"] + 0.34 * f["vwap"],
                    "mikro": f["donchian"]}
            cs = np.vstack([cats["tren"], cats["flow"], cats["mikro"]])
            agree = np.sum((cs > 0.05).astype(int) | (cs < -0.05).astype(int), axis=0)
            sign_agree = np.sum((np.sign(cs) == np.sign(ens)) & (np.abs(cs) > 0.05), axis=0)
            gated = np.where(sign_agree >= 2, ens, 0.0)
            m = score_metrics(gated[idx], fwd[idx])
            if m:
                agg["gate_2of3"].append(m)
        for k, lst in agg.items():
            if not lst:
                continue
            n_tot = sum(x["n"] for x in lst)
            hit = sum(x["hit"] * x["n"] for x in lst) / n_tot
            lo, hi = wilson(round(hit / 100 * n_tot), n_tot)
            print(f"    {k:<11} n={n_tot:>7} hit={hit:5.1f}% CI95 {lo:.1f}-{hi:.1f} "
                  f"IC={np.mean([x['ic'] for x in lst]):+.3f}")

    # ---- ML walk-forward
    print("\n" + "=" * 78)
    print("4) LIGHTGBM WALK-FORWARD (70% train / 30% test, tanpa shuffle)")
    print("=" * 78)
    try:
        import lightgbm as lgb

        for H in (15, 60):
            accs, aucs, hits, ns = [], [], [], []
            for s, d in data.items():
                f = F[s]
                c = d["c"]
                n = len(c)
                if n < 3000:
                    continue
                ret10 = np.r_[np.zeros(10), (c[10:] / c[:-10] - 1) * 100]
                X = np.column_stack([f[k] for k in f] + [ret10])
                y = np.full(n, np.nan)
                y[:-H] = (c[H:] / c[:-H] > 1.0).astype(float)
                ok = np.isfinite(y)
                X, y = X[ok], y[ok]
                cut = int(len(X) * 0.7)
                if cut < 1500:
                    continue
                params = dict(objective="binary", learning_rate=0.05, num_leaves=15,
                              min_data_in_leaf=40, feature_fraction=0.8, bagging_fraction=0.8,
                              bagging_freq=1, lambda_l2=2.0, verbose=-1, num_threads=2)
                bst = lgb.train(params, lgb.Dataset(X[:cut], label=y[:cut]), num_boost_round=150)
                p = bst.predict(X[cut:])
                pred = (p > 0.5).astype(int)
                acc = float((pred == y[cut:]).mean())
                # hit hanya pada prediksi yakin (|p-0.5|>0.05)
                sel = np.abs(p - 0.5) > 0.05
                hit = float(((pred[sel] == y[cut:][sel]).mean())) if sel.sum() else float("nan")
                accs.append(acc)
                hits.append(hit)
                ns.append(int(sel.sum()))
                if len(np.unique(y[cut:])) > 1:
                    from numpy import argsort
                    ranks = argsort(argsort(p)) / max(len(p) - 1, 1)
                    # AUC sederhana
                    ppos = p[y[cut:] == 1]
                    pneg = p[y[cut:] == 0]
                    auc = float((ppos[:, None] > pneg[None, :]).mean()) if len(ppos) and len(pneg) else float("nan")
                    aucs.append(auc)
            if accs:
                print(f"  horizon {H}m: akurasi={np.mean(accs)*100:.1f}% "
                      f"hit(prediksi yakin)={np.nanmean(hits)*100:.1f}% "
                      f"AUC={np.nanmean(aucs):.3f} | {len(accs)} simbol")
    except Exception as e:  # noqa: BLE001
        print("  ML gagal:", type(e).__name__, e)

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json"), "w",
              encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    print("\nhasil mentah -> audit/results.json")


if __name__ == "__main__":
    main()
