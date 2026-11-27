/* CryptoPulse — versi statis (GitHub Pages). Data langsung dari Binance publik. */
import { INSTRUMENTS, buildState, priceDecimals } from "./engine.js?v=5";

const REST = "https://data-api.binance.vision";
const WSBASE = "wss://data-stream.binance.vision/stream?streams=";
const HORIZONS = [15, 30, 60];
const LS_KEY = "cryptopulse.preds.v1";

const S = {
  symbol: "BTCUSDT",
  horizon: +(localStorage.getItem("cp.horizon") || 60),
  kl: [], klSymbol: null, chart: [], depth: { bids: [], asks: [] },
  sentiment: null, ticker: {}, data: null, ws: null, lastPrice: null,
  conn: false, realtime: false,
};

const $ = (id) => document.getElementById(id);
const fmt = (v, d) => (v == null || Number.isNaN(v) ? "—"
  : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d }));

/* ---------------- data ---------------- */
async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(url + " " + r.status);
  return r.json();
}

async function loadKlines(sym, limit = 1000) {
  const raw = await getJSON(`${REST}/api/v3/klines?symbol=${sym}&interval=1m&limit=${limit}`);
  return raw.map((k) => ({ t: k[0], o: +k[1], h: +k[2], l: +k[3], c: +k[4],
                           v: +k[5], q: +k[7], tb: +k[9] }));
}
async function loadTicker(sym) {
  const t = await getJSON(`${REST}/api/v3/ticker/24hr?symbol=${sym}`);
  return { chg: +t.priceChangePercent, hi: +t.highPrice, lo: +t.lowPrice, vol: +t.volume, last: +t.lastPrice };
}
async function loadSentiment() {
  try {
    const j = await getJSON("https://api.alternative.me/fng/?limit=1");
    S.sentiment = { value: +j.data[0].value, label: j.data[0].value_classification };
  } catch (e) { /* biarkan null → tampil n/a */ }
}

function patchKline(k) {
  const row = { t: k.t, o: +k.o, h: +k.h, l: +k.l, c: +k.c, v: +k.v, q: +k.q, tb: +k.V };
  S.lastPrice = row.c;
  const last = S.kl[S.kl.length - 1];
  if (last && last.t === row.t) S.kl[S.kl.length - 1] = row;
  else if (!last || row.t > last.t) S.kl.push(row);
  if (S.kl.length > 1200) S.kl = S.kl.slice(-1000);
}

/* ---------------- websocket ---------------- */
function connectWS() {
  if (S.ws) { try { S.ws.onclose = null; S.ws.close(); } catch (e) {} }
  const sym = S.symbol.toLowerCase();
  const url = `${WSBASE}${sym}@kline_1m/${sym}@depth20@1000ms`;
  let ws;
  try { ws = new WebSocket(url); } catch (e) { setConn(false); setTimeout(connectWS, 4000); return; }
  S.ws = ws;
  ws.onopen = () => setConn(true);
  ws.onclose = () => { setConn(false); setTimeout(connectWS, 4000); };
  ws.onerror = () => setConn(false);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    const stream = msg.stream || "", d = msg.data || {};
    S.realtime = true;
    if (stream.includes("@kline")) patchKline(d.k);
    else if (stream.includes("@depth")) {
      S.depth = {
        bids: (d.bids || []).map((x) => [+x[0], +x[1]]),
        asks: (d.asks || []).map((x) => [+x[0], +x[1]]),
      };
    }
    tickPrice(S.lastPrice);
  };
}

function setConn(ok) {
  S.conn = ok;
  const chip = $("connChip");
  chip.classList.toggle("live", ok);
  chip.classList.toggle("down", !ok);
  $("connText").textContent = ok ? "live" : "offline";
  $("footStatus").textContent = ok ? "live · streaming binance" : "reconnecting…";
}

/* ---------------- prediksi (localStorage) ---------------- */
function preds() {
  try { return JSON.parse(localStorage.getItem(LS_KEY) || "[]"); } catch (e) { return []; }
}
function savePreds(a) { localStorage.setItem(LS_KEY, JSON.stringify(a.slice(-800))); }

function logPrediction(d) {
  const p = d.prediction;
  if (p.direction === "WAIT") return;
  const win = S.horizon * 60000;
  const all = preds();
  const bucket = Math.floor(d.ts / win);
  if (all.some((x) => x.sym === d.symbol && Math.floor(x.ts / win) === bucket)) return;
  all.push({ sym: d.symbol, ts: d.ts, price: d.price_raw, target: p.target,
             dir: p.direction, h: S.horizon });
  savePreds(all);
}

