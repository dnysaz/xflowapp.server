#!/usr/bin/env python3
"""
manage.py — xflow server manager

Perintah:
  python manage.py start    ← jalankan server di background, simpan PID
  python manage.py stop     ← matikan server
  python manage.py restart  ← stop lalu start ulang
  python manage.py status   ← cek apakah server aktif + info tunnel
  python manage.py log      ← lihat log akses (IP, method, path, status)
  python manage.py log -n 50 ← lihat 50 baris terakhir
  python manage.py log -f   ← follow log secara realtime (seperti tail -f)
"""

import argparse
import os
import signal
import subprocess
import sys
import time
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(BASE_DIR, "xflow-server.pid")
LOG_FILE = os.path.join(BASE_DIR, "access.log")
SERVER_SCRIPT = os.path.join(BASE_DIR, "server.py")


# ──────────────────────────────────────────────
# PID helpers
# ──────────────────────────────────────────────

def read_pid() -> int | None:
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def write_pid(pid: int):
    with open(PID_FILE, "w") as f:
        f.write(str(pid))


def remove_pid():
    try:
        os.remove(PID_FILE)
    except FileNotFoundError:
        pass


def is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ──────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────

def cmd_start():
    pid = read_pid()
    if pid and is_running(pid):
        print(f"  xflow-server sudah berjalan (PID {pid})")
        print(f"  Gunakan: python manage.py restart")
        return

    print("  Menjalankan xflow-server...")

    proc = subprocess.Popen(
        [sys.executable, SERVER_SCRIPT],
        stdout=open(LOG_FILE, "a"),
        stderr=subprocess.STDOUT,
        cwd=BASE_DIR,
        start_new_session=True,  # detach dari terminal
    )

    # Tunggu sebentar pastikan tidak langsung crash
    time.sleep(1.5)
    if not is_running(proc.pid):
        print("  [ERROR] Server gagal start. Cek log:")
        print(f"  python manage.py log")
        return

    write_pid(proc.pid)
    print(f"  xflow-server berjalan (PID {proc.pid})")
    print(f"  HTTP proxy : http://145.79.12.100:8080")
    print(f"  WebSocket  : ws://145.79.12.100:8081")
    print(f"  Log        : python manage.py log")


def cmd_stop():
    pid = read_pid()
    if not pid:
        print("  xflow-server tidak berjalan (PID file tidak ada)")
        return

    if not is_running(pid):
        print(f"  xflow-server tidak berjalan (PID {pid} sudah mati)")
        remove_pid()
        return

    print(f"  Menghentikan xflow-server (PID {pid})...")
    os.kill(pid, signal.SIGTERM)

    # Tunggu hingga benar-benar berhenti
    for _ in range(10):
        time.sleep(0.5)
        if not is_running(pid):
            break
    else:
        print(f"  Tidak merespons SIGTERM, paksa berhenti (SIGKILL)...")
        os.kill(pid, signal.SIGKILL)

    remove_pid()
    print("  xflow-server dihentikan.")


def cmd_restart():
    cmd_stop()
    time.sleep(1)
    cmd_start()


def cmd_status():
    pid = read_pid()

    print("\n  xflow-server status")
    print("  " + "─" * 36)

    if not pid:
        print("  Status  : tidak berjalan")
        print("  Jalankan: python manage.py start\n")
        return

    if is_running(pid):
        print(f"  Status  : aktif")
        print(f"  PID     : {pid}")
        print(f"  HTTP    : http://145.79.12.100:8080")
        print(f"  WS      : ws://145.79.12.100:8081")
        print(f"  Status  : http://145.79.12.100:8080/status")

        # Hitung jumlah akses dari log
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE) as f:
                    lines = f.readlines()
                access_lines = [l for l in lines if "ACCESS" in l]
                print(f"  Total request : {len(access_lines)}")
            except Exception:
                pass
    else:
        print(f"  Status  : mati (PID {pid} tidak aktif)")
        remove_pid()
        print("  Jalankan: python manage.py start")

    print()


