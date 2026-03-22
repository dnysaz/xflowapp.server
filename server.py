"""
server.py — xflow server utama.

Jalankan via manage.py:
  python manage.py start    ← jalankan background, simpan PID
  python manage.py stop     ← matikan server
  python manage.py restart  ← restart
  python manage.py log      ← lihat log akses IP
  python manage.py status   ← cek apakah server aktif
"""

import asyncio
import base64
import json
import logging
import os
import time
import uuid

import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from aiohttp import web

from tunnel import TunnelManager
from tunnel_store import register, is_owner

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────

PUBLIC_HOST = os.environ.get("XFLOW_HOST", "145.79.12.100")
HTTP_PORT   = int(os.environ.get("XFLOW_HTTP_PORT", 8080))
WS_PORT     = int(os.environ.get("XFLOW_WS_PORT", 8081))
AUTH_TOKEN  = os.environ.get("XFLOW_TOKEN", "")
LOG_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "access.log")
HTML_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "html")
WELCOME_PARAM  = "_xflow_ready"   # jika query param ini ada, skip welcome page
RESERVED_PATHS = {"status", "ws", "api", "favicon.ico", "robots.txt"}  # paths that are not tunnel IDs


def _read_html(filename: str, fallback: str) -> str:
    """Baca file HTML dari folder html/, fallback ke string jika tidak ada."""
    path = os.path.join(HTML_DIR, filename)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return fallback

# ──────────────────────────────────────────────
# Logging — console + file
# ──────────────────────────────────────────────

fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

_console = logging.StreamHandler()
_console.setFormatter(fmt)

_file = logging.FileHandler(LOG_FILE)
_file.setFormatter(fmt)

logging.basicConfig(level=logging.INFO, handlers=[_console, _file])
log = logging.getLogger("xflow-server")

access_log = logging.getLogger("xflow-access")
access_log.setLevel(logging.INFO)
access_log.addHandler(_file)
access_log.propagate = False

# ──────────────────────────────────────────────
# State
# ──────────────────────────────────────────────

manager = TunnelManager()

# tunnel_ids that have welcome page disabled (toggled via /api/welcome)
welcome_disabled: set[str] = set()


def check_token(token: str) -> bool:
    if not AUTH_TOKEN:
        return True
    return token == AUTH_TOKEN


# ──────────────────────────────────────────────
# WebSocket handler
# ──────────────────────────────────────────────

async def ws_handler(websocket):
    remote = websocket.remote_address
    log.info(f"Client konek dari {remote[0]}")

    try:
        raw = await asyncio.wait_for(websocket.recv(), timeout=10)
        msg = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError):
        await websocket.send(json.dumps({"type": "error", "message": "handshake timeout atau format salah"}))
        return

    if msg.get("type") != "hello":
        await websocket.send(json.dumps({"type": "error", "message": "expected hello"}))
        return

    if not check_token(msg.get("token", "")):
        await websocket.send(json.dumps({"type": "error", "message": "token tidak valid"}))
        log.warning(f"Token salah dari {remote[0]}")
        return

    # ── Persistent tunnel ID ──
    token        = msg.get("token", "")
    requested_id = msg.get("tunnel_id", "").strip().lower() or None

    if requested_id:
        # Check if ID is already active in another connection
        if manager.get(requested_id):
            await websocket.send(json.dumps({
                "type": "error",
                "message": f"Tunnel '{requested_id}' is already in use. Please use another name.",
            }))
            return

        # Validate ownership via tunnel_store (SQLite)
        if not register(requested_id, token):
            await websocket.send(json.dumps({
                "type": "error",
                "message": f"Tunnel '{requested_id}' is already owned by another client.",
            }))
            log.warning(f"Claim rejected for tunnel '{requested_id}' from {remote[0]}")
            return

    tunnel = manager.create(websocket, tunnel_id=requested_id)
    public_url = f"http://{PUBLIC_HOST}:{HTTP_PORT}/{tunnel.tunnel_id}/"

    await websocket.send(json.dumps({
        "type": "welcome",
        "tunnel_id": tunnel.tunnel_id,
        "url": public_url,
    }))

    log.info(f"Tunnel [{tunnel.tunnel_id}] aktif — {public_url}")

    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "response":
                tunnel.resolve_pending(msg["request_id"], msg)
            elif msg.get("type") == "ping":
                await websocket.send(json.dumps({"type": "pong"}))

    except (ConnectionClosedOK, ConnectionClosedError):
        pass
    finally:
        manager.remove(tunnel.tunnel_id)
        log.info(f"Tunnel [{tunnel.tunnel_id}] ditutup")


# ──────────────────────────────────────────────
# HTTP Proxy handler
# ──────────────────────────────────────────────

COOKIE_NAME = "xflow_tid"   # stores active tunnel_id in browser cookie


