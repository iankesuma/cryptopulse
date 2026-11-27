"""Engine sinyal + prediksi untuk CryptoPulse (data spot Binance)."""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
import urllib.request

import numpy as np

import indicators as I

BINANCE_REST = "https://data-api.binance.vision"
TWELVEDATA_KEY = "a2e73c08d1ee41dcadd63e5cac49f28a"
GOLD_TICK_URL = "https://api.gold-api.com/price/XAU"
HORIZON_MIN = 15

# coin major Binance USDT + XAU/USD (gold spot, sumber Twelve Data + gold-api.com)
INSTRUMENTS = [
    {"symbol": "BTCUSDT", "label": "BTC/USDT", "source": "binance"},
    {"symbol": "ETHUSDT", "label": "ETH/USDT", "source": "binance"},
    {"symbol": "BNBUSDT", "label": "BNB/USDT", "source": "binance"},
    {"symbol": "SOLUSDT", "label": "SOL/USDT", "source": "binance"},
    {"symbol": "XRPUSDT", "label": "XRP/USDT", "source": "binance"},
    {"symbol": "ADAUSDT", "label": "ADA/USDT", "source": "binance"},
    {"symbol": "DOGEUSDT", "label": "DOGE/USDT", "source": "binance"},
    {"symbol": "TRXUSDT", "label": "TRX/USDT", "source": "binance"},
    {"symbol": "AVAXUSDT", "label": "AVAX/USDT", "source": "binance"},
    {"symbol": "LINKUSDT", "label": "LINK/USDT", "source": "binance"},
    {"symbol": "DOTUSDT", "label": "DOT/USDT", "source": "binance"},
    {"symbol": "LTCUSDT", "label": "LTC/USDT", "source": "binance"},
    {"symbol": "BCHUSDT", "label": "BCH/USDT", "source": "binance"},
    {"symbol": "SUIUSDT", "label": "SUI/USDT", "source": "binance"},
    {"symbol": "NEARUSDT", "label": "NEAR/USDT", "source": "binance"},
    {"symbol": "APTUSDT", "label": "APT/USDT", "source": "binance"},
    {"symbol": "ATOMUSDT", "label": "ATOM/USDT", "source": "binance"},
    {"symbol": "UNIUSDT", "label": "UNI/USDT", "source": "binance"},
    {"symbol": "INJUSDT", "label": "INJ/USDT", "source": "binance"},
    {"symbol": "HBARUSDT", "label": "HBAR/USDT", "source": "binance"},
    {"symbol": "XLMUSDT", "label": "XLM/USDT", "source": "binance"},
    {"symbol": "ARBUSDT", "label": "ARB/USDT", "source": "binance"},
    {"symbol": "XAUTUSDT", "label": "XAUT/USDT", "source": "binance"},
]
PAIRS = [i["symbol"] for i in INSTRUMENTS]
LABELS = {i["symbol"]: i["label"] for i in INSTRUMENTS}
SOURCES = {i["symbol"]: i["source"] for i in INSTRUMENTS}
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cryptopulse.db")

# ---------------------------------------------------------------------------
# Hasil AUDIT (14 hari × 12 instrumen, klines 1m, sampel non-overlapping):
#   H5/H15 : semua indikator tren IC NEGATIF (hit 45-47%) → pasar mean-reverting.
#            Versi kontrarian cuma 51% (edge ~+0.004%, di bawah biaya 0.10%).
#   H30    : campuran, IC kecil positif.
#   H60    : semua positif; terkuat MACD histogram (+0.098) dan ATR-momentum (+0.069)
#            di 12/12 instrumen. Ensemble IC-weighted: hit 51.2%, edge +0.109%/trade.
# LightGBM walk-forward: AUC 0.517 (H15) / 0.499 (H60) → tanpa skill, jadi info-only.
# Tabel di bawah dipakai langsung sebagai prior: bobot = |IC| × 12, arah = sign(IC).
IC_TABLE = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "ic_table.json"), encoding="utf-8"))

DEFAULT_HORIZON = 60
HORIZON_MIN = DEFAULT_HORIZON
GATE_THRESHOLD = {5: 0.25, 15: 0.22, 30: 0.18, 60: 0.12}   # ambang |skor| per horizon
MIN_IC = 0.010          # di bawah ini dianggap tidak informatif → info-only
IC_WEIGHT_SCALE = 12.0  # bobot = |IC| × 12 (cap 1.8)
K_SHRINK = 1200

# ringkasan backtest untuk ditampilkan di UI (bukan angka live)
BACKTEST = {
    5:  {"hit": 46.3, "edge": -0.006, "n": 46588, "mode": "momentum"},
    15: {"hit": 51.2, "edge": 0.004, "n": 15525, "mode": "kontrarian"},
    30: {"hit": 48.5, "edge": 0.028, "n": 7768, "mode": "momentum"},
    60: {"hit": 51.6, "edge": 0.109, "n": 3837, "mode": "macd+atr-momentum"},
}
FEE_PCT = 0.10


def set_horizon(minutes: int) -> int:
    """Ganti horizon global; cache kalibrasi & model di-reset oleh pemanggil."""
    global HORIZON_MIN
    m = int(minutes)
    HORIZON_MIN = m if str(m) in IC_TABLE else DEFAULT_HORIZON
    return HORIZON_MIN


