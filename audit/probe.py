"""Probe lanjutan: apakah arah singkat (5-15m) sebaiknya contrarian? + edge setelah fee."""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

ROOT = r"C:\Users\Evaluation Software\Projects\cryptopulse"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "audit"))
import run_audit as A  # noqa: E402

FEE_PCT = 0.10  # taker masuk+keluar ~0.1% (0.05% per sisi di spot Binance)


def wilson(k, n, z=1.96):
    p = k / n
    den = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / den * 100, (c + m) / den * 100)


def main():
    syms = A.SYMS
    data = {s: A.fetch_klines(s) for s in syms}
    F = {s: A.feats(d) for s, d in data.items()}
    print(f"{'H':>4} {'mode':<16} {'n':>7} {'hit%':>7} {'CI95':>15} {'edge%':>8} {'edge-fee':>9}")
    summary = {}
    for H in (5, 15, 30, 60):
        pool = {"momentum": [], "contrarian": [], "macd+atr": [], "macd+atr(-)": []}
        for s, d in data.items():
            c = d["c"]
            n = len(c)
            fwd = np.full(n, np.nan)
            fwd[:-H] = (c[H:] / c[:-H] - 1) * 100
            idx = np.arange(400, n - H, H)
            f = F[s]
            ens = 1.0 * f["ema_ribbon"] + 1.6 * f["cvd_obv"] + 0.8 * f["vwap"] \
                + 1.2 * f["macd_hist"] + 1.0 * f["atr_mom"] + 0.6 * f["bollinger"]
            sets = {
                "momentum": ens,
                "contrarian": -ens,
                "macd+atr": 1.2 * f["macd_hist"] + 1.0 * f["atr_mom"] + 0.6 * f["bollinger"],
                "macd+atr(-)": -(1.2 * f["macd_hist"] + 1.0 * f["atr_mom"] + 0.6 * f["bollinger"]),
            }
            for k, sc in sets.items():
                m = A.score_metrics(sc[idx], fwd[idx], thr=0.05)
                if m:
                    pool[k].append(m)
        for k, lst in pool.items():
            n_tot = sum(x["n"] for x in lst)
            hit = sum(x["hit"] * x["n"] for x in lst) / n_tot
            lo, hi = wilson(round(hit / 100 * n_tot), n_tot)
            edge = float(np.mean([x["edge"] for x in lst]))
            print(f"{H:>4} {k:<16} {n_tot:>7} {hit:>7.1f} {lo:>7.1f}-{hi:<7.1f} "
                  f"{edge:>8.3f} {edge - FEE_PCT:>9.3f}")
            summary[f"{H}:{k}"] = dict(n=n_tot, hit=hit, lo=lo, hi=hi, edge=edge,
                                       edge_after_fee=edge - FEE_PCT)
        print()
    json.dump(summary, open(os.path.join(ROOT, "audit", "probe.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