async def proxy_handler(request: web.Request) -> web.Response:
    tunnel_id = request.match_info["tunnel_id"]

    # Don't intercept reserved system paths
    if tunnel_id in RESERVED_PATHS:
        return web.Response(status=404, text="Not found")

    path = "/" + request.match_info.get("path", "")
    if request.query_string:
        path += "?" + request.query_string

    client_ip = request.headers.get("X-Forwarded-For", request.remote)

    # ── Smart tunnel resolution ──
    # If tunnel_id is not a known tunnel, check if the browser has a cookie
    # pointing to an active tunnel — this handles internal app redirects like
    # /login, /dashboard, /api/... that Laravel/Next.js etc. redirect to.
    tunnel = manager.get(tunnel_id)
    if not tunnel:
        # Try cookie
        cookie_tid = request.cookies.get(COOKIE_NAME)
        if cookie_tid and manager.get(cookie_tid):
            # Rewrite: treat the whole path as /<tunnel_id>/<original_path>
            full_path = "/" + tunnel_id + path
            tunnel_id = cookie_tid
            path      = full_path
            tunnel    = manager.get(tunnel_id)
        else:
            access_log.info(f"ACCESS {client_ip} {request.method} /{tunnel_id}{path} 404 [tunnel tidak ada]")
            html_404 = _read_html("404.html", f"<h3>404 — tunnel '{tunnel_id}' not found.</h3>")
            return web.Response(status=404, content_type="text/html", text=html_404)

    is_asset = any(path.endswith(ext) for ext in (
        ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg",
        ".ico", ".woff", ".woff2", ".ttf", ".map", ".json",
    ))

    # Welcome page on first visit
    if (
        request.method == "GET"
        and not is_asset
        and WELCOME_PARAM not in request.query_string
        and path in ("/", "")
        and tunnel_id not in welcome_disabled
    ):
        html_welcome = _read_html("welcome.html", "<meta http-equiv='refresh' content='0'>")
        resp = web.Response(status=200, content_type="text/html", text=html_welcome)
        resp.set_cookie(COOKIE_NAME, tunnel_id, max_age=86400, samesite="Lax")
        return resp

    body_bytes = await request.read()
    body_b64 = base64.b64encode(body_bytes).decode() if body_bytes else ""

    request_id = str(uuid.uuid4())[:8]
    headers = dict(request.headers)
    for h in ("host", "connection", "transfer-encoding"):
        headers.pop(h, None)

    payload = {
        "type": "request",
        "request_id": request_id,
        "method": request.method,
        "path": path,
        "headers": headers,
        "body": body_b64,
    }

    fut = tunnel.add_pending(request_id)

    try:
        await tunnel.websocket.send(json.dumps(payload))
    except Exception as e:
        tunnel.cancel_pending(request_id)
        access_log.info(f"ACCESS {client_ip} {request.method} /{tunnel_id}{path} 502 [gagal kirim ke tunnel]")
        return web.Response(status=502, text=f"xflow: gagal kirim ke tunnel — {e}")

    try:
        resp_data = await asyncio.wait_for(fut, timeout=30)
    except asyncio.TimeoutError:
        access_log.info(f"ACCESS {client_ip} {request.method} /{tunnel_id}{path} 504 [timeout]")
        return web.Response(status=504, text="xflow: timeout menunggu response dari client")
    except Exception as e:
        access_log.info(f"ACCESS {client_ip} {request.method} /{tunnel_id}{path} 502 [tunnel error]")
        return web.Response(status=502, text=f"xflow: tunnel error — {e}")

    status = resp_data.get("status", 200)
    resp_body = base64.b64decode(resp_data.get("body", "")) if resp_data.get("body") else b""
    resp_headers = resp_data.get("headers", {})
    for h in ("transfer-encoding", "connection", "content-encoding"):
        resp_headers.pop(h, None)
        resp_headers.pop(h.title(), None)

    size = len(resp_body)
    access_log.info(f"ACCESS {client_ip} {request.method} /{tunnel_id}{path} {status} {size}b")

    response = web.Response(status=status, headers=resp_headers, body=resp_body)
    # Set cookie so subsequent internal redirects (e.g. /login) resolve correctly
    response.set_cookie(COOKIE_NAME, tunnel_id, max_age=86400, samesite="Lax")
    return response


async def status_handler(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok",
        "host": PUBLIC_HOST,
        "tunnels": manager.count,
        "tunnel_list": manager.list_all(),
    })


async def welcome_toggle_handler(request: web.Request) -> web.Response:
    """Toggle welcome page on/off for a tunnel. Called from dashboard."""
    tunnel_id = request.match_info.get("tunnel_id", "")
    action    = request.match_info.get("action", "")  # "on" or "off"
    if not tunnel_id:
        return web.json_response({"error": "missing tunnel_id"}, status=400)
    if action == "off":
        welcome_disabled.add(tunnel_id)
    elif action == "on":
        welcome_disabled.discard(tunnel_id)
    return web.json_response({"tunnel_id": tunnel_id, "welcome": action != "off"})


async def home_handler(request: web.Request) -> web.Response:
    """Landing page untuk / dan /proxy/ agar tidak muncul error 404 default."""
    html = _read_html("home.html", "<h2>xflow server is running.</h2>")
    html = html.replace("{{ host }}", f"{PUBLIC_HOST}:{HTTP_PORT}")
    return web.Response(status=200, content_type="text/html", text=html)


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

async def main():
    app = web.Application()
    app.router.add_get("/", home_handler)
    app.router.add_get("/status", status_handler)
    app.router.add_post("/api/welcome/{tunnel_id}/{action}", welcome_toggle_handler)
    app.router.add_route("*", "/{tunnel_id}/{path:.*}", proxy_handler)
    app.router.add_route("*", "/{tunnel_id}", proxy_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HTTP_PORT)
    await site.start()
    log.info(f"HTTP proxy    : http://0.0.0.0:{HTTP_PORT}  (publik: http://{PUBLIC_HOST}:{HTTP_PORT})")

    ws_server = await websockets.serve(ws_handler, "0.0.0.0", WS_PORT)
    log.info(f"WebSocket     : ws://0.0.0.0:{WS_PORT}")
    log.info(f"Auth token    : {'aktif' if AUTH_TOKEN else 'nonaktif (mode dev)'}")
    log.info(f"Access log    : {LOG_FILE}")
    log.info("xflow-server siap. Tekan Ctrl+C untuk berhenti.")

    try:
        await asyncio.Future()
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("Shutdown...")
    finally:
        ws_server.close()
        await ws_server.wait_closed()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())