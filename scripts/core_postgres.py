#!/usr/bin/env python3
"""Run a command against a temporary private-socket PostgreSQL cluster.

Example:
    python scripts/core_postgres.py -- uv run --extra core --extra dev pytest

Uses installed PostgreSQL binaries, never Docker or a substitute database.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote


def postgres_binary(name: str, directory: str | None) -> str:
    if directory:
        candidate = Path(directory) / name
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    config = shutil.which("pg_config")
    if config:
        bindir = subprocess.check_output([config, "--bindir"], text=True).strip()
        candidate = Path(bindir) / name
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError(
        f"Missing PostgreSQL binary {name}; install PostgreSQL 14+ or supply --pg-bin"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-bin", help="Directory containing PostgreSQL executables")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("Supply a command after --")
    binaries = {
        name: postgres_binary(name, args.pg_bin)
        for name in ("initdb", "pg_ctl", "createdb")
    }
    with tempfile.TemporaryDirectory(prefix="thesis-pg-", dir="/tmp") as directory:
        root = Path(directory)
        data = root / "data"
        socket = root / "socket"
        socket.mkdir(mode=0o700)
        log = root / "postgres.log"
        started = False
        try:
            subprocess.run(
                [
                    binaries["initdb"],
                    "-D",
                    str(data),
                    "-U",
                    "thesis_core",
                    "--auth=trust",
                    "--no-locale",
                    "-E",
                    "UTF8",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            subprocess.run(
                [
                    binaries["pg_ctl"],
                    "-D",
                    str(data),
                    "-l",
                    str(log),
                    "-w",
                    "-t",
                    "30",
                    "-o",
                    f"-F -k {socket} -h '' -p 55432",
                    "start",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            started = True
            subprocess.run(
                [
                    binaries["createdb"],
                    "-h",
                    str(socket),
                    "-p",
                    "55432",
                    "-U",
                    "thesis_core",
                    "thesis_core",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            dsn = (
                "postgresql://thesis_core@/thesis_core?host="
                f"{quote(str(socket), safe='/')}&port=55432"
            )
            print(
                json.dumps({"postgres": "isolated private socket", "dsn": dsn}),
                flush=True,
            )
            environment = dict(os.environ)
            environment.update(
                THESIS_CORE_TEST_DSN=dsn,
                THESIS_CORE_DSN=dsn,
                THESIS_CORE_REQUIRE_POSTGRES="1",
            )
            return subprocess.run(command, env=environment).returncode
        except subprocess.CalledProcessError as exc:
            print(exc.stdout or str(exc), file=sys.stderr)
            if log.exists():
                print(log.read_text()[-4000:], file=sys.stderr)
            return 1
        finally:
            if started:
                subprocess.run(
                    [
                        binaries["pg_ctl"],
                        "-D",
                        str(data),
                        "-w",
                        "-t",
                        "30",
                        "-m",
                        "immediate",
                        "stop",
                    ],
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )


if __name__ == "__main__":
    raise SystemExit(main())
