#!/usr/bin/env python3
"""
manage.py — xflow server manager

Commands:
  python manage.py start      start server in background, save PID
  python manage.py stop       stop the running server
  python manage.py restart    stop then start again
  python manage.py status     check server status and tunnel info
  python manage.py log        view access log (last 30 lines)
  python manage.py log -n 50  view last 50 lines
  python manage.py log -f     follow log in realtime (like tail -f)
  python manage.py help       show all commands
"""

import argparse
import os
import signal
import subprocess
import sys
import time

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
PID_FILE      = os.path.join(BASE_DIR, "xflow-server.pid")
LOG_FILE      = os.path.join(BASE_DIR, "access.log")
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
        print(f"  xflow-server is already running (PID {pid})")
        print(f"  Use: python manage.py restart")
        return

    print("  Starting xflow-server...")

    proc = subprocess.Popen(
        [sys.executable, SERVER_SCRIPT],
        stdout=open(LOG_FILE, "a"),
        stderr=subprocess.STDOUT,
        cwd=BASE_DIR,
        start_new_session=True,
    )

    time.sleep(1.5)
    if not is_running(proc.pid):
        print("  [ERROR] Server failed to start. Check the log:")
        print("  python manage.py log")
        return

    write_pid(proc.pid)
    print(f"  xflow-server running (PID {proc.pid})")
    print(f"  HTTP proxy : http://145.79.12.100:8080")
    print(f"  WebSocket  : ws://145.79.12.100:8081")
    print(f"  Log        : python manage.py log")


def cmd_stop():
    pid = read_pid()
    if not pid:
        print("  xflow-server is not running (no PID file)")
        return

    if not is_running(pid):
        print(f"  xflow-server is not running (PID {pid} is dead)")
        remove_pid()
        return

    print(f"  Stopping xflow-server (PID {pid})...")
    os.kill(pid, signal.SIGTERM)

    for _ in range(10):
        time.sleep(0.5)
        if not is_running(pid):
            break
    else:
        print("  Not responding to SIGTERM, forcing stop (SIGKILL)...")
        os.kill(pid, signal.SIGKILL)

    remove_pid()
    print("  xflow-server stopped.")


def cmd_restart():
    cmd_stop()
    time.sleep(1)
    cmd_start()


def cmd_status():
    pid = read_pid()

    print("\n  xflow-server status")
    print("  " + "─" * 36)

    if not pid:
        print("  Status  : not running")
        print("  Run     : python manage.py start\n")
        return

    if is_running(pid):
        print(f"  Status  : running")
        print(f"  PID     : {pid}")
        print(f"  HTTP    : http://145.79.12.100:8080")
        print(f"  WS      : ws://145.79.12.100:8081")
        print(f"  API     : http://145.79.12.100:8080/status")

        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE) as f:
                    lines = f.readlines()
                access_lines = [l for l in lines if "ACCESS" in l]
                print(f"  Requests: {len(access_lines)} total")
            except Exception:
                pass
    else:
        print(f"  Status  : dead (PID {pid} is not active)")
        remove_pid()
        print("  Run     : python manage.py start")

    print()


def cmd_help():
    B = "\033[1m"
    G = "\033[32m"
    Y = "\033[33m"
    C = "\033[36m"
    D = "\033[2m"
    R = "\033[0m"

    print(f"""
{B}  xflow — server manager{R}
  {"─" * 44}

{B}  Commands{R}

  {G}python manage.py start{R}
  {D}  Start server in background, save PID{R}

  {G}python manage.py stop{R}
  {D}  Stop the running server{R}

  {G}python manage.py restart{R}
  {D}  Stop then start the server again{R}

  {G}python manage.py status{R}
  {D}  Check if server is active, show tunnel info{R}

{B}  Access log{R}

  {G}python manage.py log{R}
  {D}  Show last 30 lines of access log{R}

  {G}python manage.py log -n 100{R}
  {D}  Show last 100 lines{R}

  {G}python manage.py log -f{R}
  {D}  Follow log in realtime (like tail -f){R}
  {D}  Press Ctrl+C to stop{R}

{B}  Server info{R}

  {C}  HTTP proxy  :{R} http://145.79.12.100:8080
  {C}  WebSocket   :{R} ws://145.79.12.100:8081
  {C}  Status API  :{R} http://145.79.12.100:8080/status
  {C}  Log file    :{R} {LOG_FILE}
  {C}  PID file    :{R} {PID_FILE}

{B}  Log format{R}

  {Y}timestamp  STATUS  METHOD  IP               PATH  SIZE{R}
  {D}  Green  = 2xx (success){R}
  {D}  Yellow = 4xx (client error){R}
  {D}  Red    = 5xx (server error){R}
""")


def cmd_log(n: int = 30, follow: bool = False):
    if not os.path.exists(LOG_FILE):
        print("  No log file yet. Start the server first.")
        return

    if follow:
        print(f"  Following log in realtime (Ctrl+C to stop)...\n")
        try:
            subprocess.run(["tail", "-f", "-n", str(n), LOG_FILE])
        except KeyboardInterrupt:
            print("\n  Done.")
        return

    with open(LOG_FILE) as f:
        lines = f.readlines()

    last_lines = lines[-n:] if len(lines) > n else lines

    print(f"\n  Last {min(n, len(lines))} lines — {LOG_FILE}")
    print("  " + "─" * 60)

    for line in last_lines:
        line = line.rstrip()
        if "ACCESS" in line:
            parts = line.split("ACCESS ", 1)
            if len(parts) == 2:
                ts_part     = parts[0].strip()
                access_part = parts[1]
                tokens      = access_part.split()
                if len(tokens) >= 4:
                    ip     = tokens[0]
                    method = tokens[1]
                    path   = tokens[2]
                    status = tokens[3]
                    size   = tokens[4] if len(tokens) > 4 else ""

                    if status.startswith("2"):
                        color = "\033[32m"
                    elif status.startswith("4"):
                        color = "\033[33m"
                    elif status.startswith("5"):
                        color = "\033[31m"
                    else:
                        color = "\033[0m"

                    reset    = "\033[0m"
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

    subparsers.add_parser("start",   help="Start server in background")
    subparsers.add_parser("stop",    help="Stop the server")
    subparsers.add_parser("restart", help="Restart the server")
    subparsers.add_parser("status",  help="Check server status")
    subparsers.add_parser("help",    help="Show all commands and server info")

    log_parser = subparsers.add_parser("log", help="View access log")
    log_parser.add_argument("-n", type=int, default=30, help="Number of lines to show (default: 30)")
    log_parser.add_argument("-f", "--follow", action="store_true", help="Follow log in realtime")

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