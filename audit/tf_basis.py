"""Basis timeframe: M1 vs M5 vs M15 vs H1 untuk fitur yang sama.

Untuk tiap TF: tarik klines interval itu, hitung fitur yang sama, lalu uji IC + hit
pada horizon yang sama dalam MENIT (15/60/240) supaya apel-ke-apel.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

import numpy as np

ROOT = r"C:\Users\Evaluation Software\Projects\cryptopulse"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "audit"))
import run_audit as A  # noqa: E402

REST = "https://data-api.binance.vision"
CACHE = os.path.join(ROOT, "audit", "cache")
SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "XAUTUSDT", "LINKUSDT", "BNBUSDT"]
TFS = {"1h": 60}   # 5m/15m sudah teruji (lihat result sebelumnya)
BARS = 8000
HORIZONS_MIN = [15, 60, 240]


def fetch_tf(sym: str, interval: str, bars: int = BARS) -> dict:
    path = os.path.join(CACHE, f"{sym}_{interval}_{bars}.npz")
    if os.path.exists(path):
        z = np.load(path)
        return {k: z[k] for k in z.files}
    end = int(time.time() * 1000)
    rows: list = []
    while len(rows) < bars:
        limit = min(1000, bars - len(rows))
        url = f"{REST}/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}&endTime={end}"
        with urllib.request.urlopen(url, timeout=30) as r:
            batch = json.loads(r.read().decode())
        if not batch:
            break
        rows = batch + rows
        end = batch[0][0] - 1
        time.sleep(0.1)
    a = {
        "t": np.array([r[0] for r in rows], dtype=np.int64),
        "o": np.array([float(r[1]) for r in rows]),
        "h": np.array([float(r[2]) for r in rows]),
        "l": np.array([float(r[3]) for r in rows]),
        "c": np.array([float(r[4]) for r in rows]),
        "v": np.array([float(r[5]) for r in rows]),
        "tb": np.array([float(r[9]) for r in rows]),
    }
    np.savez_compressed(path, **a)
    return a


def main():
    print(f"{'TF':<5}{'H(menit)':>9}{'bar ke depan':>14}{'n':>8}{'hit%':>8}{'CI95':>15}{'IC':>8}{'edge%':>8}")
    rows_out = []
    for tf_label, tf_min in TFS.items():
        feats_by_sym = {}
        for sym in SYMS:
            try:
                d = fetch_tf(sym, tf_label)
                feats_by_sym[sym] = (d, A.feats(d))
            except Exception as e:  # noqa: BLE001
                print("  gagal", sym, tf_label, e)
        for H in HORIZONS_MIN:
            hb = max(1, round(H / tf_min))          # horizon dalam bar
            pool = []
            for sym, (d, F) in feats_by_sym.items():
                c = d["c"]
                n = len(c)
                if n < 400 or hb >= n - 200:
                    continue
                fwd = np.full(n, np.nan)
                fwd[:-hb] = (c[hb:] / c[:-hb] - 1) * 100
                idx = np.arange(200, n - hb, hb)     # non-overlapping
                ens = (1.0 * F["ema_ribbon"] + 1.2 * F["macd_hist"] + 1.0 * F["atr_mom"]
                       + 0.6 * F["bollinger"] + 0.8 * F["vwap"] + 0.6 * F["cvd_obv"])
                m = A.score_metrics(ens[idx], fwd[idx], thr=0.05)
                if m:
                    pool.append(m)
            if not pool:
                continue
            n_tot = sum(x["n"] for x in pool)
            hit = sum(x["hit"] * x["n"] for x in pool) / n_tot
            lo, hi = A.wilson(round(hit / 100 * n_tot), n_tot)
            ic = float(np.mean([x["ic"] for x in pool]))
            edge = float(np.mean([x["edge"] for x in pool]))
            print(f"{tf_label:<5}{H:>9}{hb:>14}{n_tot:>8}{hit:>8.1f}{lo:>7.1f}-{hi:<7.1f}{ic:>8.3f}{edge:>8.3f}")
            rows_out.append(dict(tf=tf_label, horizon_min=H, bars_ahead=hb, n=n_tot,
                                 hit=round(hit, 2), lo=round(lo, 2), hi=round(hi, 2),
                                 ic=round(ic, 4), edge=round(edge, 4)))
        print()
    with open(os.path.join(ROOT, "audit", "tf_basis.json"), "w", encoding="utf-8") as fh:
        json.dump(rows_out, fh, indent=1)


if __name__ == "__main__":
    main()
