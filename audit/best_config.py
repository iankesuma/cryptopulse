"""Konfigurasi terbaik: horizon 60m + filter selektif (breakout Donchian / gate keluarga).

Event-based (bukan stride): satu trade per event, event dijarangkan minimal = horizon
supaya tidak tumpang tindih. Data: M1 14 hari, 12 instrumen (cache audit).
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

ROOT = r"C:\Users\Evaluation Software\Projects\cryptopulse"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "audit"))
import run_audit as A  # noqa: E402

H = 60


def wilson(k, n, z=1.96):
    p = k / n
    den = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / den * 100, (c + m) / den * 100)


def evaluate(sym_data, selector, label):
    hits = 0
    n = 0
    ret_up, ret_dn = [], []
    per_sym = []
    for sym, (d, F) in sym_data.items():
        c = d["c"]
        m = len(c)
        ens = (1.0 * F["ema_ribbon"] + 1.2 * F["macd_hist"] + 1.0 * F["atr_mom"]
               + 0.6 * F["bollinger"] + 0.8 * F["vwap"] + 0.6 * F["cvd_obv"])
        cats = np.vstack([F["ema_ribbon"],
                          0.5 * F["macd_hist"] + 0.5 * F["bollinger"],
                          0.6 * F["cvd_obv"] + 0.4 * F["vwap"]])
        agree = np.sum((np.sign(cats) == np.sign(ens)) & (np.abs(cats) > 0.05), axis=0)
        fwd = np.full(m, np.nan)
        fwd[:-H] = (c[H:] / c[:-H] - 1) * 100
        idx = None
        if selector == "all":
            idx = np.arange(300, m - H, H)
        elif selector == "breakout":
            cand = np.where(np.abs(F["donchian"]) > 0.5)[0]
            idx = []
            last = -10**9
            for i in cand:
                if i < 300 or i >= m - H:
                    continue
                if i - last >= H:
                    idx.append(i)
                    last = i
            idx = np.array(idx, dtype=int)
        elif selector == "breakout+agree":
            cand = np.where(np.abs(F["donchian"]) > 0.5)[0]
            idx = []
            last = -10**9
            for i in cand:
                if i < 300 or i >= m - H or i - last < H:
                    continue
                if np.sign(ens[i]) != np.sign(F["donchian"][i]):
                    continue
                if agree[i] < 2:
                    continue
                idx.append(i)
                last = i
            idx = np.array(idx, dtype=int)
        elif selector == "agree3":
            cand = np.where(agree >= 3)[0]
            idx = []
            last = -10**9
            for i in cand:
                if i < 300 or i >= m - H:
                    continue
                if i - last >= H:
                    idx.append(i)
                    last = i
            idx = np.array(idx, dtype=int)
        if idx is None or len(idx) == 0:
            continue
        sel = idx[np.isfinite(fwd[idx])]
        if len(sel) == 0:
            continue
        f = fwd[sel]
        s = ens[sel]
        ok = np.sign(s) == np.sign(f)
        hits += int(ok.sum())
        n += len(sel)
        ret_up.extend(f[s > 0].tolist())
        ret_dn.extend(f[s < 0].tolist())
        per_sym.append((sym, len(sel), round(float(ok.mean()) * 100, 1)))
    if not n:
        print(f"{label:<18} tidak ada event")
        return None
    hit = hits / n * 100
    lo, hi = wilson(hits, n)
    edge = (np.mean(ret_up) if ret_up else 0) + (np.mean(ret_dn) if ret_dn else 0) * -1
    print(f"{label:<18} n={n:>6} hit={hit:5.1f}%  CI95 {lo:.1f}-{hi:.1f}  "
          f"edge={edge:+.3f}%  net(fee .10)={edge-0.10:+.3f}%")
    return dict(label=label, n=n, hit=round(hit, 2), lo=round(lo, 2), hi=round(hi, 2),
                edge=round(float(edge), 4), per_sym=per_sym)


def main():
    data = {}
    for s in A.SYMS:
        d = A.fetch_klines(s)
        data[s] = (d, A.feats(d))
    out = []
    print(f"horizon {H} menit, event-based (non-overlapping)\n")
    for sel, label in (("all", "semua sinyal"),
                       ("agree3", "3/3 keluarga"),
                       ("breakout", "breakout Donchian"),
                       ("breakout+agree", "breakout + 2/3")):
        r = evaluate(data, sel, label)
        if r:
            out.append(r)
    json.dump(out, open(os.path.join(ROOT, "audit", "best_config.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
