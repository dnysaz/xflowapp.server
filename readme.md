# xflow

Expose your localhost to the internet — fast, simple, and open source.

```
xflow serve
```

```
  xflow  tunnel is active

  Project    HTML Static
  Local      http://127.0.0.1:8400
  Public     http://145.79.12.100:8080/proxy/myapp/
  Tunnel ID  myapp  (persistent) ✓
  Dashboard  http://127.0.0.1:7070
```

---

## Features

- **Auto-detect** — detects Next.js, Laravel, Vite, Vue, SvelteKit, Django, Flask, and plain HTML projects automatically
- **Built-in file server** — for HTML projects, no need to run a separate server
- **Persistent tunnel ID** — your URL stays the same across restarts, stored in `.xflow` per project
- **Custom tunnel name** — `xflow serve --name myapp` → `/proxy/myapp/`
- **Dashboard** — realtime request log, IP lookup with location, QR code, multi-tunnel support
- **Welcome page** — branded splash screen before redirecting to your project (togglable per tunnel)
- **Multi-tunnel** — run multiple tunnels at once, all visible in one dashboard

---

## Install

**Requirements:** Python 3.10+

```bash
git clone https://github.com/yourname/xflow
cd xflow/xflow-client
chmod +x install.sh
./install.sh
```

Then add `~/.local/bin` to your PATH if not already:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

---

## Usage

### Auto-detect project (recommended)

```bash
cd /your/project
xflow serve
```

xflow will detect your framework and start tunneling automatically.

### Force a specific port

```bash
xflow serve --port 3000
```

### Custom tunnel name

```bash
xflow serve --name myapp
# → http://your-server/proxy/myapp/
```

### Tunnel directly to a port

```bash
xflow http 3000
```

### Check status

```bash
xflow status
```

### Without dashboard

```bash
xflow serve --no-dashboard
```

---

## Supported frameworks

| Framework | Detection | Default port |
|---|---|---|
| Next.js | `next.config.js` | 3000 |
| Nuxt.js | `nuxt.config.js` | 3000 |
| Vite / Vue / React | `vite.config.js` | 5173 |
| SvelteKit | `svelte.config.js` | 5173 |
| Laravel | `artisan` | 8000 |
| Django | `manage.py` + django import | 8000 |
| Flask | `app.py` + flask import | 5000 |
| HTML Static | `index.html` | auto |

---

## Dashboard

A local dashboard opens automatically at `http://127.0.0.1:7070` when you run `xflow serve`.

- **Left panel** — all active tunnels from all running `xflow` processes on this machine
- **Right panel** — request log for the selected tunnel with IP location lookup
- **Welcome page toggle** — enable/disable the splash screen per tunnel
- **QR code** — scan to open on mobile

---

## Installer commands

```bash
./install.sh            # install (default)
./install.sh update     # update to latest version
./install.sh uninstall  # remove from system
./install.sh check      # verify installation
./install.sh help       # show help
```

---

## Server setup (VPS)

```bash
cd xflow-server
pip install -r requirements.txt
python manage.py start     # start in background
python manage.py status    # check status
python manage.py log       # view access log
python manage.py log -f    # follow log realtime
python manage.py stop      # stop server
python manage.py help      # all commands
```

---

## Project structure

```
xflow/
├── xflow-client/
│   ├── cli.py           entry point — xflow command
│   ├── client.py        WebSocket tunnel client
│   ├── detector.py      framework auto-detection
│   ├── fileserver.py    built-in HTTP file server
│   ├── dashboard.py     local dashboard server
│   ├── tunnel_store.py  persistent tunnel ID storage
│   ├── html/
│   │   └── dashboard.html
│   └── install.sh
└── xflow-server/
    ├── server.py        HTTP proxy + WebSocket server
    ├── tunnel.py        tunnel manager
    ├── tunnel_store.py  SQLite tunnel registry
    ├── manage.py        server process manager
    └── html/
        ├── welcome.html splash screen
        ├── 404.html     tunnel not found page
        └── home.html    server landing page
```

---

## How it works

```
Your app (localhost:3000)
    ↕ HTTP
xflow-client
    ↕ WebSocket (persistent tunnel)
xflow-server (VPS)
    ↕ HTTP
Anyone on the internet
```

1. `xflow-client` connects to `xflow-server` via WebSocket
2. Server assigns a tunnel ID and returns a public URL
3. Incoming HTTP requests are serialized and sent through the WebSocket to your client
4. Client forwards them to your local app and sends the response back

---

## License

MIT