def ic_prior(key: str) -> float:
    return float(IC_TABLE.get(str(HORIZON_MIN), {}).get(key, 0.0))

CATEGORY = {
    "ema_ribbon": "Tren",
    "supertrend": "Tren/Vol",
    "rsi_div": "Momentum",
    "bollinger": "Momentum",
    "vwap": "Order Flow",
    "cvd_obv": "Order Flow",
    "funding_oi": "Derivatif",
    "ob_imbalance": "Mikro",
    "ml": "ML",
    "sentiment": "Alternatif",
    "macd_hist": "Momentum",
    "atr_mom": "Tren/Vol",
}

LABEL = {
    "ema_ribbon": "EMA RIBBON",
    "supertrend": "SUPERTREND",
    "rsi_div": "RSI DIVERGENCE",
    "bollinger": "BOLLINGER BANDS",
    "vwap": "VWAP",
    "cvd_obv": "CVD / OBV",
    "funding_oi": "FUNDING & OI",
    "ob_imbalance": "ORDER BOOK IMBALANCE",
    "ml": "LIGHTGBM MODEL",
    "sentiment": "SENTIMENT INDEX",
    "macd_hist": "MACD HISTOGRAM",
    "atr_mom": "ATR MOMENTUM",
}


_SENTIMENT: dict = {"value": None, "label": "n/a", "ts": 0.0}


def refresh_sentiment(force: bool = False) -> dict:
    """Fear & Greed global — satu request untuk semua instrumen."""
    if not force and _SENTIMENT["ts"] and time.time() - _SENTIMENT["ts"] < 600:
        return _SENTIMENT
    try:
        d = http_json("https://api.alternative.me/fng/?limit=1")["data"][0]
        _SENTIMENT.update({"value": int(d["value"]), "label": d["value_classification"],
                           "ts": time.time()})
    except Exception:  # noqa: BLE001
        _SENTIMENT["ts"] = _SENTIMENT["ts"] or time.time()
    return _SENTIMENT


def price_decimals(p: float) -> int:
    """Jumlah desimal wajar untuk harga instrumen (DOGE butuh 5, BTC cukup 2)."""
    p = abs(float(p or 0))
    if p >= 100:
        return 2
    if p >= 1:
        return 4
    if p >= 0.01:
        return 5
    if p >= 0.001:
        return 6
    return 8


