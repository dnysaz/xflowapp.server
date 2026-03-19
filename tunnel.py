"""
tunnel.py — Kelola semua tunnel aktif.

Setiap tunnel punya:
- tunnel_id  : string unik (misal "abc123")
- websocket  : koneksi WebSocket ke xflow-client
- pending    : dict request_id -> asyncio.Future (untuk sinkronisasi response)
"""

import asyncio
import random
import string
import time


def generate_tunnel_id(length: int = 6) -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choices(chars, k=length))


class Tunnel:
    def __init__(self, tunnel_id: str, websocket):
        self.tunnel_id = tunnel_id
        self.websocket = websocket
        self.pending: dict[str, asyncio.Future] = {}
        self.created_at = time.time()

    def add_pending(self, request_id: str) -> asyncio.Future:
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self.pending[request_id] = fut
        return fut

    def resolve_pending(self, request_id: str, response_data: dict):
        fut = self.pending.pop(request_id, None)
        if fut and not fut.done():
            fut.set_result(response_data)

    def cancel_pending(self, request_id: str, reason: str = "tunnel closed"):
        fut = self.pending.pop(request_id, None)
        if fut and not fut.done():
            fut.set_exception(Exception(reason))


class TunnelManager:
    def __init__(self):
        # tunnel_id -> Tunnel
        self._tunnels: dict[str, Tunnel] = {}

    def create(self, websocket) -> Tunnel:
        # Pastikan tunnel_id unik
        while True:
            tid = generate_tunnel_id()
            if tid not in self._tunnels:
                break

        tunnel = Tunnel(tid, websocket)
        self._tunnels[tid] = tunnel
        return tunnel

    def get(self, tunnel_id: str) -> Tunnel | None:
        return self._tunnels.get(tunnel_id)

    def remove(self, tunnel_id: str):
        tunnel = self._tunnels.pop(tunnel_id, None)
        if tunnel:
            # Cancel semua request yang masih pending
            for rid in list(tunnel.pending.keys()):
                tunnel.cancel_pending(rid)

    def list_all(self) -> list[dict]:
        return [
            {
                "tunnel_id": t.tunnel_id,
                "created_at": t.created_at,
                "pending_requests": len(t.pending),
            }
            for t in self._tunnels.values()
        ]

    @property
    def count(self) -> int:
        return len(self._tunnels)