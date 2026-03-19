# xflow

Expose localhost ke internet dengan cepat. Versi sederhana dari ngrok, open source.

## Cara Kerja

```
localhost:3000 ←→ xflow-client ←→[WebSocket]←→ xflow-server (VPS) ←→ Internet
```

---

## Instalasi

### xflow-server (di VPS)

```bash
cd xflow-server
pip install -r requirements.txt
python server.py --host 0.0.0.0 --http-port 8080 --ws-port 8081
```

Dengan token auth:
```bash
python server.py --token rahasia123
```

### xflow-client (di laptop user)

```bash
cd xflow-client
pip install -r requirements.txt
```

---

## Penggunaan

### 1. Jalankan server di VPS

```bash
python server.py
# HTTP proxy : http://0.0.0.0:8080
# WebSocket  : ws://0.0.0.0:8081
```

### 2. Di laptop, expose port lokal

```bash
python cli.py http 3000 --server ws://IP_VPS:8081
```

Output:
```
──────────────────────────────────────────────────
  xflow tunnel aktif!
  Tunnel ID : abc123
  URL publik : http://IP_VPS:8080/proxy/abc123/
  → localhost:3000
──────────────────────────────────────────────────
```

### 3. Bagikan URL ke siapapun

```
http://IP_VPS:8080/proxy/abc123/
```

URL ini bisa diakses dari mana saja selama tunnel aktif.

---

## Environment Variables

| Variable | Keterangan | Default |
|---|---|---|
| `XFLOW_SERVER` | Alamat server (client) | `ws://localhost:8081` |
| `XFLOW_TOKEN` | Auth token | kosong |
| `XFLOW_HOST` | Host untuk URL publik (server) | `localhost` |
| `XFLOW_PORT` | Port HTTP proxy (server) | `8080` |

---

## Roadmap

### Phase 1 (sekarang) — HTTP via IP:PORT ✓
- [x] WebSocket tunnel
- [x] HTTP proxy via `/proxy/<tunnel_id>/`
- [x] Auth token
- [x] Auto-reconnect
- [x] Multiple tunnel support

### Phase 2 — HTTPS + Subdomain
- [ ] Wildcard SSL cert (Let's Encrypt)
- [ ] Subdomain routing: `abc123.xflow.dev`
- [ ] Nginx/Caddy config generator
- [ ] Dashboard web

---

## Struktur Project

```
xflow/
├── xflow-server/
│   ├── server.py      ← HTTP proxy + WebSocket server
│   ├── tunnel.py      ← Tunnel manager
│   └── requirements.txt
└── xflow-client/
    ├── client.py      ← Core tunnel client
    ├── cli.py         ← CLI entry point
    └── requirements.txt
```