def cmd_help():
    B = "\033[1m"       # bold
    G = "\033[32m"      # hijau
    Y = "\033[33m"      # kuning
    C = "\033[36m"      # cyan
    D = "\033[2m"       # dim
    R = "\033[0m"       # reset

    print(f"""
{B}  xflow — server manager{R}
  {"─" * 44}

{B}  Perintah utama{R}

  {G}python manage.py start{R}
  {D}  Jalankan server di background, simpan PID{R}

  {G}python manage.py stop{R}
  {D}  Hentikan server yang sedang berjalan{R}

  {G}python manage.py restart{R}
  {D}  Stop lalu start ulang server{R}

  {G}python manage.py status{R}
  {D}  Cek apakah server aktif, tampilkan info tunnel{R}

{B}  Log akses{R}

  {G}python manage.py log{R}
  {D}  Tampilkan 30 baris log terakhir{R}

  {G}python manage.py log -n 100{R}
  {D}  Tampilkan 100 baris log terakhir{R}

  {G}python manage.py log -f{R}
  {D}  Follow log secara realtime (seperti tail -f){R}
  {D}  Tekan Ctrl+C untuk berhenti{R}

{B}  Info server{R}

  {C}  HTTP proxy  :{R} http://145.79.12.100:8080
  {C}  WebSocket   :{R} ws://145.79.12.100:8081
  {C}  Status API  :{R} http://145.79.12.100:8080/status
  {C}  Log file    :{R} {LOG_FILE}
  {C}  PID file    :{R} {PID_FILE}

{B}  Format log{R}

  {Y}timestamp  STATUS  METHOD  IP               PATH  SIZE{R}
  {D}  Hijau = 2xx (sukses){R}
  {D}  Kuning = 4xx (client error){R}
  {D}  Merah  = 5xx (server error){R}
""")


def cmd_log(n: int = 30, follow: bool = False):
    if not os.path.exists(LOG_FILE):
        print("  Log belum ada. Jalankan server dulu.")
        return

    if follow:
        # Realtime follow seperti tail -f
        print(f"  Mengikuti log secara realtime (Ctrl+C untuk berhenti)...\n")
        try:
            proc = subprocess.run(["tail", "-f", "-n", str(n), LOG_FILE])
        except KeyboardInterrupt:
            print("\n  Selesai.")
        return

    # Tampilkan N baris terakhir, filter hanya akses yang relevan
    with open(LOG_FILE) as f:
        lines = f.readlines()

    # Ambil semua baris (server log + access log)
    last_lines = lines[-n:] if len(lines) > n else lines

    print(f"\n  Log terakhir ({min(n, len(lines))} baris) — {LOG_FILE}")
    print("  " + "─" * 60)

    for line in last_lines:
        line = line.rstrip()
        if "ACCESS" in line:
            # Highlight baris akses
            # Format: timestamp [INFO] ACCESS ip method path status size
            parts = line.split("ACCESS ", 1)
            if len(parts) == 2:
                ts_part = parts[0].strip()
                access_part = parts[1]
                tokens = access_part.split()
                if len(tokens) >= 4:
                    ip     = tokens[0]
                    method = tokens[1]
                    path   = tokens[2]
                    status = tokens[3]
                    size   = tokens[4] if len(tokens) > 4 else ""

                    # Warna berdasarkan status code
                    if status.startswith("2"):
                        color = "\033[32m"  # hijau
                    elif status.startswith("4"):
                        color = "\033[33m"  # kuning
                    elif status.startswith("5"):
                        color = "\033[31m"  # merah
                    else:
                        color = "\033[0m"

                    reset = "\033[0m"
                    ts_clean = ts_part.replace("[INFO]", "").strip()
                    print(f"  {ts_clean}  {color}{status}{reset}  {method:<7} {ip:<20} {path} {size}")
                else:
                    print(f"  {line}")
        elif "[ERROR]" in line or "[WARNING]" in line:
            print(f"  \033[31m{line}\033[0m")
        else:
            print(f"  {line}")

    print()


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="manage.py",
        description="xflow server manager",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("start",   help="Jalankan server di background")
    subparsers.add_parser("stop",    help="Hentikan server")
    subparsers.add_parser("restart", help="Restart server")
    subparsers.add_parser("status",  help="Cek status server")
    subparsers.add_parser("help",    help="Tampilkan semua perintah dan info server")

    log_parser = subparsers.add_parser("log", help="Lihat log akses")
    log_parser.add_argument("-n", type=int, default=30, help="Jumlah baris terakhir (default: 30)")
    log_parser.add_argument("-f", "--follow", action="store_true", help="Follow log secara realtime")

    args = parser.parse_args()

    if args.command == "start":
        cmd_start()
    elif args.command == "stop":
        cmd_stop()
    elif args.command == "restart":
        cmd_restart()
    elif args.command == "status":
        cmd_status()
    elif args.command == "log":
        cmd_log(n=args.n, follow=args.follow)
    elif args.command == "help":
        cmd_help()


if __name__ == "__main__":
    main()