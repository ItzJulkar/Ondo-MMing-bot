import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PID_FILE = ROOT / "bot.pid"
STOP_FILE = ROOT / "bot.stop"
SAFE_EXIT_FILE = ROOT / "bot.safe_exit"
LOG_FILE = ROOT / "logs" / "bot.log"


def is_running() -> bool:
    pid = read_pid()
    if pid is None:
        return False
    return _process_alive(pid)


def read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _process_alive(pid: int) -> bool:
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def write_pid(pid: int) -> None:
    PID_FILE.write_text(str(pid), encoding="utf-8")


def clear_pid() -> None:
    PID_FILE.unlink(missing_ok=True)


def request_stop() -> None:
    STOP_FILE.touch()


def clear_stop() -> None:
    STOP_FILE.unlink(missing_ok=True)


def stop_requested() -> bool:
    return STOP_FILE.exists()


def request_safe_exit() -> None:
    SAFE_EXIT_FILE.touch()


def clear_safe_exit() -> None:
    SAFE_EXIT_FILE.unlink(missing_ok=True)


def safe_exit_requested() -> bool:
    return SAFE_EXIT_FILE.exists()


def start_background(config_path: str = "config.yaml") -> None:
    if is_running():
        pid = read_pid()
        raise SystemExit(f"Bot is already running (PID {pid}). Use: python -m src.main stop")

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    clear_stop()
    clear_safe_exit()
    clear_pid()

    cmd = [sys.executable, "-m", "src.main", "run", "-c", config_path]
    log_handle = open(LOG_FILE, "a", encoding="utf-8")

    if sys.platform == "win32":
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
    else:
        proc = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )

    write_pid(proc.pid)
    print(f"Bot started (PID {proc.pid}) — trading 24/7")
    print(f"  Logs: {LOG_FILE}")
    print(f"  Safe exit: python -m src.main safe-exit")
    print(f"  Stop now: python -m src.main stop")


def safe_exit_background() -> None:
    pid = read_pid()
    if pid is None or not _process_alive(pid):
        clear_pid()
        clear_safe_exit()
        print("Bot is not running.")
        return

    request_safe_exit()
    print(f"Safe exit requested for bot (PID {pid}).")
    print("  New entry orders will stop now.")
    print("  Existing positions will keep maker close orders until flat.")
    print(f"  Watch: python -m src.main status")


def stop_background() -> None:
    pid = read_pid()
    if pid is None or not _process_alive(pid):
        clear_pid()
        clear_stop()
        clear_safe_exit()
        print("Bot is not running.")
        return

    request_stop()
    print(f"Stopping bot (PID {pid})...")

    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True)
    else:
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass

    clear_pid()
    clear_stop()
    clear_safe_exit()
    print("Bot stopped.")


def show_status() -> None:
    pid = read_pid()
    if pid and _process_alive(pid):
        print(f"Bot is RUNNING (PID {pid})")
        if safe_exit_requested():
            print("  Mode: SAFE EXIT requested (no new entries; closing existing positions)")
        print(f"  Logs: {LOG_FILE}")
        if LOG_FILE.exists():
            lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[-5:]:
                print(f"  | {line}")
    else:
        clear_pid()
        clear_safe_exit()
        print("Bot is STOPPED")
        print("  Start: python -m src.main start")
