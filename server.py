"""
server.py — xflow server utama.

Dua endpoint:
  WS  /ws/tunnel          ← xflow-client konek ke sini
  HTTP /proxy/<tunnel_id>/<path> ← request publik masuk ke sini (Phase 1)

Phase 2 nanti: subdomain-based routing via reverse proxy di depan (nginx/caddy).
Kode di sini tidak perlu diubah — hanya tambah layer di depannya.

Jalankan:
  python server.py [--host 0.0.0.0] [--port 8080] [--token mytoken]
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
import argparse

import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from aiohttp import web

from tunnel import TunnelManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("xflow-server")

manager = TunnelManager()

# ──────────────────────────────────────────────
# Auth
# ──────────────────────────────────────────────

AUTH_TOKEN = os.environ.get("XFLOW_TOKEN", "")


def check_token(token: str) -> bool:
    if not AUTH_TOKEN:
        return True  # Jika tidak di-set, bebas (mode dev)
    return token == AUTH_TOKEN


# ──────────────────────────────────────────────
# WebSocket handler (xflow-client konek ke sini)
# ──────────────────────────────────────────────

async def ws_handler(websocket):
    """
    Protocol handshake:
      client -> server : {"type": "hello", "token": "...", "version": "1"}
      server -> client : {"type": "welcome", "tunnel_id": "abc123", "url": "http://host:port/proxy/abc123/"}
                  atau : {"type": "error", "message": "..."}

    Setelah itu server mengirim request HTTP ke client:
      server -> client : {"type": "request", "request_id": "...", "method": "GET", "path": "/", "headers": {...}, "body": "...b64..."}
      client -> server : {"type": "response", "request_id": "...", "status": 200, "headers": {...}, "body": "...b64..."}
    """
    remote = websocket.remote_address
    log.info(f"Koneksi baru dari {remote}")

    # Handshake
    try:
        raw = await asyncio.wait_for(websocket.recv(), timeout=10)
        msg = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError) as e:
        await websocket.send(json.dumps({"type": "error", "message": "handshake timeout atau format salah"}))
        return

    if msg.get("type") != "hello":
        await websocket.send(json.dumps({"type": "error", "message": "expected hello"}))
        return

    if not check_token(msg.get("token", "")):
        await websocket.send(json.dumps({"type": "error", "message": "token tidak valid"}))
        log.warning(f"Token salah dari {remote}")
        return

    # Buat tunnel
    tunnel = manager.create(websocket)
    host = os.environ.get("XFLOW_HOST", "localhost")
    port = os.environ.get("XFLOW_PORT", "8080")
    public_url = f"http://{host}:{port}/proxy/{tunnel.tunnel_id}/"

    await websocket.send(json.dumps({
        "type": "welcome",
        "tunnel_id": tunnel.tunnel_id,
        "url": public_url,
    }))

    log.info(f"Tunnel [{tunnel.tunnel_id}] aktif → {public_url}")

    # Terima response dari client
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
# HTTP Proxy handler (request publik)
# ──────────────────────────────────────────────

import base64

async def proxy_handler(request: web.Request) -> web.Response:
    """
    URL format: /proxy/<tunnel_id>/<path>
    Semua request di-forward ke client via WebSocket tunnel.
    """
    tunnel_id = request.match_info["tunnel_id"]
    path = "/" + request.match_info.get("path", "")
    if request.query_string:
        path += "?" + request.query_string

    tunnel = manager.get(tunnel_id)
    if not tunnel:
        return web.Response(
            status=404,
            content_type="text/html",
            text=f"<h3>xflow: tunnel '{tunnel_id}' tidak ditemukan atau sudah tutup.</h3>"
        )

    # Baca body
    body_bytes = await request.read()
    body_b64 = base64.b64encode(body_bytes).decode() if body_bytes else ""

    # Siapkan payload request
    request_id = str(uuid.uuid4())[:8]
    headers = dict(request.headers)
    # Hapus hop-by-hop headers
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

    # Daftarkan future untuk response
    fut = tunnel.add_pending(request_id)

    try:
        await tunnel.websocket.send(json.dumps(payload))
    except Exception as e:
        tunnel.cancel_pending(request_id)
        return web.Response(status=502, text=f"xflow: gagal kirim ke tunnel — {e}")

    # Tunggu response dari client (timeout 30 detik)
    try:
        resp_data = await asyncio.wait_for(fut, timeout=30)
    except asyncio.TimeoutError:
        return web.Response(status=504, text="xflow: timeout menunggu response dari client")
    except Exception as e:
        return web.Response(status=502, text=f"xflow: tunnel error — {e}")

    # Decode response body
    resp_body = base64.b64decode(resp_data.get("body", "")) if resp_data.get("body") else b""
    resp_headers = resp_data.get("headers", {})

    # Hapus hop-by-hop headers dari response
    for h in ("transfer-encoding", "connection", "content-encoding"):
        resp_headers.pop(h, None)
        resp_headers.pop(h.title(), None)

    return web.Response(
        status=resp_data.get("status", 200),
        headers=resp_headers,
        body=resp_body,
    )


async def status_handler(request: web.Request) -> web.Response:
    """Simple status endpoint untuk cek server."""
    return web.json_response({
        "status": "ok",
        "tunnels": manager.count,
        "tunnel_list": manager.list_all(),
    })


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

async def main(host: str, http_port: int, ws_port: int, token: str):
    global AUTH_TOKEN
    if token:
        AUTH_TOKEN = token
        os.environ["XFLOW_TOKEN"] = token

    os.environ["XFLOW_HOST"] = host
    os.environ["XFLOW_PORT"] = str(http_port)

    # HTTP server (aiohttp)
    app = web.Application()
    app.router.add_get("/status", status_handler)
    app.router.add_route("*", "/proxy/{tunnel_id}/{path:.*}", proxy_handler)
    app.router.add_route("*", "/proxy/{tunnel_id}", proxy_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, http_port)
    await site.start()
    log.info(f"HTTP proxy berjalan di http://{host}:{http_port}")

    # WebSocket server
    ws_server = await websockets.serve(ws_handler, host, ws_port)
    log.info(f"WebSocket server berjalan di ws://{host}:{ws_port}")
    log.info(f"Auth token: {'aktif' if AUTH_TOKEN else 'nonaktif (mode dev)'}")
    log.info("xflow-server siap. Tekan Ctrl+C untuk berhenti.")

    try:
        await asyncio.Future()  # jalan selamanya
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("Shutdown...")
    finally:
        ws_server.close()
        await ws_server.wait_closed()
        await runner.cleanup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="xflow server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--http-port", type=int, default=8080, help="Port HTTP proxy (default: 8080)")
    parser.add_argument("--ws-port", type=int, default=8081, help="Port WebSocket (default: 8081)")
    parser.add_argument("--token", default="", help="Auth token (opsional, kosong = mode dev)")
    args = parser.parse_args()

    asyncio.run(main(args.host, args.http_port, args.ws_port, args.token))