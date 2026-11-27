"""CryptoPulse - dashboard sinyal & prediksi harga kripto + XAU/USD (live).

Jalankan:  python app.py [--open]   ->  http://127.0.0.1:8099
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import traceback
import webbrowser
from contextlib import asynccontextmanager

import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import engine as E

HERE = os.path.dirname(os.path.abspath(__file__))
WS_BINANCE = "wss://data-stream.binance.vision/stream?streams="
PORT = int(os.environ.get("CRYPTOPULSE_PORT", "8099"))

states: dict[str, E.SymbolState] = {s: E.SymbolState(s, E.SOURCES[s]) for s in E.PAIRS}
clients: dict[str, set[WebSocket]] = {s: set() for s in E.PAIRS}
BINANCE_SYMS = [s for s in E.PAIRS if E.SOURCES[s] == "binance"]
GOLD_SYMS = [s for s in E.PAIRS if E.SOURCES[s] == "gold"]
db_lock = asyncio.Lock()
status = {"binance_ws": "connecting", "gold_feed": "connecting", "last_msg": 0, "errors": []}


def push_error(msg: str):
    status["errors"] = ([msg] + status["errors"])[:5]
    print("[err]", msg)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    await bootstrap()
    asyncio.create_task(binance_stream())
    asyncio.create_task(gold_poller())
    asyncio.create_task(periodic())
    yield


app = FastAPI(title="CryptoPulse", lifespan=lifespan)


@app.middleware("http")
async def no_cache(request, call_next):
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")


# ------------------------------------------------------------------ bootstrap
async def bootstrap():
    E.db().close()
    sem = asyncio.Semaphore(6)

    async def one(sym: str, st: E.SymbolState):
        async with sem:
            try:
                await asyncio.to_thread(st.load_klines, 1000)
                await asyncio.to_thread(st.load_ticker)
                await asyncio.to_thread(
                    st.ml.predict,
                    [k["o"] for k in st.klines], [k["h"] for k in st.klines],
                    [k["l"] for k in st.klines], [k["c"] for k in st.klines],
                    [k["v"] for k in st.klines], [k["tb"] for k in st.klines], True,
                )
                st.build_state()
                print(f"[boot] {sym} price={st.price} bars={len(st.klines)} ml={st.ml.status}")
            except Exception as e:  # noqa: BLE001
                push_error(f"bootstrap {sym}: {type(e).__name__}: {e}")

    await asyncio.gather(*(one(sym, st) for sym, st in states.items()))
    try:
        await asyncio.to_thread(states[E.PAIRS[0]].load_sentiment)
    except Exception as e:  # noqa: BLE001
        push_error(f"sentiment: {type(e).__name__}: {e}")


# ------------------------------------------------------------------ binance ws
async def binance_stream():
    streams = "/".join(f"{s.lower()}@kline_1m/{s.lower()}@depth20@1000ms" for s in BINANCE_SYMS)
    url = WS_BINANCE + streams
    while True:
        try:
            async with websockets.connect(url, open_timeout=20, ping_interval=20) as ws:
                status["binance_ws"] = "live"
                print(f"[ws] terhubung: {len(BINANCE_SYMS)} simbol, {len(BINANCE_SYMS)*2} stream")
                async for raw in ws:
                    msg = json.loads(raw)
                    stream = msg.get("stream", "")
                    data = msg.get("data", {})
                    sym = stream.split("@")[0].upper()
                    st = states.get(sym)
                    if not st:
                        continue
                    status["last_msg"] = int(time.time() * 1000)
                    if "@kline" in stream:
                        st.patch_kline(data["k"])
                    elif "@depth" in stream:
                        st.set_depth(data.get("bids", []), data.get("asks", []))
                    await broadcast_tick(sym)
        except Exception as e:  # noqa: BLE001
            status["binance_ws"] = "reconnect"
            push_error(f"binance ws: {type(e).__name__}: {e}")
            await asyncio.sleep(3)


# ------------------------------------------------------------------ gold feed
async def gold_poller():
    """XAU/USD tidak ada di Binance spot -> tick dari gold-api.com tiap 5 detik."""
    while True:
        for sym in GOLD_SYMS:
            st = states[sym]
            try:
                d = await asyncio.to_thread(E.http_json, E.GOLD_TICK_URL, 8.0)
                price = float(d.get("price") or 0)
                if price > 0:
                    st.add_tick(price)
                    status["gold_feed"] = "live"
                    status["last_msg"] = int(time.time() * 1000)
                    await broadcast_tick(sym)
                else:
                    status["gold_feed"] = "kosong"
            except Exception as e:  # noqa: BLE001
                status["gold_feed"] = "reconnect"
                push_error(f"gold tick {sym}: {type(e).__name__}: {e}")
                await asyncio.sleep(8)
        await asyncio.sleep(5)


async def broadcast_tick(sym: str):
    st = states[sym]
    if not clients[sym] or st.price is None:
        return
    payload = json.dumps({"type": "tick", "symbol": sym, "price": st.price,
                          "ts": int(time.time() * 1000)})
    for ws in list(clients[sym]):
        try:
            await ws.send_text(payload)
        except Exception:  # noqa: BLE001
            clients[sym].discard(ws)


# ------------------------------------------------------------------ periodic
async def periodic():
    """Build state tiap 3s, refresh data (crypto 90s / gold 300s), resolve prediksi 60s."""
    last_refresh = 0.0
    last_gold = 0.0
    last_resolve = 0.0
    while True:
        try:
            now = time.time()
            if now - last_refresh > 90:
                for sym, st in states.items():
                    if st.source != "binance":
                        continue
                    try:
                        await asyncio.to_thread(st.load_klines, 1000)
                        await asyncio.to_thread(st.load_ticker)
                    except Exception as e:  # noqa: BLE001
                        push_error(f"refresh {st.symbol}: {type(e).__name__}: {e}")
                try:
                    await asyncio.to_thread(states[E.PAIRS[0]].load_sentiment)
                except Exception as e:  # noqa: BLE001
                    push_error(f"sentiment: {type(e).__name__}: {e}")
                last_refresh = now

            if now - last_gold > 300:
                for sym in GOLD_SYMS:
                    st = states[sym]
                    try:
                        await asyncio.to_thread(st.load_klines_gold, 480)
                        await asyncio.to_thread(st.load_ticker)
                    except Exception as e:  # noqa: BLE001
                        push_error(f"gold series {sym}: {type(e).__name__}: {e}")
                last_gold = now

            async with db_lock:
                con = E.db()
                try:
                    for sym, st in states.items():
                        if not st.klines:
                            continue
                        state = await asyncio.to_thread(st.build_state)
                        if not state:
                            continue
                        E.log_prediction(con, state)
                        if clients[sym]:
                            payload = json.dumps({
                                "type": "state",
                                "state": state,
                                "stats": E.stats(con, sym),
                                "status": status,
                            })
                            for ws in list(clients[sym]):
                                try:
                                    await ws.send_text(payload)
                                except Exception:  # noqa: BLE001
                                    clients[sym].discard(ws)
                    if now - last_resolve > 55:
                        E.resolve_predictions(con, states)
                        last_resolve = now
                finally:
                    con.close()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        await asyncio.sleep(3)


# ------------------------------------------------------------------ http api
@app.get("/")
async def index():
    return FileResponse(os.path.join(HERE, "static", "index.html"))


@app.get("/api/state/{symbol}")
async def api_state(symbol: str):
    sym = symbol.upper()
    if sym not in states:
        return JSONResponse({"error": "unknown symbol"}, status_code=404)
    st = states[sym]
    state = st.state or await asyncio.to_thread(st.build_state)
    con = E.db()
    try:
        s = E.stats(con, sym)
    finally:
        con.close()
    return {"state": state, "chart": st.chart(), "stats": s, "status": status}


@app.get("/api/chart/{symbol}")
async def api_chart(symbol: str, bars: int = 180):
    sym = symbol.upper()
    if sym not in states:
        return JSONResponse({"error": "unknown symbol"}, status_code=404)
    return {"chart": states[sym].chart(bars)}


@app.api_route("/api/horizon/{minutes}", methods=["GET", "POST"])
async def api_horizon(minutes: int):
    h = E.set_horizon(minutes)
    for st in states.values():          # reset cache kalibrasi + model
        st.ml.trained_at = 0.0
        st.ml.model = None
        st.ml.prob = None
        st.ic = {}
        st.ic_at = 0.0
        st.last_build = 0.0
        st.state = None
    await asyncio.to_thread(E.refresh_sentiment)
    return {"horizon": h, "backtest": E.BACKTEST.get(h, {})}


@app.get("/api/instruments")
async def api_instruments():
    return {"instruments": E.INSTRUMENTS, "sources": E.SOURCES}


@app.get("/api/health")
async def health():
    return {
        "ok": True, "ts": int(time.time() * 1000), "status": status,
        "instruments": len(E.INSTRUMENTS), "horizon_min": E.HORIZON_MIN,
        "pairs": {s: {"price": st.price, "bars": len(st.klines), "source": st.source,
                      "ml": st.ml.status, "last_build": int(st.last_build)}
                  for s, st in states.items()},
    }


@app.websocket("/ws/{symbol}")
async def ws_endpoint(ws: WebSocket, symbol: str):
    sym = symbol.upper()
    if sym not in states:
        await ws.close()
        return
    await ws.accept()
    clients[sym].add(ws)
    st = states[sym]
    con = E.db()
    try:
        state = st.state or await asyncio.to_thread(st.build_state)
        await ws.send_text(json.dumps({
            "type": "init", "state": state, "chart": st.chart(),
            "stats": E.stats(con, sym), "status": status,
        }))
    finally:
        con.close()
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        clients[sym].discard(ws)


def open_browser_later(url: str, delay: float = 2.5):
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_open, daemon=True).start()


if __name__ == "__main__":
    import uvicorn

    url = f"http://127.0.0.1:{PORT}"
    print(f"\n  CryptoPulse  ->  {url}   ({len(E.INSTRUMENTS)} instrumen)\n")
    if "--open" in sys.argv:
        open_browser_later(url)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
