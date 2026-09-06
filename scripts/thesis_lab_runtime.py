#!/usr/bin/env python3
"""Install a private, durable macOS lab preview; never changes production.

Explicit install starts four per-user launchd jobs. Scientific data survives
service restarts and stop. This is a local pilot, dependent on login and wake.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, text=True, capture_output=True, **kwargs)


def loaded(domain, label):
    return (
        subprocess.run(
            ["launchctl", "print", f"{domain}/{label}"], capture_output=True
        ).returncode
        == 0
    )


def unload(domain, label):
    subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
    # launchd can return while process termination is still in progress.
    for _ in range(50):
        if not loaded(domain, label):
            return
        time.sleep(0.1)
    raise RuntimeError(f"Service did not stop: {label}")


def start_runtime(config, domain, plists):
    """Resume a staged install or start stopped jobs without replacing data."""
    root = Path(config["root"])
    labels = config["labels"]
    pg_bin = Path(config["pg_bin"])
    port = str(config["pg_port"])
    socket = str(root / "socket")
    for identity in labels.values():
        run(["launchctl", "enable", f"{domain}/{identity}"])
    if not loaded(domain, labels["postgres"]):
        run(
            [
                "launchctl",
                "bootstrap",
                domain,
                str(plists / f"{labels['postgres']}.plist"),
            ]
        )
    for _ in range(100):
        check = subprocess.run(
            [str(pg_bin / "pg_isready"), "-h", socket, "-p", port],
            capture_output=True,
        )
        if check.returncode == 0:
            break
        time.sleep(0.2)
    else:
        raise RuntimeError(f"Database did not start; inspect {root / 'logs'}")
    exists = run(
        [
            str(pg_bin / "psql"),
            "-h",
            socket,
            "-p",
            port,
            "-d",
            "postgres",
            "-Atc",
            "SELECT 1 FROM pg_database WHERE datname='thesis_lab'",
        ]
    ).stdout.strip()
    if not exists:
        run([str(pg_bin / "createdb"), "-h", socket, "-p", port, "thesis_lab"])
    run([config["python"], "-m", "thesis_core", "init"], env=config["environment"])
    for role in ("api", "site", "poll"):
        if not loaded(domain, labels[role]):
            run(
                [
                    "launchctl",
                    "bootstrap",
                    domain,
                    str(plists / f"{labels[role]}.plist"),
                ]
            )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "status", "stop", "restart"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--api-port", type=int, default=8111)
    parser.add_argument("--site-port", type=int, default=3211)
    parser.add_argument("--pg-port", type=int, default=55491)
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        parser.error("This installer requires macOS; use deploy/thesis-lab on Linux")
    root, repo = args.root.expanduser().resolve(), args.repo.resolve()
    if not re.fullmatch(r"[a-z0-9-]+", root.name):
        parser.error(
            "Runtime directory name must contain lowercase letters/digits/hyphens"
        )
    for port in (args.api_port, args.site_port, args.pg_port):
        if not 1024 <= port <= 65535:
            parser.error("Ports must be in 1024..65535")
    socket = root / "socket"
    if args.command in {"install", "restart"} and len(str(socket).encode()) > 85:
        parser.error("Runtime path is too long for a PostgreSQL Unix socket")
    label = f"org.thesis.{root.name}"
    domain = f"gui/{os.getuid()}"
    roles = ("postgres", "api", "site", "poll")
    labels = {role: f"{label}.{role}" for role in roles}
    plists = Path.home() / "Library/LaunchAgents"
    saved = None
    if args.command in {"stop", "restart"}:
        if not (root / "runtime.json").is_file():
            parser.error("No installed runtime configuration; no services were changed")
        saved = json.loads((root / "runtime.json").read_text())
        if saved["root"] != str(root) or saved["labels"] != labels:
            parser.error("Runtime identity mismatch; no services were changed")
    if args.command == "status":
        result = {}
        for role, identity in labels.items():
            process = subprocess.run(
                ["launchctl", "print", f"{domain}/{identity}"],
                capture_output=True,
                text=True,
            )
            result[role] = {"loaded": process.returncode == 0}
            for field in ("state", "pid", "last exit code"):
                match = re.search(rf"^\s*{field} = (.+)$", process.stdout, re.M)
                if match:
                    result[role][field] = match[1]
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "stop":
        for role in reversed(roles):
            run(["launchctl", "disable", f"{domain}/{labels[role]}"])
            unload(domain, labels[role])
        print(
            json.dumps({"stopped": list(labels.values()), "data_preserved": str(root)})
        )
        return 0
    if args.command == "restart":
        for role in reversed(roles):
            unload(domain, labels[role])
        start_runtime(saved, domain, plists)
        print(json.dumps({"restarted": list(labels.values())}))
        return 0
    os.umask(0o077)
    if (root / "runtime.json").exists():
        parser.error(
            "Runtime already installed; use status/restart (existing data preserved)"
        )
    # Check every service collision before initdb or any other persistent mutation.
    for identity in labels.values():
        path = plists / f"{identity}.plist"
        if path.exists() or loaded(domain, identity):
            parser.error(f"Existing launch agent preserved: {identity}")
    if (root / "postgres").exists():
        parser.error(
            "Existing database directory found; refusing to initialize over it"
        )
    python = repo / ".venv/bin/python"
    bun = shutil.which("bun")
    codex = shutil.which("codex")
    config = shutil.which("pg_config")
    if not python.is_file() or not bun or not config or not codex:
        parser.error(
            "Install the repo core environment, Codex, Bun and PostgreSQL first"
        )
    if not (repo / "site/.next/BUILD_ID").is_file():
        parser.error("Build the site before installing its persistent preview")
    pg_bin = Path(run([config, "--bindir"]).stdout.strip())
    for directory in (root, socket, root / "artifacts", root / "logs", root / "bin"):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    run(
        [
            str(pg_bin / "initdb"),
            "-D",
            str(root / "postgres"),
            "--auth-local=peer",
            "--auth-host=reject",
            "--no-locale",
            "-E",
            "UTF8",
        ]
    )
    dsn = (
        f"postgresql://{quote(getpass.getuser())}@/thesis_lab?"
        f"host={quote(str(socket), safe='/')}&port={args.pg_port}"
    )
    environment = {
        "THESIS_CORE_DSN": dsn,
        "THESIS_CORE_SCHEMA": "thesis_lab",
        "THESIS_CORE_ARTIFACTS": str(root / "artifacts"),
        "THESIS_CORE_API_URL": f"http://127.0.0.1:{args.api_port}",
        "PATH": os.pathsep.join(
            [
                str(root / "bin"),
                str(repo / ".venv/bin"),
                str(Path(bun).parent),
                str(Path(codex).parent),
                "/opt/homebrew/bin",
                "/usr/bin",
                "/bin",
            ]
        ),
        "HOME": str(Path.home()),
        "LANG": "en_US.UTF-8",
    }
    if os.environ.get("CODEX_HOME"):
        environment["CODEX_HOME"] = os.environ["CODEX_HOME"]
    launcher = root / "bin/thesis-core-codex"
    launcher.write_text(
        "#!/usr/bin/env python3\nfrom thesis_core.codex_transport import main\n"
        "raise SystemExit(main())\n"
    )
    launcher.chmod(0o700)
    commands = {
        "postgres": [
            str(pg_bin / "postgres"),
            "-D",
            str(root / "postgres"),
            "-k",
            str(socket),
            "-h",
            "",
            "-p",
            str(args.pg_port),
        ],
        "api": [
            str(python),
            "-m",
            "thesis_core",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.api_port),
        ],
        "site": [
            bun,
            "node_modules/next/dist/bin/next",
            "start",
            "--hostname",
            "127.0.0.1",
            "--port",
            str(args.site_port),
        ],
        "poll": [str(python), "-m", "thesis_core", "poll", "--max-jobs", "20"],
    }
    plists.mkdir(parents=True, exist_ok=True)
    for role in roles:
        path = plists / f"{labels[role]}.plist"
        if path.exists():
            parser.error(f"Existing launch agent preserved: {path}")
        contents = {
            "Label": labels[role],
            "ProgramArguments": commands[role],
            "WorkingDirectory": str(repo / "site" if role == "site" else repo),
            "EnvironmentVariables": environment,
            "RunAtLoad": True,
            "StandardOutPath": str(root / "logs" / f"{role}.stdout.log"),
            "StandardErrorPath": str(root / "logs" / f"{role}.stderr.log"),
            "Umask": 0o077,
        }
        if role == "poll":
            contents["StartInterval"] = 60
        else:
            contents.update(KeepAlive=True, ThrottleInterval=10)
        path.write_bytes(plistlib.dumps(contents))
        path.chmod(0o600)
    # Save restart information before starting services: partial bootstrap can
    # resume using restart, including idempotent database creation/migration.
    config_path = root / "runtime.json"
    runtime = {
        "repo": str(repo),
        "root": str(root),
        "labels": labels,
        "environment": environment,
        "pg_bin": str(pg_bin),
        "pg_port": args.pg_port,
        "python": str(python),
    }
    config_path.write_text(json.dumps(runtime, indent=2) + "\n")
    start_runtime(runtime, domain, plists)
    print(
        json.dumps(
            {
                "runtime": str(config_path),
                "site": f"http://127.0.0.1:{args.site_port}/lab",
                "api": environment["THESIS_CORE_API_URL"],
                "poll_interval_seconds": 60,
                "limitation": "Local Mac must be logged in and awake",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
