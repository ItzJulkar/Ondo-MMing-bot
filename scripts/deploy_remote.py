"""One-time remote deploy to VPS via SSH."""
import os
import sys
from pathlib import Path

try:
    import paramiko
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko", "-q"])
    import paramiko

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"__pycache__", "venv", "logs", ".git"}
SKIP_FILES = {"bot.pid", "bot.stop", "deploy_remote.py"}


def upload_dir(sftp, local: Path, remote: str) -> None:
    try:
        sftp.mkdir(remote)
    except OSError:
        pass
    for item in local.iterdir():
        if item.name in SKIP_FILES or item.name.startswith("."):
            if item.name not in (".env.example",):
                if item.name == ".env":
                    continue  # written separately
                if item.name.startswith("."):
                    continue
        if item.is_dir():
            if item.name in SKIP_DIRS:
                continue
            upload_dir(sftp, item, f"{remote}/{item.name}")
        else:
            if item.suffix == ".pyc":
                continue
            sftp.put(str(item), f"{remote}/{item.name}")


def run(ssh, cmd: str) -> str:
    print(f">>> {cmd}")
    _, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    combined = (out + err).strip()
    if combined:
        print(combined[-2000:])
    return combined


def main() -> None:
    host = os.environ["DEPLOY_HOST"]
    user = os.environ.get("DEPLOY_USER", "root")
    password = os.environ["DEPLOY_PASS"]

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {host}...")
    ssh.connect(host, username=user, password=password, timeout=30)

    run(ssh, "mkdir -p /root/ondo-grid-bot")
    sftp = ssh.open_sftp()
    upload_dir(sftp, ROOT, "/root/ondo-grid-bot")

    env_content = (ROOT / ".env").read_text(encoding="utf-8")
    with sftp.open("/root/ondo-grid-bot/.env", "w") as f:
        f.write(env_content)

    config = (ROOT / "config.yaml").read_text(encoding="utf-8")
    config = config.replace("dry_run: true", "dry_run: false")
    with sftp.open("/root/ondo-grid-bot/config.yaml", "w") as f:
        f.write(config)

    sftp.close()

    run(ssh, "apt-get update -qq && apt-get install -y -qq python3 python3-pip python3-venv")
    run(ssh, "cd /root/ondo-grid-bot && python3 -m venv venv")
    run(ssh, "cd /root/ondo-grid-bot && ./venv/bin/pip install -r requirements.txt -q")
    run(ssh, "cd /root/ondo-grid-bot && ./venv/bin/python3 -m src.main stop 2>/dev/null || true")
    out = run(ssh, "cd /root/ondo-grid-bot && ./venv/bin/python3 -m src.main start")
    out2 = run(ssh, "cd /root/ondo-grid-bot && ./venv/bin/python3 -m src.main status")
    run(ssh, "cd /root/ondo-grid-bot && tail -5 logs/bot.log 2>/dev/null || true")

    ssh.close()
    print("\n=== DEPLOY DONE ===")


if __name__ == "__main__":
    main()