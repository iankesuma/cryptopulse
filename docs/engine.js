/* CryptoPulse static engine — port 1:1 dari engine.py (tanpa server, jalan di browser).
   Semua angka dihitung dari data Binance publik yang di-fetch langsung. */

export const INSTRUMENTS = [
  { symbol: "BTCUSDT", label: "BTC/USDT" }, { symbol: "ETHUSDT", label: "ETH/USDT" },
  { symbol: "BNBUSDT", label: "BNB/USDT" }, { symbol: "SOLUSDT", label: "SOL/USDT" },
  { symbol: "XRPUSDT", label: "XRP/USDT" }, { symbol: "ADAUSDT", label: "ADA/USDT" },
  { symbol: "DOGEUSDT", label: "DOGE/USDT" }, { symbol: "TRXUSDT", label: "TRX/USDT" },
  { symbol: "AVAXUSDT", label: "AVAX/USDT" }, { symbol: "LINKUSDT", label: "LINK/USDT" },
  { symbol: "DOTUSDT", label: "DOT/USDT" }, { symbol: "LTCUSDT", label: "LTC/USDT" },
  { symbol: "BCHUSDT", label: "BCH/USDT" }, { symbol: "SUIUSDT", label: "SUI/USDT" },
  { symbol: "NEARUSDT", label: "NEAR/USDT" }, { symbol: "APTUSDT", label: "APT/USDT" },
  { symbol: "ATOMUSDT", label: "ATOM/USDT" }, { symbol: "UNIUSDT", label: "UNI/USDT" },
  { symbol: "INJUSDT", label: "INJ/USDT" }, { symbol: "HBARUSDT", label: "HBAR/USDT" },
  { symbol: "XLMUSDT", label: "XLM/USDT" }, { symbol: "ARBUSDT", label: "ARB/USDT" },
  { symbol: "XAUTUSDT", label: "XAUT/USDT" },
];

const CATEGORY = {
  ema_ribbon: "Tren", supertrend: "Tren/Vol", rsi_div: "Momentum", bollinger: "Momentum",
  vwap: "Order Flow", cvd_obv: "Order Flow", funding_oi: "Derivatif",
  ob_imbalance: "Mikro", ml: "ML", sentiment: "Alternatif",
  macd_hist: "Momentum", atr_mom: "Tren/Vol",
};
const LABEL = {
  ema_ribbon: "EMA RIBBON", supertrend: "SUPERTREND", rsi_div: "RSI DIVERGENCE",
  bollinger: "BOLLINGER BANDS", vwap: "VWAP", cvd_obv: "CVD / OBV",
  funding_oi: "FUNDING & OI", ob_imbalance: "ORDER BOOK IMBALANCE",
  ml: "ML MODEL (LOGIT)", sentiment: "SENTIMENT INDEX",
  macd_hist: "MACD HISTOGRAM", atr_mom: "ATR MOMENTUM",
};

/* IC hasil audit 14 hari × 12 instrumen (klines 1m, non-overlapping) */
export const IC_TABLE = {
  5: { ema_ribbon: -0.0061, supertrend: -0.0206, rsi_div: -0.0171, bollinger: -0.0209,
       vwap: -0.0052, cvd_obv: 0.0, macd_hist: -0.0206, atr_mom: -0.0219,
       ob_imbalance: 0, funding_oi: 0, ml: 0, sentiment: 0 },
  15: { ema_ribbon: 0.0051, supertrend: -0.0088, rsi_div: -0.0069, bollinger: -0.0163,
        vwap: -0.0051, cvd_obv: 0.0009, macd_hist: -0.008, atr_mom: -0.006,
        ob_imbalance: 0, funding_oi: 0, ml: 0, sentiment: 0 },
  30: { ema_ribbon: 0.0279, supertrend: 0.0087, rsi_div: 0.0221, bollinger: 0.0146,
        vwap: -0.0074, cvd_obv: -0.0037, macd_hist: 0.0302, atr_mom: 0.0238,
        ob_imbalance: 0, funding_oi: 0, ml: 0, sentiment: 0 },
  60: { ema_ribbon: 0.0109, supertrend: 0.0141, rsi_div: 0.0438, bollinger: 0.0496,
        vwap: 0.0068, cvd_obv: 0.0153, macd_hist: 0.0978, atr_mom: 0.069,
        ob_imbalance: 0, funding_oi: 0, ml: 0, sentiment: 0 },
};