def _dt_to_ms(dt: str) -> int:
    import datetime as _dt
    d = _dt.datetime.strptime(dt[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=_dt.timezone.utc)
    return int(d.timestamp() * 1000)


def http_json(url: str, timeout: float = 10.0):
    req = urllib.request.Request(url, headers={"User-Agent": "CryptoPulse/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ---------------------------------------------------------------- database
def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute(
        """CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, created_ms INTEGER, horizon_min INTEGER,
            price REAL, target REAL, lo REAL, hi REAL,
            confidence INTEGER, direction TEXT, score REAL,
            resolved_price REAL, resolved_ms INTEGER, hit INTEGER
        )"""
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_pred_symbol ON predictions(symbol, created_ms)")
    con.commit()
    return con


# ---------------------------------------------------------------- ML model
class MLModel:
    """LightGBM classifier: arah 15 menit ke depan dari fitur 1m."""

    def __init__(self):
        self.model = None
        self.trained_at = 0.0
        self.prob = None
        self.train_n = 0
        self.status = "idle"
        self.last_error = None

    def _features(self, o, h, l, c, v, tb):
        c = np.asarray(c, float)
        o = np.asarray(o, float)
        h = np.asarray(h, float)
        l = np.asarray(l, float)
        v = np.asarray(v, float)
        tb = np.asarray(tb, float)
        ret = np.diff(c, prepend=c[0]) / np.where(c > 0, c, 1)
        ema9, ema21, ema55 = I.ema(c, 9), I.ema(c, 21), I.ema(c, 55)
        rsi14 = I.rsi(c, 14)
        mid, up, lo, pb, bw = I.bollinger(c, 20, 2.0)
        a = I.atr(h, l, c, 14)
        ob = I.obv(c, v)
        rows = []
        for i in range(60, len(c)):
            body = (c[i] - o[i]) / max(h[i] - l[i], 1e-9)
            vol_z = I.zscore(v[i - 59:i + 1], 30)
            tbr = tb[i] / max(v[i], 1e-9)
            rows.append([
                ret[i], ret[i - 1], ret[i - 2], ret[i - 3], ret[i - 5], ret[i - 14],
                (ema9[i] - ema21[i]) / max(c[i], 1e-9) * 100,
                (ema21[i] - ema55[i]) / max(c[i], 1e-9) * 100,
                rsi14[i] / 100.0,
                pb[i], bw[i] * 100,
                a[i] / max(c[i], 1e-9) * 100,
                I.linreg_slope(ob[i - 19:i + 1]) / max(v[i - 19:i + 1].mean(), 1e-9),
                body, vol_z, tbr,
            ])
        return np.array(rows, float)

    def predict(self, o, h, l, c, v, tb, force: bool = False):
        now = time.time()
        if not force and self.model is not None and now - self.trained_at < 240:
            return self.prob
        try:
            import lightgbm as lgb

            X = self._features(o, h, l, c, v, tb)
            c_ex = np.asarray(c, float)
            fwd = np.array([c_ex[i + HORIZON_MIN] / c_ex[i] - 1 if i + HORIZON_MIN < len(c_ex) else np.nan
                            for i in range(60, len(c_ex))])
            mask = ~np.isnan(fwd)
            X, fwd = X[mask], fwd[mask]
            if len(X) < 120:
                self.status = "data kurang"
                return self.prob
            y = (fwd > 0).astype(int)
            if y.sum() in (0, len(y)):
                self.status = "label konstan"
                return self.prob
            Xtr, ytr = X[:-1], y[:-1]
            params = {
                "objective": "binary", "metric": "auc",
                "learning_rate": 0.06, "num_leaves": 7, "min_data_in_leaf": 25,
                "feature_fraction": 0.9, "bagging_fraction": 0.85, "bagging_freq": 1,
                "lambda_l2": 1.0, "verbose": -1, "num_threads": 2,
            }
            booster = lgb.train(params, lgb.Dataset(Xtr, label=ytr), num_boost_round=90)
            self.model = booster
            self.trained_at = now
            self.train_n = int(len(Xtr))
            self.prob = float(booster.predict(X[-1:])[0])
            self.status = "live"
            self.last_error = None
        except Exception as e:  # noqa: BLE001
            self.last_error = f"{type(e).__name__}: {e}"
            self.status = "error"
        return self.prob


# ---------------------------------------------------------------- engine
class SymbolState:
    def __init__(self, symbol: str, source: str = "binance"):
        self.symbol = symbol
        self.source = source
        self.klines = []           # list of dict
        self.price = None
        self.price_ts = 0
        self.ticker = {}
        self.depth = {"bids": [], "asks": []}
        self.sentiment = None      # {"value": int, "label": str, "ts": float}
        self.ml = MLModel()
        self.state = None
        self.last_build = 0.0
        self.ic = {}          # IC per aturan hasil kalibrasi
        self.ic_at = 0.0

    # -- data
    def load_klines(self, limit: int = 1000):
        if self.source == "gold":
            return self.load_klines_gold(limit)
        raw = http_json(f"{BINANCE_REST}/api/v3/klines?symbol={self.symbol}&interval=1m&limit={limit}")
        self.klines = [
            {
                "t": k[0], "o": float(k[1]), "h": float(k[2]), "l": float(k[3]),
                "c": float(k[4]), "v": float(k[5]), "q": float(k[7]),
                "n": int(k[8]), "tb": float(k[9]),
            }
            for k in raw
        ]
        if self.klines:
            self.price = self.klines[-1]["c"]
            self.price_ts = int(time.time() * 1000)

    def load_klines_gold(self, limit: int = 1000):
        """OHLC 1m XAU/USD dari Twelve Data (tanpa volume asli → v=1 per tick)."""
        n = min(max(limit, 120), 480)
        url = (f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval=1min"
               f"&outputsize={n}&timezone=UTC&order=ASC&apikey={TWELVEDATA_KEY}")
        d = http_json(url)
        if d.get("status") == "error":
            raise RuntimeError(f"twelvedata: {d.get('message')}")
        rows = []
        for v in d.get("values", []):
            ts = _dt_to_ms(v["datetime"])
            o, h, l, c = (float(v["open"]), float(v["high"]), float(v["low"]), float(v["close"]))
            rows.append({"t": ts, "o": o, "h": h, "l": l, "c": c,
                         "v": 1.0, "q": c, "n": 1, "tb": 0.5})
        if not rows:
            return
        rows.sort(key=lambda r: r["t"])
        self.klines = rows[-1200:]
        self.price = rows[-1]["c"]
        self.price_ts = int(time.time() * 1000)

    def add_tick(self, price: float, ts_ms: int | None = None):
        """Bangun candle 1m berjalan dari tick harga (untuk instrumen tanpa stream)."""
        if not price or price <= 0:
            return
        ts = ts_ms or int(time.time() * 1000)
        minute = ts // 60000 * 60000
        self.price = price
        self.price_ts = ts
        if not self.klines:
            self.klines.append({"t": minute, "o": price, "h": price, "l": price, "c": price,
                                "v": 1.0, "q": price, "n": 1, "tb": 0.5})
            return
        last = self.klines[-1]
        if last["t"] == minute:
            last["c"] = price
            last["h"] = max(last["h"], price)
            last["l"] = min(last["l"], price)
            last["q"] = price
            last["v"] = float(last["v"]) + 1.0
            last["n"] = int(last["n"]) + 1
            last["tb"] = last["v"] * 0.5
        elif minute > last["t"]:
            self.klines.append({"t": minute, "o": last["c"], "h": price, "l": min(last["c"], price),
                                "c": price, "v": 1.0, "q": price, "n": 1, "tb": 0.5})
            if len(self.klines) > 1200:
                self.klines = self.klines[-1000:]

    def load_ticker(self):
        if self.source == "gold":
            k = self.klines
            if not k:
                return
            last = k[-1]["c"]
            window = k[-1440:] if len(k) > 1440 else k
            ref = window[0]["o"]
            self.ticker = {
                "change24h": (last / ref - 1) * 100 if ref else 0.0,
                "change24h_abs": last - ref,
                "high24h": max(r["h"] for r in window),
                "low24h": min(r["l"] for r in window),
                "vol24h": None,
                "quote24h": None,
                "lastPrice": last,
            }
            return
        t = http_json(f"{BINANCE_REST}/api/v3/ticker/24hr?symbol={self.symbol}")
        self.ticker = {
            "change24h": float(t.get("priceChangePercent", 0)),
            "change24h_abs": float(t.get("priceChange", 0)),
            "high24h": float(t.get("highPrice", 0)),
            "low24h": float(t.get("lowPrice", 0)),
            "vol24h": float(t.get("volume", 0)),
            "quote24h": float(t.get("quoteVolume", 0)),
            "lastPrice": float(t.get("lastPrice", 0)),
        }
        if not self.price:
            self.price = self.ticker["lastPrice"]

    def load_sentiment(self, force: bool = False):
        self.sentiment = refresh_sentiment(force)

    def patch_kline(self, k: dict):
        """Update candle berjalan dari stream kline."""
        ts = k["t"]
        row = {
            "t": ts, "o": float(k["o"]), "h": float(k["h"]), "l": float(k["l"]),
            "c": float(k["c"]), "v": float(k["v"]), "q": float(k["q"]),
            "n": int(k["n"]), "tb": float(k["V"]),
        }
        self.price = row["c"]
        self.price_ts = int(time.time() * 1000)
        if self.klines and self.klines[-1]["t"] == ts:
            self.klines[-1] = row
        elif not self.klines or ts > self.klines[-1]["t"]:
            self.klines.append(row)
            if len(self.klines) > 1200:
                self.klines = self.klines[-1000:]

    def set_depth(self, bids, asks):
        self.depth = {"bids": bids[:20], "asks": asks[:20]}

    # -- kalibrasi IC per pair
    def calibrate(self, o, h, l, c, v, tb, bars: int = 600):
        """Ukur IC (korelasi skor vs return 15 bar) tiap aturan price-based."""
        n = len(c)
        if n < 300:
            return
        sl = slice(max(0, n - bars), n)
        oo, hh, ll, cc, vv, tt = o[sl], h[sl], l[sl], c[sl], v[sl], tb[sl]
        m = len(cc)
        if m < 300:
            return
        fwd = np.full(m, np.nan)
        fwd[:-HORIZON_MIN] = (cc[HORIZON_MIN:] / cc[:-HORIZON_MIN] - 1) * 100.0

        sc = {}
        e9, e21, e55 = I.ema(cc, 9), I.ema(cc, 21), I.ema(cc, 55)
        sc["ema_ribbon"] = np.where((e9 > e21) & (e21 > e55), 0.6,
                                    np.where((e9 < e21) & (e21 < e55), -0.6, 0.0))

        tp = (hh + ll + cc) / 3.0
        vol_sum = I.sma(vv, 240)
        if vv.sum() > 0:
            vw = I.sma(tp * vv, 240) / np.maximum(vol_sum, 1e-12)
        else:
            vw = I.sma(tp, 240)
        dev = np.nan_to_num((cc - vw) / np.where(vw > 0, vw, 1) * 100.0, nan=0.0)
        sc["vwap"] = np.clip(dev / 2.0, -0.7, 0.7)

        delta = 2 * tt - vv
        cvd = np.cumsum(delta)
        ob = I.obv(cc, vv)
        slp = np.zeros(m)
        for i in range(60, m, 3):          # stride 3: cukup untuk estimasi IC, 3x lebih cepat
            vm = max(vv[i - 59:i + 1].mean(), 1e-9)
            slp[i] = (0.6 * I.linreg_slope(cvd[i - 59:i + 1]) / vm
                      + 0.4 * I.linreg_slope(ob[i - 59:i + 1]) / vm)
        sc["cvd_obv"] = np.clip(slp * 0.55, -0.8, 0.8)

        r = I.rsi(cc, 14)
        sc["rsi_div"] = np.clip((r - 50) / 60.0, -0.3, 0.3)
        _mid, _up, _lo, pb, _bw = I.bollinger(cc, 20, 2.0)
        sc["bollinger"] = np.clip(np.nan_to_num((pb - 0.5) * 0.5, nan=0.0), -0.3, 0.3)

        ic = {}
        warm = 170
        for k, arr in sc.items():
            ss, ff = arr[warm:-HORIZON_MIN], fwd[warm:-HORIZON_MIN]
            ok = np.isfinite(ss) & np.isfinite(ff)
            if ok.sum() < 80 or ss[ok].std() < 1e-9:
                ic[k] = ic_prior(k)
                continue
            raw = float(np.corrcoef(ss[ok], ff[ok])[0, 1])
            r = ok.sum() / (ok.sum() + K_SHRINK)          # shrinkage ke prior global
            ic[k] = (1 - r) * ic_prior(k) + r * raw
        self.ic = ic
        self.ic_at = time.time()

    def rule_weight(self, key: str):
        """Arah dari IC audit; besar bobot diskalakan IC pair (tanpa boleh membalik arah)."""
        ic = ic_prior(key)
        if abs(ic) < MIN_IC:
            return 0.0, "info", 0.0
        orient = 1.0 if ic > 0 else -1.0
        w = min(abs(ic) * IC_WEIGHT_SCALE, 1.8)
        pair_ic = float(self.ic.get(key, 0.0)) if (key in self.ic and self.ic_at) else None
        if pair_ic is not None:
            if pair_ic * ic < 0:                     # pair tidak konfirmasi → bobot dikecilkan
                w *= 0.35
            else:
                w *= float(I.clamp(0.7 + 3 * abs(pair_ic), 0.7, 1.3))
        return round(float(w), 2), "vote", orient

    # -- signals
    def build_state(self, force_ml: bool = False):
        if not self.klines:
            return None
        k = self.klines
        o = np.array([x["o"] for x in k])
        h = np.array([x["h"] for x in k])
        l = np.array([x["l"] for x in k])
        c = np.array([x["c"] for x in k])
        v = np.array([x["v"] for x in k])
        tb = np.array([x["tb"] for x in k])
        price = float(self.price or c[-1])
        pdec = price_decimals(price)
        fp = lambda v, d=None: f"{v:,.{pdec if d is None else d}f}"  # noqa: E731
        pp = 2 if price >= 1 else 3
        sig = []

        def add(key, status, value, score, note=""):
            sig.append({
                "key": key, "name": LABEL[key], "category": CATEGORY[key],
                "status": status, "value": value, "score": round(float(score), 3), "note": note,
            })

        # 1. EMA Ribbon
        e9, e21, e55 = I.ema(c, 9), I.ema(c, 21), I.ema(c, 55)
        spread = (e9[-1] - e55[-1]) / price * 100
        if e9[-1] > e21[-1] > e55[-1] and price > e21[-1]:
            st, sc = "BULL", I.clamp(0.45 + spread / 1.2, 0.2, 1.0)
        elif e9[-1] < e21[-1] < e55[-1] and price < e21[-1]:
            st, sc = "BEAR", I.clamp(0.45 + spread / 1.2, -1.0, -0.2)
        else:
            st, sc = "NEUTRAL", I.clamp(spread * 1.5, -0.35, 0.35)
        add("ema_ribbon", st, f"9/21/55 · {spread:+.2f}%", sc)

        # 2. SuperTrend
        stl, direction = I.supertrend(h, l, c, 10, 3.0)
        dist = (price - stl[-1]) / price * 100
        if direction[-1] > 0:
            st, sc = "BULL", I.clamp(0.5 + abs(dist) / 1.5, 0.25, 1.0)
            val = f"line {fp(stl[-1])} · {dist:+.{pp}f}%"
        else:
            st, sc = "BEAR", I.clamp(-0.5 - abs(dist) / 1.5, -1.0, -0.25)
            val = f"line {fp(stl[-1])} · {dist:+.{pp}f}%"
        add("supertrend", st, val, sc)

        # 3. RSI Divergence
        r = I.rsi(c, 14)
        win = 90
        lows = I.pivot_points(c[-win:], "low")
        highs = I.pivot_points(c[-win:], "high")
        rw = r[-win:]
        st, sc, val = "NEUTRAL", 0.0, f"RSI {r[-1]:.1f}"
        if len(lows) >= 2:
            i1, i2 = lows[-2], lows[-1]
            if c[-win:][i2] < c[-win:][i1] and rw[i2] > rw[i1] + 1.5:
                st, sc, val = "BULL", 0.6, f"bullish div · RSI {r[-1]:.1f}"
        if len(highs) >= 2:
            i1, i2 = highs[-2], highs[-1]
            if c[-win:][i2] > c[-win:][i1] and rw[i2] < rw[i1] - 1.5:
                st, sc, val = "BEAR", -0.6, f"bearish div · RSI {r[-1]:.1f}"
        if st == "NEUTRAL":
            sc = I.clamp((r[-1] - 50) / 60.0, -0.25, 0.25)
        add("rsi_div", st, val, sc)

        # 4. Bollinger
        mid, up, lo_, pb, bw = I.bollinger(c, 20, 2.0)
        bw_now, bw_prev = bw[-1], np.nanmean(bw[-30:-5])
        squeeze = bw_now < bw_prev * 0.8
        if pb[-1] > 1.0:
            st, sc = "BEAR", -0.35
        elif pb[-1] < 0.0:
            st, sc = "BULL", 0.35
        else:
            st, sc = "NEUTRAL", I.clamp((pb[-1] - 0.5) * 0.5, -0.25, 0.25)
        val = f"%B {pb[-1]:.2f} · width {bw_now*100:,.{pp}f}%" + (" · squeeze" if squeeze else "")
        add("bollinger", st, val, sc)

        # 11. MACD histogram (12/26/9) dinormalisasi ATR — IC terkuat di horizon 60m
        macd_line = I.ema(c, 12) - I.ema(c, 26)
        macd_sig = I.ema(macd_line, 9)
        a14 = I.atr(h, l, c, 14)[-1]
        hist = (macd_line[-1] - macd_sig[-1]) / max(a14, 1e-9)
        sc = I.clamp(hist * 1.5, -0.8, 0.8)
        st = "BULL" if sc > 0.15 else "BEAR" if sc < -0.15 else "NEUTRAL"
        add("macd_hist", st, f"hist {hist:+.2f}×ATR", sc)

        # 12. ATR momentum: return 10 bar / (3 × ATR%)
        ret10 = (c[-1] / c[-11] - 1) * 100 if c.size > 11 else 0.0
        atr_pct_now = a14 / price * 100
        amom = ret10 / max(atr_pct_now * 3, 1e-9)
        sc = I.clamp(amom, -0.8, 0.8)
        st = "BULL" if sc > 0.2 else "BEAR" if sc < -0.2 else "NEUTRAL"
        add("atr_mom", st, f"mom {ret10:+.2f}% / ATR {atr_pct_now:.2f}%", sc)

        # 5. VWAP sesi (UTC)
        day_start = 0
        utc_midnight = (int(time.time()) // 86400) * 86400 * 1000
        for i, row in enumerate(k):
            if row["t"] >= utc_midnight:
                day_start = i
                break
        vw = I.vwap_session(h, l, c, v, day_start)
        dev = (price - vw) / vw * 100
        if price > vw:
            st, sc = "BULL", I.clamp(0.3 + dev / 2.0, 0.15, 0.9)
        else:
            st, sc = "BEAR", I.clamp(-0.3 + dev / 2.0, -0.9, -0.15)
        add("vwap", st, f"{fp(vw)} · {dev:+.{pp}f}%", sc)

        # 6. CVD / OBV
        delta = 2 * tb - v
        cvd = np.cumsum(delta)
        cvd_slope = I.linreg_slope(cvd[-60:]) / max(v[-60:].mean(), 1e-9)
        ob = I.obv(c, v)
        ob_slope = I.linreg_slope(ob[-60:]) / max(v[-60:].mean(), 1e-9)
        mix = 0.6 * cvd_slope + 0.4 * ob_slope
        taker_ratio = tb[-30:].sum() / max(v[-30:].sum(), 1e-9)
        sc = I.clamp(mix * 0.55 + (taker_ratio - 0.5) * 2.2, -1, 1)
        st = "BULL" if sc > 0.18 else "BEAR" if sc < -0.18 else "NEUTRAL"
        add("cvd_obv", st, f"taker {taker_ratio*100:.1f}% · slope {mix:+.2f}", sc)

        # 7. Funding & OI (proxy dari data spot — endpoint futures diblokir)
        if self.source != "binance":
            add("funding_oi", "NEUTRAL", "n/a · tanpa futures", 0.0, "spot only")
        else:
            fund_proxy = (taker_ratio - 0.5) * 0.02            # estimasi % per 8 jam
            q = np.array([x["q"] for x in k])
            flow = (q[-30:].mean() / max(q[-150:-30].mean(), 1e-9) - 1) * 100
            sc = I.clamp(fund_proxy / 0.01 * 0.4 + flow / 40 * 0.6, -1, 1)
            if abs(fund_proxy) > 0.012 and flow > 15:          # crowded → contrarian
                sc = -sc * 0.6
            st = "BULL" if sc > 0.2 else "BEAR" if sc < -0.2 else "NEUTRAL"
            add("funding_oi", st, f"fund {fund_proxy:+.4f}% · flow {flow:+.1f}%", sc,
                "proxy spot (futures diblokir)")

        # 8. Order book imbalance
        bids, asks = self.depth.get("bids", []), self.depth.get("asks", [])
        if bids and asks:
            bq = sum(float(x[1]) for x in bids)
            aq = sum(float(x[1]) for x in asks)
            imb = (bq - aq) / max(bq + aq, 1e-9)
            sc = I.clamp(imb * 2.2, -1, 1)
            st = "BULL" if sc > 0.18 else "BEAR" if sc < -0.18 else "NEUTRAL"
            val = f"bid {bq/(bq+aq)*100:.1f}% · {imb*100:+.1f}%"
        else:
            st, sc = "NEUTRAL", 0.0
            val = "menunggu depth" if self.source == "binance" else "n/a · tanpa order book"
        add("ob_imbalance", st, val, sc)

        # 9. LightGBM
        prob = self.ml.predict(o, h, l, c, v, tb, force=force_ml)
        if prob is None:
            st, sc, val = "NEUTRAL", 0.0, self.ml.status
        else:
            sc = I.clamp((prob - 0.5) * 2.6, -1, 1)
            st = "BULL" if prob > 0.56 else "BEAR" if prob < 0.44 else "NEUTRAL"
            val = f"P(up) {prob*100:.1f}% · n={self.ml.train_n}"
        add("ml", st, val, sc)

        # 10. Sentiment (Fear & Greed) — ekstrem dipakai contrarian
        s = self.sentiment or refresh_sentiment()
        fng = s.get("value")
        if fng is None:
            st, sc, val = "NEUTRAL", 0.0, "n/a"
        elif fng <= 22:
            st, sc = "BULL", 0.3
            val = f"{fng} · {s.get('label','')} (contrarian)"
        elif fng >= 78:
            st, sc = "BEAR", -0.3
            val = f"{fng} · {s.get('label','')} (contrarian)"
        else:
            sc = I.clamp((fng - 50) / 50.0 * 0.55, -0.5, 0.5)
            st = "BULL" if fng >= 58 else "BEAR" if fng <= 42 else "NEUTRAL"
            val = f"{fng} · {s.get('label','')}"
        add("sentiment", st, val, sc)

        # -- kalibrasi IC per pair (refresh 30 menit)
        if not self.ic or time.time() - self.ic_at > 1800:
            self.calibrate(o, h, l, c, v, tb)

        # -- filter rezim: tren 15m & 1h searah + volatilitas wajar
        a15 = I.atr(h, l, c, 14)[-1]
        e15 = I.ema(c[::15] if len(c) > 400 else c, 21)
        e1h = I.ema(c[::60] if len(c) > 400 else c, 21)
        trend15 = 1 if c[-1] > e15[-1] else -1
        trend1h = 1 if c[-1] > e1h[-1] else -1
        atr_pct = a15 / price * 100
        vol_ok = 0.005 < atr_pct < 0.9
        macro_pass = trend15 == trend1h and vol_ok

        # -- bobot voter: |IC| × skala, arah = sign(IC) horizon aktif
        for s_ in sig:
            w, mode, orient = self.rule_weight(s_["key"])
            s_["weight"] = round(float(w), 2)
            s_["mode"] = mode
            s_["orient"] = int(orient)
            s_["ic"] = round(ic_prior(s_["key"]), 3)

        voters = [s_ for s_ in sig if s_["mode"] == "vote" and s_["weight"] > 0]
        tot_w = sum(s_["weight"] for s_ in voters) or 1.0
        S = sum(s_["weight"] * s_["orient"] * s_["score"] for s_ in voters) / tot_w

        bull = sum(1 for s_ in sig if s_["status"] == "BULL")
        bear = sum(1 for s_ in sig if s_["status"] == "BEAR")
        neutral = len(sig) - bull - bear

        # -- gate: ≥2 dari 3 keluarga (tren / momentum / flow) sepakat searah S
        fam_of = {
            "ema_ribbon": "tren", "supertrend": "tren", "adx_trend": "tren",
            "atr_mom": "tren",
            "rsi_div": "momentum", "bollinger": "momentum", "stoch": "momentum",
            "macd_hist": "momentum",
            "cvd_obv": "flow", "vwap": "flow", "vol_surge": "flow",
            "donchian": "flow", "ob_imbalance": "flow",
        }
        buckets: dict[str, list] = {}
        for s_ in voters:
            fam = fam_of.get(s_["key"])
            if fam:
                buckets.setdefault(fam, []).append(
                    (s_["weight"], s_["orient"] * s_["score"]))
        fam_score = {f: sum(w * sc for w, sc in vals) / max(sum(w for w, _ in vals), 1e-9)
                     for f, vals in buckets.items()}
        cats_ok = sum(1 for cs in fam_score.values() if abs(cs) > 0.05 and (cs > 0) == (S > 0))

        sigma = a15 * math.sqrt(HORIZON_MIN)
        expected = S * sigma * 0.9
        target = price + expected
        vol_factor = I.clamp(atr_pct / 0.12, 0.7, 1.8)
        band = sigma * (1.05 + 0.45 * (1 - abs(S))) * vol_factor

        ic_q = I.clamp(sum(abs(s_["ic"]) * s_["weight"] for s_ in voters) / tot_w / 0.08, 0.0, 1.0)
        conf = 34 + 26 * abs(S) + 18 * (cats_ok / 3.0) + 8 * ic_q
        conf = int(max(30, min(86, round(conf))))

        thr = GATE_THRESHOLD.get(HORIZON_MIN, 0.12)
        strength_ok = abs(S) > thr
        gate_ok = cats_ok >= 2 and (macro_pass or abs(S) >= 0.35)
        if strength_ok and gate_ok:
            direction, verdict = (("UP", "LONG — Sinyal Beli") if S > 0
                                  else ("DOWN", "SHORT — Sinyal Jual"))
            reason = f"skor {S:+.2f} · {cats_ok}/3 keluarga sepakat"
        else:
            direction, verdict = "WAIT", "WAIT — Menunggu Sinyal"
            if not strength_ok:
                reason = f"skor {S:+.2f} < ambang {thr:.2f} (horizon {HORIZON_MIN}m)"
            elif cats_ok < 2:
                reason = f"keluarga konflik ({cats_ok}/3 sepakat)"
            else:
                reason = "filter rezim gagal" + ("" if vol_ok else " · volatilitas ekstrem")

        # normalisasi & rapikan
        state = {
            "symbol": self.symbol,
            "label": LABELS.get(self.symbol, self.symbol),
            "source_kind": self.source,
            "pairs": PAIRS,
            "instruments": INSTRUMENTS,
            "price": round(float(price), pdec),
            "price_raw": float(price),
            "change24h": float(self.ticker.get("change24h") or 0.0),
            "change24h_abs": float(self.ticker.get("change24h_abs") or 0.0),
            "high24h": float(self.ticker.get("high24h") or 0.0),
            "low24h": float(self.ticker.get("low24h") or 0.0),
            "vol24h": self.ticker.get("vol24h"),
            "signals": sig,
            "summary": {
                "bull": bull, "neutral": neutral, "bear": bear,
                "score": round(float(S), 4), "verdict": verdict, "direction": direction,
                "cats_ok": int(cats_ok),
                "cats": {f: round(float(fam_score.get(f, 0)), 3)
                         for f in ("tren", "momentum", "flow")},
                "reason": reason,
                "voters": len(voters),
                "horizon_min": HORIZON_MIN,
                "gate_threshold": thr,
                "backtest": BACKTEST.get(HORIZON_MIN, {}),
                "fee_pct": FEE_PCT,
            },
            "prediction": {
                "horizon": f"{HORIZON_MIN}M",
                "target": round(float(target), pdec),
                "lo": round(float(target - band), pdec),
                "hi": round(float(target + band), pdec),
                "exp_move_pct": round(float(expected / price * 100), 3),
                "confidence": conf,
                "direction": direction,
                "decimals": pdec,
            },
            "macro": {
                "status": "PASS" if macro_pass else "FAIL",
                "note": f"15m {'↑' if trend15>0 else '↓'} · 1h {'↑' if trend1h>0 else '↓'} · ATR {atr_pct:.3f}%",
            },
            "ml": {"status": self.ml.status,
                   "prob": (float(prob) if prob is not None else None), "n": self.ml.train_n,
                   "age_s": int(time.time() - self.ml.trained_at) if self.ml.trained_at else None,
                   "error": self.ml.last_error},
            "ts": int(time.time() * 1000),
            "source": "Binance Spot · data-api.binance.vision",
        }
        self.state = state
        self.last_build = time.time()
        return state

    # -- chart data
    def chart(self, bars: int = 180):
        k = self.klines[-bars:]
        return [[x["t"], x["o"], x["h"], x["l"], x["c"], x["v"]] for x in k]


# ---------------------------------------------------------------- prediction log
def log_prediction(con, state):
    # hanya simpan prediksi yang punya arah tegas (WAIT bukan prediksi)
    if state["prediction"]["direction"] == "WAIT":
        return
    now_ms = state["ts"]
    window = now_ms // (HORIZON_MIN * 60 * 1000)
    row = con.execute(
        "SELECT id FROM predictions WHERE symbol=? AND created_ms BETWEEN ? AND ?",
        (state["symbol"], window * HORIZON_MIN * 60 * 1000, (window + 1) * HORIZON_MIN * 60 * 1000),
    ).fetchone()
    if row:
        return
    p = state["prediction"]
    con.execute(
        "INSERT INTO predictions (symbol, created_ms, horizon_min, price, target, lo, hi, confidence, direction, score)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (state["symbol"], now_ms, HORIZON_MIN, state["price"], p["target"], p["lo"], p["hi"],
         p["confidence"], p["direction"], state["summary"]["score"]),
    )
    con.commit()


def resolve_predictions(con, states: dict):
    now_ms = int(time.time() * 1000)
    rows = con.execute(
        "SELECT id, symbol, created_ms, price, target, direction FROM predictions WHERE hit IS NULL"
    ).fetchall()
    for pid, symbol, created_ms, price, target, direction in rows:
        if now_ms - created_ms < HORIZON_MIN * 60 * 1000 + 5000:
            continue
        st = states.get(symbol)
        if not st or not st.klines:
            continue
        cutoff = created_ms + HORIZON_MIN * 60 * 1000
        resolved = None
        for row in st.klines:
            if row["t"] >= cutoff:
                resolved = row["c"]
                break
        if resolved is None and st.klines:
            resolved = st.klines[-1]["c"]
        hit = 1 if (resolved - price) * (target - price) > 0 else 0
        con.execute("UPDATE predictions SET resolved_price=?, resolved_ms=?, hit=? WHERE id=?",
                    (resolved, now_ms, hit, pid))
    con.commit()


def stats(con, symbol: str):
    total, hits = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(hit),0) FROM predictions"
        " WHERE symbol=? AND hit IS NOT NULL AND direction != 'WAIT'",
        (symbol,),
    ).fetchone()
    pending = con.execute(
        "SELECT COUNT(*) FROM predictions WHERE symbol=? AND hit IS NULL AND direction != 'WAIT'",
        (symbol,),
    ).fetchone()[0]
    recent = con.execute(
        "SELECT created_ms, price, target, direction, hit, resolved_price FROM predictions"
        " WHERE symbol=? AND hit IS NOT NULL AND direction != 'WAIT'"
        " ORDER BY created_ms DESC LIMIT 8", (symbol,)
    ).fetchall()
    return {
        "total": total, "hits": hits,
        "accuracy": round(hits / total * 100, 1) if total else None,
        "pending": pending,
        "recent": [{"ts": r[0], "price": r[1], "target": r[2], "direction": r[3],
                    "hit": bool(r[4]), "resolved": r[5]} for r in recent],
    }
