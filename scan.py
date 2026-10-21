"""One-shot scan for GitHub Actions. Alerts only, no trading.
M1, M5, M15 must agree (all BUY or all SELL) + at least one of H1/H4/D1 agrees.
Secrets: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
"""
import asyncio, json, os, time
import requests, websockets

TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
APP_ID = os.environ.get("DERIV_APP_ID", "1089")
ENDPOINTS = [
    f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}",
    f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}",
]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
LOWER = {"M1": 60, "M5": 300, "M15": 900}
HIGHER = {"H1": 3600, "H4": 14400, "D1": 86400}

def sma(v, n): return sum(v[-n:]) / n
def ema(v, n):
    k = 2 / (n + 1); e = sum(v[:n]) / n; out = [e]
    for x in v[n:]:
        e = x * k + e * (1 - k); out.append(e)
    return out

def direction(c):
    e = ema(c, 10); now, prev = e[-1], e[-2]
    s10, s20 = sma(c, 10), sma(c, 20)
    if now > s10 and now > s20 and now > prev: return "BUY"
    if now < s10 and now < s20 and now < prev: return "SELL"
    return "NEUTRAL"

async def call(ws, p):
    await ws.send(json.dumps(p)); return json.loads(await ws.recv())

async def connect():
    last = None
    for attempt in range(3):
        for url in ENDPOINTS:
            try:
                return await websockets.connect(url, origin="https://api.deriv.com",
                                                extra_headers=HEADERS, open_timeout=20)
            except Exception as ex:
                last = ex
                print("connect failed", url, ex)
        await asyncio.sleep(5)
    raise last

async def scan():
    res = []
    ws = await connect()
    async with ws:
        r = await call(ws, {"active_symbols": "brief", "product_type": "basic"})
        syms = [s["symbol"] for s in r.get("active_symbols", [])
                if s.get("market") == "synthetic_index" and not s.get("is_trading_suspended")]
        for sym in syms:
            try:
                d = {}
                for name, g in {**LOWER, **HIGHER}.items():
                    h = await call(ws, {"ticks_history": sym, "style": "candles",
                                        "granularity": g, "count": 60, "end": "latest"})
                    c = [float(x["close"]) for x in h.get("candles", [])]
                    d[name] = direction(c) if len(c) >= 30 else "NEUTRAL"
                low = {d[k] for k in LOWER}
                if len(low) == 1 and "NEUTRAL" not in low:
                    dr = low.pop(); agree = [k for k in HIGHER if d[k] == dr]
                    if agree: res.append((sym, dr, agree))
            except Exception as ex:
                print("skip", sym, ex)
    return res

def report(res):
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    if not res: return f"Hourly scan {stamp}\nNo synthetics aligned right now."
    lines = [f"Hourly scan {stamp}", f"{len(res)} aligned:"]
    for sym, d, agree in sorted(res, key=lambda x: x[1]):
        lines.append(f"{'🟢' if d=='BUY' else '🔴'} {sym}: {d} (M1/M5/M15 + {', '.join(agree)})")
    return "\n".join(lines)

if __name__ == "__main__":
    text = report(asyncio.run(scan()))
    print(text)
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  data={"chat_id": CHAT_ID, "text": text}, timeout=15).raise_for_status()