export const GATE_THRESHOLD = { 5: 0.25, 15: 0.22, 30: 0.18, 60: 0.12 };
export const BACKTEST = {
  5: { hit: 46.3, edge: -0.006, n: 46588, mode: "momentum" },
  15: { hit: 51.2, edge: 0.004, n: 15525, mode: "kontrarian" },
  30: { hit: 48.5, edge: 0.028, n: 7768, mode: "momentum" },
  60: { hit: 51.6, edge: 0.109, n: 3837, mode: "macd+atr-momentum" },
};
export const FEE_PCT = 0.10;
const MIN_IC = 0.010, IC_SCALE = 12.0;

/* ---------------- indikator ---------------- */
export const clamp = (x, lo = -1, hi = 1) => Math.max(lo, Math.min(hi, x));

export function ema(a, n) {
  const out = new Float64Array(a.length); if (!a.length) return out;
  const k = 2 / (n + 1); out[0] = a[0];
  for (let i = 1; i < a.length; i++) out[i] = out[i - 1] + k * (a[i] - out[i - 1]);
  return out;
}
export function rma(a, n) {
  const out = new Float64Array(a.length); if (!a.length) return out;
  const k = 1 / n; out[0] = a[0];
  for (let i = 1; i < a.length; i++) out[i] = out[i - 1] + k * (a[i] - out[i - 1]);
  return out;
}
export function sma(a, n) {
  const out = new Float64Array(a.length).fill(NaN);
  let s = 0;
  for (let i = 0; i < a.length; i++) {
    s += a[i];
    if (i >= n) s -= a[i - n];
    if (i >= n - 1) out[i] = s / n;
  }
  return out;
}
function trueRange(h, l, c) {
  const out = new Float64Array(c.length);
  for (let i = 0; i < c.length; i++) {
    const prev = i ? c[i - 1] : c[i];
    out[i] = Math.max(h[i] - l[i], Math.abs(h[i] - prev), Math.abs(l[i] - prev));
  }
  return out;
}
export const atr = (h, l, c, n = 14) => rma(trueRange(h, l, c), n);

