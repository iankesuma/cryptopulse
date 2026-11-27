/* CryptoPulse frontend — live WS, tanpa dependency */
const state = {
  symbol: "ETHUSDT",
  ws: null,
  data: null,
  chart: [],
  lastPrice: null,
  decimals: 2,
  connected: false,
};

const $ = (id) => document.getElementById(id);

/* ---------------- pair tabs ---------------- */
function buildTabs(list) {
  const nav = $("pairtabs");
  nav.innerHTML = "";
  list.forEach((it) => {
    const sym = it.symbol, label = it.label || sym.replace("USDT", "/USDT");
    const b = document.createElement("button");
    b.className = "ptab" + (sym === state.symbol ? " active" : "");
    b.dataset.sym = sym;
    b.textContent = label;
    if (it.source === "gold") b.classList.add("gold");
    b.onclick = () => {
      if (sym === state.symbol) return;
      state.symbol = sym;
      nav.querySelectorAll(".ptab").forEach((x) => x.classList.toggle("active", x.dataset.sym === sym));
      connect();
    };
    nav.appendChild(b);
  });
  $("pairCount").textContent = list.length;
}

/* ---------------- horizon selector ---------------- */
const HORIZONS = [5, 15, 30, 60];
function renderHz(active) {
  const box = $("hzChips");
  if (!box) return;
  box.innerHTML = "";
  HORIZONS.forEach((h) => {
    const b = document.createElement("button");
    b.className = "hzbtn" + (h === active ? " on" : "");
    b.textContent = h + "m";
    b.onclick = async () => {
      box.querySelectorAll(".hzbtn").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      try { await fetch(`/api/horizon/${h}`, { method: "POST" }); } catch (e) {}
      setTimeout(connect, 400);
    };
    box.appendChild(b);
  });
}