async function resolvePredictions() {
  const all = preds();
  let changed = false;
  for (const x of all) {
    if (x.resolved) continue;
    const cutoff = x.ts + x.h * 60000;
    if (Date.now() < cutoff + 2000) continue;
    try {
      const kl = x.sym === S.symbol ? S.kl : await loadKlines(x.sym, 300);
      const bar = kl.find((k) => k.t >= cutoff);
      const px = bar ? bar.c : (kl.at(-1) ? kl.at(-1).c : null);
      if (px == null) continue;
      x.resolved = px;
      x.hit = (px - x.price) * (x.target - x.price) > 0 ? 1 : 0;
      changed = true;
    } catch (e) { /* coba lagi nanti */ }
  }
  if (changed) savePreds(all);
}

function statsFor(sym) {
  const rows = preds().filter((x) => x.sym === sym && x.resolved);
  const hits = rows.filter((x) => x.hit).length;
  const byId = new Set(rows.map((x) => x.ts));
  const pending = preds().filter((x) => x.sym === sym && !x.resolved && !byId.has(x.ts)).length;
  return {
    total: rows.length, hits,
    accuracy: rows.length ? +(hits / rows.length * 100).toFixed(1) : null,
    pending,
    recent: rows.slice(-8).reverse().map((x) => ({ ts: x.ts, price: x.price, target: x.target,
                                                   direction: x.dir, hit: !!x.hit, resolved: x.resolved })),
  };
}

/* ---------------- tabs & horizon ---------------- */
function buildTabs() {
  const nav = $("pairtabs");
  nav.innerHTML = "";
  INSTRUMENTS.forEach((it) => {
    const b = document.createElement("button");
    b.className = "ptab" + (it.symbol === S.symbol ? " active" : "");
    b.textContent = it.label;
    b.onclick = () => { if (it.symbol !== S.symbol) { S.symbol = it.symbol; buildTabs(); boot(); } };
    nav.appendChild(b);
  });
  $("pairCount").textContent = INSTRUMENTS.length;
}

function renderHz() {
  const box = $("hzChips");
  box.innerHTML = "";
  HORIZONS.forEach((h) => {
    const b = document.createElement("button");
    b.className = "hzbtn" + (h === S.horizon ? " on" : "");
    b.textContent = h + "m";
    b.onclick = () => {
      S.horizon = h;
      localStorage.setItem("cp.horizon", h);
      renderHz(); rebuild();
    };
    box.appendChild(b);
  });
}