export function rsi(c, n = 14) {
  const g = new Float64Array(c.length), ls = new Float64Array(c.length);
  for (let i = 1; i < c.length; i++) {
    const d = c[i] - c[i - 1];
    g[i] = d > 0 ? d : 0; ls[i] = d < 0 ? -d : 0;
  }
  const ag = rma(g, n), al = rma(ls, n);
  const out = new Float64Array(c.length);
  for (let i = 0; i < c.length; i++) {
    const rs = al[i] > 1e-12 ? ag[i] / al[i] : 1e9;
    out[i] = 100 - 100 / (1 + rs);
  }
  return out;
}
export function bollinger(c, n = 20, mult = 2) {
  const mid = sma(c, n);
  const pb = new Float64Array(c.length).fill(NaN), bw = new Float64Array(c.length).fill(NaN);
  for (let i = n - 1; i < c.length; i++) {
    let s = 0;
    for (let j = i - n + 1; j <= i; j++) s += (c[j] - mid[i]) ** 2;
    const sd = Math.sqrt(s / n), up = mid[i] + mult * sd, lo = mid[i] - mult * sd;
    const rng = Math.max(up - lo, 1e-12);
    pb[i] = (c[i] - lo) / rng; bw[i] = rng / Math.max(mid[i], 1e-12);
  }
  return { mid, pb, bw };
}
export function supertrend(h, l, c, n = 10, mult = 3) {
  const a = atr(h, l, c, n), dir = new Int8Array(c.length).fill(1), st = new Float64Array(c.length);
  let fu = 0, fl = 0;
  for (let i = 0; i < c.length; i++) {
    const hl2 = (h[i] + l[i]) / 2, up = hl2 + mult * a[i], lo = hl2 - mult * a[i];
    if (i === 0) { fu = up; fl = lo; }
    else {
      fu = (up < fu || c[i - 1] > fu) ? up : fu;
      fl = (lo > fl || c[i - 1] < fl) ? lo : fl;
      if (c[i] > fu) dir[i] = 1; else if (c[i] < fl) dir[i] = -1; else dir[i] = dir[i - 1];
    }
    st[i] = dir[i] > 0 ? fl : fu;
  }
  return { st, dir };
}
export function obv(c, v) {
  const out = new Float64Array(c.length);
  for (let i = 1; i < c.length; i++) {
    const d = Math.sign(c[i] - c[i - 1]);
    out[i] = out[i - 1] + d * v[i];
  }
  return out;
}
export function rollingVwap(h, l, c, v, w = 240) {
  const out = new Float64Array(c.length).fill(NaN);
  let pv = 0, vv = 0;
  for (let i = 0; i < c.length; i++) {
    const tp = (h[i] + l[i] + c[i]) / 3;
    pv += tp * v[i]; vv += v[i];
    if (i >= w) { const tp0 = (h[i - w] + l[i - w] + c[i - w]) / 3; pv -= tp0 * v[i - w]; vv -= v[i - w]; }
    if (i >= w - 1 && vv > 0) out[i] = pv / vv;
  }
  return out;
}
export function sessionVwap(h, l, c, v, ts) {
  const midnight = Math.floor(ts[ts.length - 1] / 86400000) * 86400000;
  let pv = 0, vv = 0;
  for (let i = ts.length - 1; i >= 0 && ts[i] >= midnight; i--) {
    pv += ((h[i] + l[i] + c[i]) / 3) * v[i]; vv += v[i];
  }
  return vv > 0 ? pv / vv : c[c.length - 1];
}
export function linregSlope(a) {
  const n = a.length; if (n < 3) return 0;
  let mx = (n - 1) / 2, my = 0;
  for (let i = 0; i < n; i++) my += a[i];
  my /= n;
  let num = 0, den = 0;
  for (let i = 0; i < n; i++) { const dx = i - mx; num += dx * (a[i] - my); den += dx * dx; }
  return den > 0 ? num / den : 0;
}
export function pivotPoints(a, kind, k = 3) {
  const idx = [];
  for (let i = k; i < a.length - k; i++) {
    let ok = true;
    for (let j = i - k; j <= i + k; j++) {
      if (kind === "low" && a[j] < a[i]) { ok = false; break; }
      if (kind === "high" && a[j] > a[i]) { ok = false; break; }
    }
    if (ok) idx.push(i);
  }
  return idx;
}
export function priceDecimals(p) {
  p = Math.abs(p || 0);
  if (p >= 100) return 2;
  if (p >= 1) return 4;
  if (p >= 0.01) return 5;
  if (p >= 0.001) return 6;
  return 8;
}

