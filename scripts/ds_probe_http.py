"""ds_probe_http.py — liveness probes for the HTTP sources, and Alpaca ENTITLEMENT.

Split out of ds_health.py for the 100-line cap.

The HTTP rule: 401 / 403 / 404 / 412 / 429 all prove the host ANSWERED, so only a transport
failure counts as down. A bare GET to Polygon returns 401 and to CZCE 412 — both healthy.

Alpaca is different and gets its own probe, because REACHABLE != USABLE there. This account's
option entitlement is independent of the network: on 2026-10-10 `data.alpaca.markets` answered
401-without-a-key and 200-for-stocks while returning **403 "OPRA agreement is not signed"** for
any RECENT option window. A reachability check alone called that healthy, which is exactly the
confusion that cost an hour.
"""
import pathlib
import bootstrap
import time

from scripts.ds_probe import record

ROOT = pathlib.Path(__file__).resolve().parents[1]


def probe_alpaca():
    """Reachability AND entitlement, reported separately. Returns (None, entitled)."""
    import json
    import urllib.error
    import urllib.request
    d = json.loads((bootstrap.DATA_ROOT / "secrets" / "alpaca.json").read_text())
    H = {"APCA-API-KEY-ID": d["key_id"], "APCA-API-SECRET-KEY": d["secret"]}
    t0 = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(
                "https://data.alpaca.markets/v2/stocks/SPY/bars?timeframe=1Day&limit=1",
                headers=H), timeout=15) as r:
            reach = r.status == 200
    except Exception as e:
        record("alpaca", False, f"unreachable: {type(e).__name__}", time.time() - t0)
        return None, None
    note, ent = "", None
    try:
        # A RECENT option window is the only probe that exercises the entitlement.
        with urllib.request.urlopen(urllib.request.Request(
                "https://data.alpaca.markets/v1beta1/options/bars?symbols=SPY261120C00700000"
                "&timeframe=1Day&start=2026-10-05&end=2026-10-09&limit=1", headers=H),
                timeout=15) as r:
            ent, note = True, "options OK"
    except urllib.error.HTTPError as e:
        ent = e.code != 403
        note = f"HTTP {e.code} {e.read(160).decode('utf-8', 'replace')}".strip()
    except Exception as e:
        note = f"{type(e).__name__}: {str(e)[:50]}"
    record("alpaca", reach, f"reachable; options: {note}", time.time() - t0)
    return None, ent


def probe_http():
    import requests
    for name, url, required in (
            ("yahoo", "https://query1.finance.yahoo.com/v8/finance/chart/SPY", True),
            ("massive", "https://api.polygon.io/v2/aggs/ticker/SPY/prev", True),
            ("tiingo", "https://api.tiingo.com", False),
            ("czce", "https://www.czce.com.cn", False),
            ("shfe", "https://www.shfe.com.cn", False),
            ("sina", "https://finance.sina.com.cn", False)):
        t0 = time.time()
        try:
            r = requests.get(url, timeout=12, allow_redirects=False)
            note = f"HTTP {r.status_code}" + (" (rate-limited)" if r.status_code == 429 else "")
            record(name, True, note, time.time() - t0, required=required)
        except Exception as e:
            record(name, False, f"{type(e).__name__}: {str(e)[:50]}", time.time() - t0,
                   required=required)