/* ---------------- render ---------------- */
function render() {
  const d = S.data;
  if (!d) return;
  const dec = d.prediction.decimals;
  $("heroPair").textContent = d.label;
  $("price").textContent = fmt(S.lastPrice ?? d.price, dec);
  const chg = S.ticker.chg ?? 0;
  $("chg24").innerHTML = `<span class="${chg >= 0 ? "green" : "red"}">${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%</span>`;
  $("hi24").textContent = fmt(S.ticker.hi, dec);
  $("lo24").textContent = fmt(S.ticker.lo, dec);
  $("vol24").textContent = S.ticker.vol ? fmt(S.ticker.vol, 0) + " " + d.symbol.replace("USDT", "") : "—";
  $("priceTag").textContent = d.label.split("/")[0] + " · spot";

  const mc = $("macroChip");
  mc.classList.toggle("ok", d.macro.status === "PASS");
  mc.classList.toggle("fail", d.macro.status !== "PASS");
  const m = d.macro;
  $("macroText").textContent = m.status === "PASS" ? "PASS"
    : `FAIL · 15m${m.trend15 > 0 ? "↑" : "↓"} 1h${m.trend1h > 0 ? "↑" : "↓"}`;
  mc.title = `${m.why} — ${m.note}`;

  const wrap = $("signals");
  const byKey = new Map([...wrap.children].map((c) => [c.dataset.key, c]));
  d.signals.forEach((s) => {
    let card = byKey.get(s.key);
    if (!card) {
      card = document.createElement("div");
      card.dataset.key = s.key;
      card.innerHTML = `<div class="badge"></div><div><div class="cname"></div><div class="ccat"></div></div>
                        <div><div class="cval"></div><div class="cnote"></div></div><div class="cmode"></div>`;
      wrap.appendChild(card);
    }
    card.className = "card " + s.status.toLowerCase();
    card.querySelector(".cname").textContent = s.name;
    card.querySelector(".ccat").textContent = s.category;
    const glyph = s.status === "BULL" ? "▲" : s.status === "BEAR" ? "▼" : "●";
    card.querySelector(".badge").textContent = `${glyph} ${s.status}`;
    card.querySelector(".cval").textContent = s.value;
    const note = card.querySelector(".cnote");
    note.textContent = s.note || ""; note.style.display = s.note ? "block" : "none";
    const mode = card.querySelector(".cmode");
    const isVote = s.mode === "vote" && s.weight > 0;
    mode.textContent = isVote ? `voter ${s.weight}` : "info";
    mode.className = "cmode" + (isVote ? " vote" : "");
  });

  const sum = d.summary;
  $("bullN").textContent = sum.bull; $("neutralN").textContent = sum.neutral; $("bearN").textContent = sum.bear;
  const tot = Math.max(1, sum.bull + sum.neutral + sum.bear);
  $("segBull").style.width = (sum.bull / tot * 100) + "%";
  $("segNeutral").style.width = (sum.neutral / tot * 100) + "%";
  $("segBear").style.width = (sum.bear / tot * 100) + "%";

  const v = $("verdict");
  v.textContent = sum.verdict;
  v.className = "verdict" + (sum.direction === "UP" ? " buy" : sum.direction === "DOWN" ? " sell" : "");
  const sc = Math.max(-1, Math.min(1, sum.score)), pct = Math.abs(sc) * 50;
  const fill = $("scoreFill");
  fill.style.width = pct + "%"; fill.style.left = (sc >= 0 ? 50 : 50 - pct) + "%";
  fill.classList.toggle("neg", sc < 0);
  $("scoreVal").textContent = (sc >= 0 ? "+" : "") + sc.toFixed(3);

  const parts = Object.entries(sum.cats || {}).map(([k, val]) => `<b>${k}</b> ${Number(val).toFixed(2)}`).join(" &nbsp;");
  $("reason").innerHTML = `${sum.reason || ""} &nbsp;·&nbsp; ${parts}`;

  const p = d.prediction;
  $("horizon").textContent = p.horizon;
  $("pNow").textContent = fmt(S.lastPrice ?? d.price, dec);
  $("pNowSub").innerHTML = `<span class="${p.exp_move_pct >= 0 ? "green" : "red"}">target ${p.exp_move_pct >= 0 ? "+" : ""}${p.exp_move_pct.toFixed(3)}%</span> dalam ${p.horizon}`;
  $("pTarget").textContent = fmt(p.target, dec);
  $("pTarget").className = "pval " + (p.direction === "UP" ? "green" : p.direction === "DOWN" ? "red" : "yellow");
  $("pTargetSub").textContent = `${p.direction === "UP" ? "▲ bullish bias" : p.direction === "DOWN" ? "▼ bearish bias" : "● netral"} · ${sum.voters} voter / ${d.signals.length} indikator`;
  $("pRange").textContent = `${fmt(p.lo, dec)} — ${fmt(p.hi, dec)}`;
  $("pRangeSub").textContent = `± ${fmt((p.hi - p.lo) / 2, dec)} · band ATR-based`;
  $("pConf").textContent = p.confidence + "%";
  $("confFill").style.width = p.confidence + "%";
  const dir = $("pDir"); dir.textContent = p.direction;
  dir.className = "dirchip" + (p.direction === "UP" ? " up" : p.direction === "DOWN" ? " down" : "");

  const ml = d.ml || {};
  $("mlStatus").textContent = ml.status === "logit"
    ? (ml.auc != null ? `logit · AUC ${ml.auc.toFixed(3)}` : "logit") : (ml.status || "n/a");
  $("mlProb").textContent = ml.prob == null ? "—" : (ml.prob * 100).toFixed(1) + "%";
  $("mlN").textContent = ml.n || "—";
  const seb = d.signals.find((s) => s.key === "sentiment");
  $("fng").textContent = seb ? seb.value : "—";
  $("srcNote").textContent = `${d.source} · depth20@1000ms · kline_1m`;
  $("voterNote").textContent = `voter aktif: ${sum.voters}/${d.signals.length} · bobot = |IC| × 12 (audit 14 hari), arah = sign(IC) · ambang gate ${sum.gate_threshold.toFixed(2)}`;
  const bt = sum.backtest || {};
  const after = (bt.edge - (sum.fee_pct || 0.1)).toFixed(3);
  $("btNote").innerHTML = bt.hit
    ? `backtest ${bt.n.toLocaleString("en-US")} sampel (${sum.horizon_min}m, ${bt.mode}): hit <b>${bt.hit}%</b> · edge ${bt.edge >= 0 ? "+" : ""}${bt.edge}%/trade · setelah fee 0.10% = ${after}%`
    : "—";

  const st = statsFor(d.symbol);
  $("accVal").textContent = st.accuracy == null ? "—" : st.accuracy + "%";
  $("accTotal").textContent = st.total; $("accPending").textContent = st.pending;
  const r = $("recent"); r.innerHTML = "";
  st.recent.forEach((x) => {
    const dt = new Date(x.ts);
    const el = document.createElement("span");
    el.className = "pill " + (x.hit ? "hit" : "miss");
    el.textContent = `${x.direction} ${x.hit ? "✓" : "✗"} ${String(dt.getHours()).padStart(2, "0")}:${String(dt.getMinutes()).padStart(2, "0")}`;
    el.title = `entry ${x.price} → target ${x.target} · aktual ${x.resolved}`;
    r.appendChild(el);
  });

  const left = S.horizon * 60000 - (Date.now() % (S.horizon * 60000));
  $("pCountdown").textContent = `window ${Math.floor(left / 60000)}:${String(Math.floor(left % 60000 / 1000)).padStart(2, "0")}`;
  $("footMid").textContent = `binance ${S.conn ? "live" : "reconnect"} · ${new Date(d.ts).toLocaleTimeString("id-ID")} · ${d.signals.length} indikator`;
  document.title = `${fmt(S.lastPrice ?? d.price, dec)} ${d.label} · CryptoPulse`;

  drawChart();
}