/* ---------------- ML logit (dilatih di browser) ---------------- */
export function trainLogit(kl, horizon = 60) {
  const n = kl.length;
  if (n < 240) return null;
  const o = kl.map((k) => k.o), h = kl.map((k) => k.h), l = kl.map((k) => k.l);
  const c = kl.map((k) => k.c), v = kl.map((k) => k.v), tb = kl.map((k) => k.tb);
  const q = kl.map((k) => (k.q != null ? k.q : k.v * k.c));   // quote volume (USD)`);
  const e9 = ema(c, 9), e21 = ema(c, 21), e55 = ema(c, 55);
  const r = rsi(c, 14), a = atr(h, l, c, 14), bb = bollinger(c, 20, 2);
  const ob = obv(c, v);
  const X = [], y = [];
  for (let i = 60; i < n - horizon; i++) {
    const vm = v.slice(i - 19, i + 1).reduce((x, z) => x + z, 0) / 20 || 1e-9;
    X.push([
      (c[i] - c[i - 1]) / c[i] * 100,
      (c[i] - c[i - 5]) / c[i] * 100,
      (c[i] - c[i - 14]) / c[i] * 100,
      (e9[i] - e21[i]) / c[i] * 100,
      (e21[i] - e55[i]) / c[i] * 100,
      r[i] / 100,
      isFinite(bb.pb[i]) ? bb.pb[i] : 0.5,
      a[i] / c[i] * 100,
      linregSlope(ob.slice(i - 19, i + 1)) / vm,
      (tb[i] / Math.max(v[i], 1e-9)),
    ]);
    y.push(c[i + horizon] > c[i] ? 1 : 0);
  }
  if (X.length < 150) return null;
  const d = X[0].length;
  // standarisasi
  const mu = new Array(d).fill(0), sd = new Array(d).fill(0);
  for (const row of X) for (let j = 0; j < d; j++) mu[j] += row[j];
  for (let j = 0; j < d; j++) mu[j] /= X.length;
  for (const row of X) for (let j = 0; j < d; j++) sd[j] += (row[j] - mu[j]) ** 2;
  for (let j = 0; j < d; j++) sd[j] = Math.sqrt(sd[j] / X.length) || 1;
  const Z = X.map((row) => row.map((x, j) => (x - mu[j]) / sd[j]));
  const cut = Math.floor(Z.length * 0.8);
  const w = new Array(d).fill(0); let b = 0;
  const lr = 0.25, l2 = 0.01;
  for (let it = 0; it < 400; it++) {
    const gw = new Array(d).fill(0); let gb = 0;
    for (let i = 0; i < cut; i++) {
      let z = b; for (let j = 0; j < d; j++) z += w[j] * Z[i][j];
      const p = 1 / (1 + Math.exp(-z)), err = p - y[i];
      gb += err; for (let j = 0; j < d; j++) gw[j] += err * Z[i][j];
    }
    b -= lr * gb / cut;
    for (let j = 0; j < d; j++) w[j] -= lr * (gw[j] / cut + l2 * w[j]);
  }
  const proba = (row) => {
    let z = b; for (let j = 0; j < d; j++) z += w[j] * row[j];
    return 1 / (1 + Math.exp(-z));
  };
  // AUC pada 20% terakhir (holdout)
  const pos = [], neg = [];
  for (let i = cut; i < Z.length; i++) (y[i] ? pos : neg).push(proba(Z[i]));
  let auc = null;
  if (pos.length && neg.length) {
    let win = 0;
    for (const p of pos) for (const q of neg) win += p > q ? 1 : p === q ? 0.5 : 0;
    auc = win / (pos.length * neg.length);
  }
  return { prob: proba(Z[Z.length - 1]), n: cut, auc };
}

