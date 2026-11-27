"""Indikator teknikal murni numpy (tanpa pandas) untuk engine CryptoPulse."""
from __future__ import annotations

import numpy as np


def ema(values: np.ndarray, period: int) -> np.ndarray:
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return v
    alpha = 2.0 / (period + 1.0)
    out = np.empty_like(v)
    out[0] = v[0]
    for i in range(1, v.size):
        out[i] = out[i - 1] + alpha * (v[i] - out[i - 1])
    return out


def rma(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder smoothing (RMA) — alpha 1/period, dipakai ATR & RSI standar."""
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return v
    alpha = 1.0 / period
    out = np.empty_like(v)
    out[0] = v[0]
    for i in range(1, v.size):
        out[i] = out[i - 1] + alpha * (v[i] - out[i - 1])
    return out


def sma(values: np.ndarray, period: int) -> np.ndarray:
    v = np.asarray(values, dtype=float)
    if v.size < period:
        return np.full_like(v, np.nan)
    c = np.cumsum(np.insert(v, 0, 0.0))
    out = np.full_like(v, np.nan)
    out[period - 1:] = (c[period:] - c[:-period]) / period
    return out


def rolling_std(values: np.ndarray, period: int) -> np.ndarray:
    v = np.asarray(values, dtype=float)
    out = np.full_like(v, np.nan)
    if v.size < period:
        return out
    for i in range(period - 1, v.size):
        out[i] = v[i - period + 1:i + 1].std()
    return out


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    h, l, c = map(lambda x: np.asarray(x, float), (high, low, close))
    prev = np.roll(c, 1)
    prev[0] = c[0]
    return np.maximum(h - l, np.maximum(np.abs(h - prev), np.abs(l - prev)))


def atr(high, low, close, period: int = 14) -> np.ndarray:
    """ATR standar Wilder: RMA dari True Range."""
    return rma(true_range(high, low, close), period)


def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    c = np.asarray(close, float)
    delta = np.diff(c, prepend=c[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    ag = rma(gain, period)
    al = rma(loss, period)
    rs = np.divide(ag, al, out=np.full_like(ag, np.inf), where=al > 1e-12)
    out = 100.0 - (100.0 / (1.0 + rs))
    return np.nan_to_num(out, nan=50.0)


def bollinger(close: np.ndarray, period: int = 20, mult: float = 2.0):
    c = np.asarray(close, float)
    mid = sma(c, period)
    sd = rolling_std(c, period)
    upper, lower = mid + mult * sd, mid - mult * sd
    rng = np.where((upper - lower) > 1e-12, upper - lower, 1e-12)
    pct_b = (c - lower) / rng
    width = rng / np.where(mid > 1e-12, mid, 1e-12)
    return mid, upper, lower, pct_b, width


def supertrend(high, low, close, period: int = 10, mult: float = 3.0):
    h, l, c = map(lambda x: np.asarray(x, float), (high, low, close))
    a = atr(h, l, c, period)
    hl2 = (h + l) / 2.0
    upper = hl2 + mult * a
    lower = hl2 - mult * a
    st = np.zeros_like(c)
    direction = np.ones_like(c)  # 1 = uptrend, -1 = downtrend
    fu, fl = upper[0], lower[0]
    for i in range(1, c.size):
        fu = min(upper[i], fu) if c[i - 1] <= fu else upper[i]
        fl = max(lower[i], fl) if c[i - 1] >= fl else lower[i]
        if c[i] > fu:
            direction[i] = 1
        elif c[i] < fl:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
        st[i] = fl if direction[i] > 0 else fu
    return st, direction


def obv(close, volume) -> np.ndarray:
    c, v = np.asarray(close, float), np.asarray(volume, float)
    d = np.diff(c, prepend=c[0])
    return np.cumsum(np.sign(d) * v)


def vwap_session(high, low, close, volume, day_start_index: int = 0):
    """VWAP dari (day_start_index) sampai bar terakhir."""
    h, l, c, v = map(lambda x: np.asarray(x, float), (high, low, close, volume))
    tp = (h + l + c) / 3.0
    tp = tp[day_start_index:]
    v = v[day_start_index:]
    tot = v.sum()
    if tot <= 0:
        return float(c[-1])
    return float((tp * v).sum() / tot)


def linreg_slope(values: np.ndarray) -> float:
    y = np.asarray(values, float)
    if y.size < 3:
        return 0.0
    x = np.arange(y.size, dtype=float)
    x -= x.mean()
    denom = (x * x).sum()
    if denom <= 0:
        return 0.0
    return float((x * (y - y.mean())).sum() / denom)


def pivot_points(window: np.ndarray, kind: str, k: int = 3):
    """Cari index pivot (fractal) lokal: kind 'low' atau 'high'."""
    w = np.asarray(window, float)
    idx = []
    for i in range(k, len(w) - k):
        seg = w[i - k:i + k + 1]
        if kind == "low" and w[i] == seg.min() and w[i] < w[i - k] and w[i] < w[i + k]:
            idx.append(i)
        if kind == "high" and w[i] == seg.max() and w[i] > w[i - k] and w[i] > w[i + k]:
            idx.append(i)
    return idx


def zscore(values: np.ndarray, period: int = 50) -> float:
    v = np.asarray(values, float)
    seg = v[-period:]
    sd = seg.std()
    if sd < 1e-12:
        return 0.0
    return float((seg[-1] - seg.mean()) / sd)


def clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return float(max(lo, min(hi, x)))