function tickPrice(p) {
  if (!S.data || p == null) return;
  const dec = S.data.prediction.decimals;
  const prev = S.lastPrice;
  S.lastPrice = p;
  const el = $("price");
  el.textContent = fmt(p, dec);
  const box = el.parentElement;
  box.classList.remove("up", "down");
  if (prev != null && p !== prev) box.classList.add(p > prev ? "up" : "down");
  setTimeout(() => box.classList.remove("up", "down"), 500);
  drawChart();
}

/* ---------------- chart ---------------- */
const cv = $("chart"), ctx = cv.getContext("2d");
function drawChart() {
  const bars = S.chart;
  if (!bars || bars.length < 5) return;
  const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = 220;
  if (!w || w < 20) return;
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const padL = 6, padR = 64, padT = 10, padB = 18;
  const cwd = w - padL - padR, ch = h - padT - padB;
  const pred = S.data && S.data.prediction;
  let hi = Math.max(...bars.map((b) => b[2])), lo = Math.min(...bars.map((b) => b[3]));
  if (pred) { hi = Math.max(hi, pred.hi); lo = Math.min(lo, pred.lo); }
  const pad = (hi - lo) * 0.08 || 1; hi += pad; lo -= pad;
  const y = (p) => padT + ch - ((p - lo) / (hi - lo)) * ch;
  const slot = cwd / (bars.length + 1);
  const dec = S.data ? S.data.prediction.decimals : 2;
  const fp = (v) => Number(v).toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  ctx.font = "10px JetBrains Mono, monospace"; ctx.textAlign = "left";
  for (let i = 0; i <= 4; i++) {
    const price = lo + (hi - lo) * i / 4, yy = y(price);
    ctx.strokeStyle = "rgba(22,39,63,.75)";
    ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(padL + cwd, yy); ctx.stroke();
    ctx.fillStyle = "#5b6982"; ctx.fillText(fp(price), padL + cwd + 8, yy + 3);
  }
  if (pred) {
    ctx.fillStyle = "rgba(255,207,92,.07)";
    ctx.fillRect(padL + cwd * 0.86, y(pred.hi), cwd * 0.14, Math.max(1, y(pred.lo) - y(pred.hi)));
    ctx.strokeStyle = pred.direction === "UP" ? "rgba(44,228,164,.85)" : pred.direction === "DOWN" ? "rgba(255,92,122,.85)" : "rgba(255,207,92,.85)";
    ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(padL + cwd * 0.86, y(pred.target)); ctx.lineTo(padL + cwd, y(pred.target)); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = ctx.strokeStyle; ctx.fillText(fp(pred.target), padL + cwd + 8, y(pred.target) + 3);
  }
  bars.forEach((b, i) => {
    const [, o, hh, ll, c] = b, x = padL + i * slot + slot / 2, up = c >= o;
    ctx.strokeStyle = up ? "rgba(44,228,164,.9)" : "rgba(255,92,122,.9)";
    ctx.fillStyle = up ? "rgba(44,228,164,.85)" : "rgba(255,92,122,.85)";
    ctx.beginPath(); ctx.moveTo(x, y(hh)); ctx.lineTo(x, y(ll)); ctx.stroke();
    const t = y(Math.max(o, c)), btm = y(Math.min(o, c));
    ctx.fillRect(x - Math.max(1, slot * 0.3), t, Math.max(2, slot * 0.6), Math.max(1, btm - t));
  });
  const last = bars.at(-1)[4], ly = y(last);
  ctx.strokeStyle = "rgba(232,238,251,.35)"; ctx.setLineDash([2, 3]);
  ctx.beginPath(); ctx.moveTo(padL, ly); ctx.lineTo(padL + cwd, ly); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#5b6982";
  const step = Math.ceil(bars.length / 6);
  for (let i = 0; i < bars.length; i += step) {
    const d2 = new Date(bars[i][0]);
    const lx = Math.max(padL, Math.min(padL + cwd - 30, padL + i * slot - 10));
    ctx.fillText(`${String(d2.getHours()).padStart(2, "0")}:${String(d2.getMinutes()).padStart(2, "0")}`, lx, h - 5);
  }
}