/* ---------------- ws ---------------- */
function connect() {
  if (state.ws) {
    try { state.ws.onclose = null; state.ws.close(); } catch (e) {}
  }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/${state.symbol}`);
  state.ws = ws;

  ws.onopen = () => setConn(true);
  ws.onclose = () => { setConn(false); setTimeout(connect, 2500); };
  ws.onerror = () => setConn(false);

  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "init") {
      state.data = msg.state;
      state.chart = msg.chart || [];
      renderState(msg.state, msg.stats, msg.status);
      drawChart();
      setTimeout(drawChart, 150);
      setTimeout(drawChart, 600);
    } else if (msg.type === "state") {
      state.data = msg.state;
      renderState(msg.state, msg.stats, msg.status);
    } else if (msg.type === "tick") {
      tickPrice(msg.price);
    }
  };
}

function setConn(ok) {
  state.connected = ok;
  const chip = $("connChip");
  chip.classList.toggle("live", ok);
  chip.classList.toggle("down", !ok);
  $("connText").textContent = ok ? "live" : "offline";
  $("footStatus").textContent = ok ? "live · streaming binance" : "reconnecting…";
}

/* ---------------- formatting ---------------- */
function fmt(v, dec) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

function tickPrice(p) {
  if (!state.data) return;
  const dec = state.data.prediction?.decimals ?? 2;
  const prev = state.lastPrice;
  state.lastPrice = p;
  const el = $("price");
  el.textContent = fmt(p, dec);
  const box = el.parentElement;
  box.classList.remove("up", "down");
  if (prev !== null && p !== prev) box.classList.add(p > prev ? "up" : "down");
  setTimeout(() => box.classList.remove("up", "down"), 550);
  if (state.data.prediction) {
    const t = state.data.prediction;
    const diff = ((p - state.data.price_raw) / state.data.price_raw) * 100;
    $("pNowSub").innerHTML = `<span class="${diff >= 0 ? "green" : "red"}">${diff >= 0 ? "▲" : "▼"} ${diff.toFixed(3)}%</span> sejak snapshot`;
  }
  drawChart();
}

/* ---------------- render ---------------- */
function renderState(d, stats, status) {
  if (!d) return;
  state.decimals = d.prediction.decimals;

  buildTabsIfNeeded(d.instruments || (d.pairs || []).map((p) => ({ symbol: p, label: p.replace("USDT", "/USDT") })));
  $("heroPair").textContent = d.label || d.symbol.replace("USDT", "/USDT");
  const dec = d.prediction.decimals;
  $("price").textContent = fmt(d.price, dec);
  state.lastPrice = d.price;

  const chg = d.change24h;
  $("chg24").innerHTML = `<span class="${chg >= 0 ? "green" : "red"}">${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%</span>`;
  $("hi24").textContent = fmt(d.high24h, dec);
  $("lo24").textContent = fmt(d.low24h, dec);
  $("vol24").textContent = d.vol24h === null || d.vol24h === undefined
    ? "—"
    : fmt(d.vol24h, 0) + " " + d.symbol.replace("USDT", "");

  $("priceTag").textContent = (d.label ? d.label.split("/")[0] : d.symbol.replace("USDT", ""))
    + (d.source_kind === "gold" ? " · gold spot" : " · spot");
  $("priceTag").className = "pricetag";

  /* macro */
  const mc = $("macroChip");
  mc.classList.toggle("ok", d.macro.status === "PASS");
  mc.classList.toggle("fail", d.macro.status !== "PASS");
  $("macroText").textContent = d.macro.status;
  mc.title = d.macro.note;

  /* cards */
  const wrap = $("signals");
  const seen = new Map();
  [...wrap.children].forEach((c) => seen.set(c.dataset.key, c));
  d.signals.forEach((s) => {
    let card = seen.get(s.key);
    if (!card) {
      card = document.createElement("div");
      card.dataset.key = s.key;
      card.innerHTML = `<div class="badge"></div><div><div class="cname"></div><div class="ccat"></div></div>
                        <div><div class="cval"></div><div class="cnote"></div></div>
                        <div class="cmode"></div>`;
      wrap.appendChild(card);
    }
    const st = s.status.toLowerCase();
    card.className = "card " + st;
    card.querySelector(".cname").textContent = s.name;
    card.querySelector(".ccat").textContent = s.category;
    const glyph = s.status === "BULL" ? "▲" : s.status === "BEAR" ? "▼" : "●";
    card.querySelector(".badge").textContent = `${glyph} ${s.status}`;
    card.querySelector(".cval").textContent = s.value;
    const note = card.querySelector(".cnote");
    note.textContent = s.note || "";
    note.style.display = s.note ? "block" : "none";
    const mode = card.querySelector(".cmode");
    const isVote = s.mode === "vote" && s.weight > 0;
    mode.textContent = isVote ? `voter ${s.weight}` : "info";
    mode.className = "cmode" + (isVote ? " vote" : "");
  });

  /* summary */
  const sum = d.summary;
  $("bullN").textContent = sum.bull;
  $("neutralN").textContent = sum.neutral;
  $("bearN").textContent = sum.bear;
  const tot = Math.max(1, sum.bull + sum.neutral + sum.bear);
  $("segBull").style.width = (sum.bull / tot) * 100 + "%";
  $("segNeutral").style.width = (sum.neutral / tot) * 100 + "%";
  $("segBear").style.width = (sum.bear / tot) * 100 + "%";

  const v = $("verdict");
  v.textContent = sum.verdict;
  v.className = "verdict" + (sum.direction === "UP" ? " buy" : sum.direction === "DOWN" ? " sell" : "");

  const rsn = $("reason");
  if (rsn) {
    const c = sum.cats || {};
    const parts = Object.entries(c).map(([k, v]) => `<b>${k}</b> ${Number(v).toFixed(2)}`).join(" &nbsp;");
    rsn.innerHTML = `${sum.reason || ""} &nbsp;·&nbsp; ${parts}`;
  }

  const sc = Math.max(-1, Math.min(1, sum.score));
  const fill = $("scoreFill");
  const pct = Math.abs(sc) * 50;
  fill.style.width = pct + "%";
  fill.style.left = sc >= 0 ? "50%" : 50 - pct + "%";
  fill.classList.toggle("neg", sc < 0);
  $("scoreVal").textContent = (sc >= 0 ? "+" : "") + sc.toFixed(3);

  /* prediction */
  const p = d.prediction;
  $("horizon").textContent = p.horizon;
  renderHz(sum.horizon_min || 60);
  $("pNow").textContent = fmt(d.price, dec);
  const exp = p.exp_move_pct;
  $("pNowSub").innerHTML = `<span class="${exp >= 0 ? "green" : "red"}">target ${exp >= 0 ? "+" : ""}${exp.toFixed(3)}%</span> dalam ${p.horizon}`;
  $("pTarget").textContent = fmt(p.target, dec);
  $("pTarget").className = "pval " + (p.direction === "UP" ? "green" : p.direction === "DOWN" ? "red" : "yellow");
  $("pTargetSub").textContent = `${p.direction === "UP" ? "▲ bullish bias" : p.direction === "DOWN" ? "▼ bearish bias" : "● netral"} · ${sum.voters} voter / ${d.signals.length} indikator`;
  $("pRange").textContent = `${fmt(p.lo, dec)} — ${fmt(p.hi, dec)}`;
  $("pRangeSub").textContent = `± ${fmt((p.hi - p.lo) / 2, dec)} · band ATR-based`;
  $("pConf").textContent = p.confidence + "%";
  $("confFill").style.width = p.confidence + "%";
  const dir = $("pDir");
  dir.textContent = p.direction;
  dir.className = "dirchip" + (p.direction === "UP" ? " up" : p.direction === "DOWN" ? " down" : "");

  /* ml + sentiment */
  $("mlStatus").textContent = d.ml.status === "live" ? "trained" : d.ml.status;
  $("mlProb").textContent = d.ml.prob === null || d.ml.prob === undefined ? "—" : (d.ml.prob * 100).toFixed(1) + "%";
  $("mlN").textContent = d.ml.n || "—";
  const seb = d.signals.find((s) => s.key === "sentiment");
  $("fng").textContent = seb ? seb.value : "—";
  $("srcNote").textContent = `${d.source} · depth20@1000ms · kline_1m`;
  const vn = $("voterNote");
  if (vn) vn.textContent = `voter aktif: ${sum.voters ?? 0}/${d.signals.length} · bobot = |IC| × 12 (audit 14 hari), arah = sign(IC) · ambang gate ${(sum.gate_threshold ?? 0).toFixed(2)}`;
  const bt = sum.backtest || {};
  const bn = $("btNote");
  if (bn && bt.hit) {
    const afterFee = (bt.edge - (sum.fee_pct ?? 0.1)).toFixed(3);
    bn.innerHTML = `backtest ${(bt.n || 0).toLocaleString("en-US")} sampel (${sum.horizon_min}m, ${bt.mode}): ` +
      `hit <b>${bt.hit}%</b> · edge ${bt.edge >= 0 ? "+" : ""}${bt.edge}%/trade · setelah fee 0.10% = ${afterFee}%`;
  }

  /* stats */
  if (stats) {
    $("accVal").textContent = stats.accuracy === null ? "—" : stats.accuracy + "%";
    $("accTotal").textContent = stats.total;
    $("accPending").textContent = stats.pending;
    const r = $("recent");
    r.innerHTML = "";
    (stats.recent || []).forEach((x) => {
      const d2 = new Date(x.ts);
      const el = document.createElement("span");
      el.className = "pill " + (x.hit ? "hit" : "miss");
      el.textContent = `${x.direction === "WAIT" ? "—" : x.direction} ${x.hit ? "✓" : "✗"} ${d2.getHours().toString().padStart(2, "0")}:${d2.getMinutes().toString().padStart(2, "0")}`;
      el.title = `entry ${x.price} → target ${x.target} · actual ${x.resolved}`;
      r.appendChild(el);
    });
  }

  const st = (status || {});
  $("footMid").textContent = `binance ${st.binance_ws || "?"} · gold ${st.gold_feed || "?"} · ${new Date(d.ts).toLocaleTimeString("id-ID")} · ${d.signals.length} indikator`;
  document.title = `${fmt(d.price, dec)} ${d.symbol.replace("USDT", "/USDT")} · CryptoPulse`;
  updateCountdown();
}

let tabsBuilt = false;
function buildTabsIfNeeded(list) {
  const key = (list || []).map((x) => x.symbol).join(",");
  if (!list || !list.length || state.tabKey === key) return;
  buildTabs(list);
  state.tabKey = key;
}

/* ---------------- countdown ---------------- */
function updateCountdown() {
  const now = Date.now();
  const win = 15 * 60 * 1000;
  const left = win - (now % win);
  const m = Math.floor(left / 60000);
  const s = Math.floor((left % 60000) / 1000);
  $("pCountdown").textContent = `window ${m}:${s.toString().padStart(2, "0")}`;
}
setInterval(updateCountdown, 1000);
setInterval(() => {
  const d = new Date();
  $("clock").textContent = d.toLocaleTimeString("en-GB", { timeZone: "Asia/Jakarta" });
}, 1000);

/* ---------------- chart ---------------- */
const cv = $("chart");
const ctx = cv.getContext("2d");

function drawChart() {
  const bars = state.chart;
  if (!cv || !bars || bars.length < 5) return;
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth, h = 220;
  if (!w || w < 20) return;               // jangan clear canvas kalau layout belum siap
  if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const padL = 6, padR = 64, padT = 10, padB = 18;
  const cw = w - padL - padR, ch = h - padT - padB;
  const pred = state.data?.prediction;
  const closes = bars.map((b) => b[4]);
  let hi = Math.max(...bars.map((b) => b[2]));
  let lo = Math.min(...bars.map((b) => b[3]));
  if (pred) { hi = Math.max(hi, pred.hi); lo = Math.min(lo, pred.lo); }
  const pad = (hi - lo) * 0.08 || 1;
  hi += pad; lo -= pad;
  const y = (p) => padT + ch - ((p - lo) / (hi - lo)) * ch;
  const slot = cw / (bars.length + 1);   // 1 slot kosong di kanan biar candle terakhir tidak terpotong
  const bw = slot;

  // grid + price labels
  ctx.font = "10px JetBrains Mono, monospace";
  ctx.textAlign = "left";
  for (let i = 0; i <= 4; i++) {
    const price = lo + ((hi - lo) * i) / 4;
    const yy = y(price);
    ctx.strokeStyle = "rgba(22,39,63,.75)";
    ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(padL + cw, yy); ctx.stroke();
    ctx.fillStyle = "#5b6982";
    ctx.textAlign = "left";
    ctx.fillText(fmtPrice(price), padL + cw + 8, yy + 3);
  }

  // prediction band on the right edge
  if (pred) {
    const xTarget = padL + cw * 0.985;
    ctx.fillStyle = "rgba(255,207,92,.07)";
    ctx.fillRect(padL + cw * 0.86, y(pred.hi), cw * 0.14, y(pred.lo) - y(pred.hi));
    ctx.strokeStyle = pred.direction === "UP" ? "rgba(44,228,164,.85)" : pred.direction === "DOWN" ? "rgba(255,92,122,.85)" : "rgba(255,207,92,.85)";
    ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(padL + cw * 0.86, y(pred.target)); ctx.lineTo(padL + cw, y(pred.target)); ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.fillText(fmtPrice(pred.target), padL + cw + 6, y(pred.target) + 3);
  }

  // candles
  bars.forEach((b, i) => {
    const [t, o, hh, ll, c] = b;
    const x = padL + i * bw + bw / 2;
    const up = c >= o;
    ctx.strokeStyle = up ? "rgba(44,228,164,.9)" : "rgba(255,92,122,.9)";
    ctx.fillStyle = up ? "rgba(44,228,164,.85)" : "rgba(255,92,122,.85)";
    ctx.beginPath(); ctx.moveTo(x, y(hh)); ctx.lineTo(x, y(ll)); ctx.stroke();
    const bodyT = y(Math.max(o, c)), bodyB = y(Math.min(o, c));
    const bodyH = Math.max(1, bodyB - bodyT);
    ctx.fillRect(x - Math.max(1, bw * 0.3), bodyT, Math.max(2, bw * 0.6), bodyH);
  });

  // last price line
  const last = closes[closes.length - 1];
  const ly = y(last);
  ctx.strokeStyle = "rgba(232,238,251,.35)";
  ctx.setLineDash([2, 3]);
  ctx.beginPath(); ctx.moveTo(padL, ly); ctx.lineTo(padL + cw, ly); ctx.stroke();
  ctx.setLineDash([]);

  // time labels
  ctx.fillStyle = "#5b6982";
  const step = Math.ceil(bars.length / 6);
  for (let i = 0; i < bars.length; i += step) {
    const d = new Date(bars[i][0]);
    const lx = Math.max(padL, Math.min(padL + cw - 30, padL + i * bw - 10));
    ctx.fillText(`${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`, lx, h - 5);
  }
}

function fmtPrice(p) {
  const dec = state.decimals ?? 2;
  return Number(p).toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

/* refresh chart bars periodically */
setInterval(async () => {
  try {
    const r = await fetch(`/api/chart/${state.symbol}?bars=180`);
    const j = await r.json();
    if (j.chart) { state.chart = j.chart; drawChart(); }
  } catch (e) {}
}, 15000);

window.addEventListener("resize", drawChart);
setInterval(drawChart, 1000);   // jaring pengaman: chart selalu tergambar
if (window.ResizeObserver) new ResizeObserver(() => drawChart()).observe(document.querySelector(".herochart"));
setInterval(() => state.ws && state.ws.readyState === 1 && state.ws.send("ping"), 20000);

connect();