/* ---------------- sinyal ---------------- */
export function buildSignals(kl, depth, sentiment) {
  const o = kl.map((k) => k.o), h = kl.map((k) => k.h), l = kl.map((k) => k.l);
  const c = kl.map((k) => k.c), v = kl.map((k) => k.v), tb = kl.map((k) => k.tb);
  const q = kl.map((k) => (k.q != null ? k.q : k.v * k.c));   // quote volume (USD)`);
  const ts = kl.map((k) => k.t);
  const price = c[c.length - 1];
  const pdec = priceDecimals(price);
  const pp = price >= 1 ? 2 : 3;
  const fp = (x, d = pdec) => Number(x).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const sig = [];
  const add = (key, status, value, score, note = "") =>
    sig.push({ key, name: LABEL[key], category: CATEGORY[key], status, value,
               score: +score.toFixed(3), note });

  // 1. EMA ribbon
  const e9 = ema(c, 9), e21 = ema(c, 21), e55 = ema(c, 55);
  const spread = (e9[e9.length - 1] - e55[e55.length - 1]) / price * 100;
  let st, sc;
  if (e9.at(-1) > e21.at(-1) && e21.at(-1) > e55.at(-1) && price > e21.at(-1)) { st = "BULL"; sc = clamp(0.45 + spread / 1.2, 0.2, 1); }
  else if (e9.at(-1) < e21.at(-1) && e21.at(-1) < e55.at(-1) && price < e21.at(-1)) { st = "BEAR"; sc = clamp(0.45 + spread / 1.2, -1, -0.2); }
  else { st = "NEUTRAL"; sc = clamp(spread * 1.5, -0.35, 0.35); }
  add("ema_ribbon", st, `9/21/55 · ${spread >= 0 ? "+" : ""}${spread.toFixed(2)}%`, sc);

  // 2. Supertrend
  const sT = supertrend(h, l, c, 10, 3);
  const dist = (price - sT.st.at(-1)) / price * 100;
  add("supertrend", sT.dir.at(-1) > 0 ? "BULL" : "BEAR",
      `line ${fp(sT.st.at(-1))} · ${dist >= 0 ? "+" : ""}${dist.toFixed(pp)}%`,
      sT.dir.at(-1) > 0 ? clamp(0.5 + Math.abs(dist) / 1.5, 0.25, 1) : clamp(-0.5 - Math.abs(dist) / 1.5, -1, -0.25));

  // 3. RSI (+ divergence)
  const r = rsi(c, 14), win = Math.min(90, c.length);
  const cw = c.slice(-win), rw = Array.from(r.slice(-win));
  const lows = pivotPoints(cw, "low"), highs = pivotPoints(cw, "high");
  let rsiSt = "NEUTRAL", rsiSc = clamp((r.at(-1) - 50) / 60, -0.25, 0.25), rsiVal = `RSI ${r.at(-1).toFixed(1)}`;
  if (lows.length >= 2) {
    const [i1, i2] = [lows.at(-2), lows.at(-1)];
    if (cw[i2] < cw[i1] && rw[i2] > rw[i1] + 1.5) { rsiSt = "BULL"; rsiSc = 0.6; rsiVal = `bullish div · RSI ${r.at(-1).toFixed(1)}`; }
  }
  if (highs.length >= 2) {
    const [i1, i2] = [highs.at(-2), highs.at(-1)];
    if (cw[i2] > cw[i1] && rw[i2] < rw[i1] - 1.5) { rsiSt = "BEAR"; rsiSc = -0.6; rsiVal = `bearish div · RSI ${r.at(-1).toFixed(1)}`; }
  }
  add("rsi_div", rsiSt, rsiVal, rsiSc);

  // 4. Bollinger
  const bb = bollinger(c, 20, 2);
  const pbv = bb.pb.at(-1), bwv = bb.bw.at(-1);
  const bwAvg = bb.bw.slice(-30, -5).reduce((a, x) => a + (isFinite(x) ? x : 0), 0) / 25;
  const squeeze = bwv < bwAvg * 0.8;
  let bbSt = "NEUTRAL", bbSc = clamp((pbv - 0.5) * 0.5, -0.25, 0.25);
  if (pbv > 1) { bbSt = "BEAR"; bbSc = -0.35; } else if (pbv < 0) { bbSt = "BULL"; bbSc = 0.35; }
  add("bollinger", bbSt, `%B ${pbv.toFixed(2)} · width ${(bwv * 100).toFixed(pp)}%` + (squeeze ? " · squeeze" : ""), bbSc);

  // 5. VWAP sesi
  const vw = sessionVwap(h, l, c, v, ts), vdev = (price - vw) / vw * 100;
  add("vwap", price > vw ? "BULL" : "BEAR", `${fp(vw)} · ${vdev >= 0 ? "+" : ""}${vdev.toFixed(pp)}%`,
      price > vw ? clamp(0.3 + vdev / 2, 0.15, 0.9) : clamp(-0.3 + vdev / 2, -0.9, -0.15));

  // 6. CVD / OBV
  const delta = tb.map((x, i) => 2 * x - v[i]);
  const cvd = []; let acc = 0;
  delta.forEach((d) => { acc += d; cvd.push(acc); });
  const ob = Array.from(obv(c, v));
  const vm60 = v.slice(-60).reduce((a, x) => a + x, 0) / 60;
  const mix = 0.6 * linregSlope(cvd.slice(-60)) / Math.max(vm60, 1e-9) + 0.4 * linregSlope(ob.slice(-60)) / Math.max(vm60, 1e-9);
  const v30 = v.slice(-30).reduce((a, x) => a + x, 0), tb30 = tb.slice(-30).reduce((a, x) => a + x, 0);
  const taker = tb30 / Math.max(v30, 1e-9);
  const cvdSc = clamp(mix * 0.55 + (taker - 0.5) * 2.2, -1, 1);
  add("cvd_obv", cvdSc > 0.18 ? "BULL" : cvdSc < -0.18 ? "BEAR" : "NEUTRAL",
      `taker ${(taker * 100).toFixed(1)}% · slope ${mix >= 0 ? "+" : ""}${mix.toFixed(2)}`, cvdSc);

  // 7. Funding & OI (proxy spot)
  const fund = (taker - 0.5) * 0.02;
  const qRecent = q.slice(-30).reduce((a, x) => a + x, 0) / 30;
  const qOld = q.slice(-150, -30).reduce((a, x) => a + x, 0) / 120;
  const flow = (qRecent / Math.max(qOld, 1e-9) - 1) * 100;
  let fSc = clamp(fund / 0.01 * 0.4 + flow / 40 * 0.6, -1, 1);
  if (Math.abs(fund) > 0.012 && flow > 15) fSc = -fSc * 0.6;
  add("funding_oi", fSc > 0.2 ? "BULL" : fSc < -0.2 ? "BEAR" : "NEUTRAL",
      `fund ${fund >= 0 ? "+" : ""}${fund.toFixed(4)}% · flow ${flow >= 0 ? "+" : ""}${flow.toFixed(1)}%`, fSc,
      "proxy spot (futures diblokir)");

  // 8. Order book imbalance
  let obSt = "NEUTRAL", obSc = 0, obVal = depth && depth.bids.length ? "" : "menunggu depth";
  if (depth && depth.bids.length && depth.asks.length) {
    const bq = depth.bids.reduce((a, x) => a + x[1], 0), aq = depth.asks.reduce((a, x) => a + x[1], 0);
    const imb = (bq - aq) / Math.max(bq + aq, 1e-9);
    obSc = clamp(imb * 2.2, -1, 1);
    obSt = obSc > 0.18 ? "BULL" : obSc < -0.18 ? "BEAR" : "NEUTRAL";
    obVal = `bid ${(bq / (bq + aq) * 100).toFixed(1)}% · ${(imb * 100).toFixed(1)}%`;
  }
  add("ob_imbalance", obSt, obVal, obSc);

  // 9. MACD histogram
  const macd = ema(c, 12).map((x, i) => x - ema(c, 26)[i]);
  const macdSig = ema(macd, 9);
  const a14 = atr(h, l, c, 14).at(-1);
  const hist = (macd.at(-1) - macdSig.at(-1)) / Math.max(a14, 1e-9);
  const mhSc = clamp(hist * 1.5, -0.8, 0.8);
  add("macd_hist", mhSc > 0.15 ? "BULL" : mhSc < -0.15 ? "BEAR" : "NEUTRAL",
      `hist ${hist >= 0 ? "+" : ""}${hist.toFixed(2)}×ATR`, mhSc);

  // 10. ATR momentum
  const ret10 = c.length > 11 ? (c.at(-1) / c.at(-11) - 1) * 100 : 0;
  const atrPct = a14 / price * 100;
  const amom = ret10 / Math.max(atrPct * 3, 1e-9);
  const amSc = clamp(amom, -0.8, 0.8);
  add("atr_mom", amSc > 0.2 ? "BULL" : amSc < -0.2 ? "BEAR" : "NEUTRAL",
      `mom ${ret10 >= 0 ? "+" : ""}${ret10.toFixed(2)}% / ATR ${atrPct.toFixed(2)}%`, amSc);

  // 11. ML logit (dilatih di browser, horizon aktif)
  let mlRes = null;
  try { mlRes = trainLogit(kl, HORIZON_ACTIVE); } catch (e) { mlRes = null; }
  if (!mlRes) {
    add("ml", "NEUTRAL", "n/a · data kurang", 0, "logit in-browser");
  } else {
    const sc0 = clamp((mlRes.prob - 0.5) * 2.6, -1, 1);
    add("ml", mlRes.prob > 0.56 ? "BULL" : mlRes.prob < 0.44 ? "BEAR" : "NEUTRAL",
        `P(up) ${(mlRes.prob * 100).toFixed(1)}% · n=${mlRes.n}` + (mlRes.auc != null ? ` · AUC ${mlRes.auc.toFixed(3)}` : ""),
        sc0, "logit in-browser (info-only)");
  }

  // 12. Sentiment
  let snSt = "NEUTRAL", snSc = 0, snVal = "n/a";
  const fng = sentiment && sentiment.value;
  if (fng != null) {
    if (fng <= 22) { snSt = "BULL"; snSc = 0.3; snVal = `${fng} · ${sentiment.label} (contrarian)`; }
    else if (fng >= 78) { snSt = "BEAR"; snSc = -0.3; snVal = `${fng} · ${sentiment.label} (contrarian)`; }
    else { snSc = clamp((fng - 50) / 50 * 0.55, -0.5, 0.5); snSt = fng >= 58 ? "BULL" : fng <= 42 ? "BEAR" : "NEUTRAL"; snVal = `${fng} · ${sentiment.label}`; }
  }
  add("sentiment", snSt, snVal, snSc);

  return { sig, price, pdec, a14, mlRes };
}