/* ---------------- boot ---------------- */
function rebuild() {
  if (!S.kl.length || S.klSymbol !== S.symbol) return;   // cegah render data pair lama
  S.data = buildState({ symbol: S.symbol, label: labelOf(S.symbol), kl: S.kl, depth: S.depth,
                        sentiment: S.sentiment, horizon: S.horizon });
  if (S.data) { logPrediction(S.data); render(); }
}

function labelOf(sym) {
  const it = INSTRUMENTS.find((x) => x.symbol === sym);
  return it ? it.label : sym;
}

async function boot() {
  $("footStatus").textContent = "memuat data…";
  const want = S.symbol;
  S.kl = []; S.klSymbol = null; S.chart = []; S.depth = { bids: [], asks: [] };
  try {
    const [kl, tick] = await Promise.all([loadKlines(want), loadTicker(want)]);
    if (want !== S.symbol) return;                       // user ganti pair saat fetch
    S.kl = kl; S.klSymbol = want; S.ticker = tick; S.lastPrice = tick.last;
    S.chart = kl.slice(-180).map((k) => [k.t, k.o, k.h, k.l, k.c, k.v]);
    if (!S.sentiment) await loadSentiment();
    rebuild();
    connectWS();
    await resolvePredictions();
  } catch (e) {
    $("footStatus").textContent = "gagal memuat: " + e.message;
  }
}

/* periodic refresh: klines tiap 60s, ticker 60s, sentimen 10 menit, resolve 60s */
setInterval(async () => {
  const want = S.symbol;
  try {
    const kl = await loadKlines(want, 300);
    if (want !== S.symbol) return;
    S.kl = kl; S.klSymbol = want;
    S.chart = S.kl.slice(-180).map((k) => [k.t, k.o, k.h, k.l, k.c, k.v]);
    rebuild();
  } catch (e) {}
}, 60000);
setInterval(async () => {
  const want = S.symbol;
  try { const t = await loadTicker(want); if (want === S.symbol) S.ticker = t; } catch (e) {}
}, 60000);
setInterval(loadSentiment, 600000);
setInterval(() => { resolvePredictions().then(() => rebrandStats()); }, 45000);
function rebrandStats() { if (S.data) render(); }
setInterval(() => {
  if (S.data) rebuild();
  const d = new Date();
  $("clock").textContent = d.toLocaleTimeString("en-GB", { timeZone: "Asia/Jakarta" });
}, 5000);
setInterval(() => S.ws && S.ws.readyState === 1 && S.ws.send("ping"), 20000);
window.addEventListener("resize", drawChart);
if (window.ResizeObserver) new ResizeObserver(() => drawChart()).observe(document.querySelector(".herochart"));
setInterval(drawChart, 1000);

buildTabs();
renderHz();
boot();
async function scanAll() {
  const out = [];
  window.__scan = { done: false, total: INSTRUMENTS.length, rows: out };
  for (const it of INSTRUMENTS) {
    try {
      const kl = await loadKlines(it.symbol, 1000);
      const st = buildState({ symbol: it.symbol, label: it.label, kl, depth: { bids: [], asks: [] },
                              sentiment: S.sentiment, horizon: S.horizon });
      const bad = st.signals.filter((x) => /n\/a|NaN|undefined/.test(String(x.value)));
      out.push({ sym: it.symbol, ok: !bad.length, macro: st.macro.status, why: st.macro.why,
                 dir: st.summary.direction, score: st.summary.score, voters: st.summary.voters,
                 bad: bad.map((b) => b.key + ":" + b.value) });
      await new Promise((r) => setTimeout(r, 120));
    } catch (e) { out.push({ sym: it.symbol, ok: false, error: String(e) }); }
    window.__scan.rows = out.slice();
  }
  window.__scan.done = true;
  return out;
}
window.__cp = { S, rebuild, drawChart, boot, preds, scanAll };
