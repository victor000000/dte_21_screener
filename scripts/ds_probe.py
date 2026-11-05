"""ds_probe.py — liveness probes for the LOCAL services (IBKR, Futu, ThetaData).

Split out of ds_health.py for the 100-line cap. Each probe answers "is this source actually
USABLE", not "is a port open", because for all three of these the two differ:

  * IBKR   — `isConnected()` stays True while the gateway's link to IBKR is dead, so a socket
             test is a FALSE GREEN. Needs a real handshake (reqCurrentTime).
  * Futu   — OpenD accepts the TCP connection before it is usable. Needs a context call.
  * Theta  — the Java terminal must be RUNNING locally on 127.0.0.1:25503; a reachable host
             proves nothing about the terminal.

Every probe records its verdict via `record()` and returns it, so callers can branch.
"""
import os
import pathlib
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))  # repo root

import bootstrap  # Configure native broker endpoints before loading adapters.

RESULTS = []


def record(name, ok, detail="", secs=0.0, required=True):
    RESULTS.append({"source": name, "ok": bool(ok), "detail": detail,
                    "secs": round(secs, 3), "required": required})
    return ok


def tcp(host, port, timeout=4.0):
    t0 = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, time.time() - t0, ""
    except Exception as e:
        return False, time.time() - t0, f"{type(e).__name__}: {str(e)[:50]}"


def probe_ibkr(quick):
    from datasources import tws
    host = os.environ.get("IB_HOST", tws.HOST)
    if quick:
        open_ports = [p for p in (4001, 4002, 7496, 7497) if tcp(host, p)[0]]
        return record("tws", bool(open_ports), f"ports open: {open_ports or 'none'}")
    t0 = time.time()
    try:
        from ib_async import IB
        ib = IB()
        ib.RequestTimeout = 20
        ib.connect(host, int(os.environ.get("IB_PORT", 4001)), clientId=97, timeout=15,
                   readonly=True)
        now = ib.reqCurrentTime()
        ib.disconnect()
        return record("tws", True, f"handshake ok, server={now}", time.time() - t0)
    except Exception as e:
        return record("tws", False, f"{type(e).__name__}: {str(e)[:60]}", time.time() - t0)


def probe_futu(quick):
    host = os.environ.get("FUTU_HOST", "host.docker.internal")
    ok, el, err = tcp(host, 11111)
    if not ok or quick:
        return record("futu_opend", ok, err or "tcp open", el)
    t0 = time.time()
    try:
        from futu import OpenQuoteContext
        ctx = OpenQuoteContext(host=host, port=11111)
        ret, _ = ctx.get_global_state()
        ctx.close()
        return record("futu_opend", ret == 0, f"get_global_state ret={ret}", time.time() - t0)
    except Exception as e:
        return record("futu_opend", False, f"{type(e).__name__}: {str(e)[:60]}",
                      time.time() - t0)


def probe_thetadata(quick):
    proc = subprocess.run(["pgrep", "-f", "ThetaTerminal"], capture_output=True, text=True)
    running = bool(proc.stdout.strip())
    ok, el, err = tcp("127.0.0.1", 25503)
    if not ok:
        return record("thetadata", False,
                      f"terminal {'running but ' if running else ''}port 25503 closed: {err}", el)
    if quick:
        return record("thetadata", True, "terminal up, port open", el)
    t0 = time.time()
    try:
        from datasources.thetadata import get_client
        avail = get_client().terminal_available()
        return record("thetadata", bool(avail), f"terminal_available={avail} (EOD tier)",
                      time.time() - t0)
    except Exception as e:
        return record("thetadata", False, f"{type(e).__name__}: {str(e)[:60]}", time.time() - t0)