/* ---------------- state ---------------- */
let HORIZON_ACTIVE = 60;
export function buildState({ symbol, label, kl, depth, sentiment, horizon = 60 }) {
  HORIZON_ACTIVE = horizon;
  if (!kl || kl.length < 120) return null;
  const { sig, price, pdec, a14, mlRes } = buildSignals(kl, depth, sentiment);
  const c = kl.map((k) => k.c), h = kl.map((k) => k.h), l = kl.map((k) => k.l);
  const ic = IC_TABLE[horizon] || IC_TABLE[60];

  let S = 0, totW = 0;
  const voters = [];
  for (const s of sig) {
    const v = ic[s.key] ?? 0;
    if (Math.abs(v) < MIN_IC) { s.weight = 0; s.mode = "info"; s.orient = 0; s.ic = +v.toFixed(3); continue; }
    const w = Math.min(Math.abs(v) * IC_SCALE, 1.8), orient = v > 0 ? 1 : -1;
    Object.assign(s, { weight: +w.toFixed(2), mode: "vote", orient, ic: +v.toFixed(3) });
    voters.push(s); S += w * orient * s.score; totW += w;
  }
  S = totW > 0 ? S / totW : 0;

  const famOf = {
    ema_ribbon: "tren", supertrend: "tren", atr_mom: "tren",
    rsi_div: "momentum", bollinger: "momentum", macd_hist: "momentum",
    cvd_obv: "flow", vwap: "flow", ob_imbalance: "flow",
  };
  const buckets = {};
  for (const s of voters) {
    const f = famOf[s.key]; if (!f) continue;
    (buckets[f] ||= []).push([s.weight, s.orient * s.score]);
  }
  const famScore = {};
  for (const [f, arr] of Object.entries(buckets)) {
    const ws = arr.reduce((a, x) => a + x[0], 0);
    famScore[f] = arr.reduce((a, x) => a + x[0] * x[1], 0) / Math.max(ws, 1e-9);
  }
  const catsOk = Object.values(famScore).filter((x) => Math.abs(x) > 0.05 && Math.sign(x) === Math.sign(S)).length;

  const atrPct = a14 / price * 100;
  const sigma = a14 * Math.sqrt(horizon);
  const expected = S * sigma * 0.9;
  const target = price + expected;
  const volFactor = clamp(atrPct / 0.12, 0.7, 1.8);
  const band = sigma * (1.05 + 0.45 * (1 - Math.abs(S))) * volFactor;

  const icQ = clamp(voters.reduce((a, s) => a + Math.abs(s.ic) * s.weight, 0) / Math.max(totW, 1e-9) / 0.08, 0, 1);
  const conf = Math.round(Math.max(30, Math.min(86, 34 + 26 * Math.abs(S) + 18 * (catsOk / 3) + 8 * icQ)));

  // filter rezim
  const e15 = ema(c.filter((_, i) => i % 15 === 0), 21), e1h = ema(c.filter((_, i) => i % 60 === 0), 21);
  const trend15 = c.at(-1) > e15.at(-1) ? 1 : -1, trend1h = c.at(-1) > e1h.at(-1) ? 1 : -1;
  const volOk = atrPct > 0.005 && atrPct < 0.9;
  const macroPass = trend15 === trend1h && volOk;

  const thr = GATE_THRESHOLD[horizon] ?? 0.12;
  const strengthOk = Math.abs(S) > thr;
  const gateOk = catsOk >= 2 && (macroPass || Math.abs(S) >= 0.35);
  let direction = "WAIT", verdict = "WAIT — Menunggu Sinyal", reason;
  if (strengthOk && gateOk) {
    direction = S > 0 ? "UP" : "DOWN";
    verdict = S > 0 ? "LONG — Sinyal Beli" : "SHORT — Sinyal Jual";
    reason = `skor ${S >= 0 ? "+" : ""}${S.toFixed(2)} · ${catsOk}/3 keluarga sepakat`;
  } else if (!strengthOk) {
    reason = `skor ${S >= 0 ? "+" : ""}${S.toFixed(2)} < ambang ${thr.toFixed(2)} (horizon ${horizon}m)`;
  } else if (catsOk < 2) {
    reason = `keluarga konflik (${catsOk}/3 sepakat)`;
  } else {
    reason = "filter rezim gagal" + (volOk ? "" : " · volatilitas ekstrem");
  }

  const bull = sig.filter((s) => s.status === "BULL").length;
  const bear = sig.filter((s) => s.status === "BEAR").length;

  return {
    symbol, label, price: +price.toFixed(pdec), price_raw: price,
    signals: sig,
    summary: {
      bull, bear, neutral: sig.length - bull - bear,
      score: +S.toFixed(4), verdict, direction, cats_ok: catsOk,
      cats: Object.fromEntries(Object.entries(famScore).map(([k, v]) => [k, +v.toFixed(3)])),
      reason, voters: voters.length, horizon_min: horizon,
      gate_threshold: thr, backtest: BACKTEST[horizon], fee_pct: FEE_PCT,
    },
    prediction: {
      horizon: horizon + "M", target: +target.toFixed(pdec),
      lo: +(target - band).toFixed(pdec), hi: +(target + band).toFixed(pdec),
      exp_move_pct: +(expected / price * 100).toFixed(3),
      confidence: conf, direction, decimals: pdec,
    },
    macro: { status: macroPass ? "PASS" : "FAIL",
             trend15, trend1h, atr_pct: +atrPct.toFixed(4), vol_ok: volOk,
             why: macroPass ? "tren 15m & 1h searah, volatilitas wajar"
                            : (trend15 !== trend1h ? "tren 15m vs 1h konflik" : "volatilitas di luar rentang"),
             note: `15m ${trend15 > 0 ? "↑" : "↓"} · 1h ${trend1h > 0 ? "↑" : "↓"} · ATR ${atrPct.toFixed(3)}%` },
    ml: mlRes
      ? { status: "logit", prob: +mlRes.prob.toFixed(4), n: mlRes.n,
          auc: mlRes.auc != null ? +mlRes.auc.toFixed(4) : null }
      : { status: "n/a · data kurang", prob: null, n: 0, auc: null },
    instruments: INSTRUMENTS,
    ts: Date.now(),
    source: "Binance Spot · data-api.binance.vision + data-stream (browser)",
  };
}
