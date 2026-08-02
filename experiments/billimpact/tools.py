"""Tool-use layer: PolicyEngine as a callable tool inside the model loop.

Two things live here:
  1. A thread-safe pool of warm `pe_server.py` subprocesses (each holds a loaded
     PolicyEngine tax-benefit system, so a query costs ~0.1s instead of ~4s).
  2. An Anthropic tool-use conversation loop that lets a model call it.

The point of the experiment is that tool ACCESS is an ablation dimension: the
same question is asked with the authoritative calculator available and without
it, and we measure how far the answers move.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).parent
# Interpreter of a venv with policyengine-us installed. Set PE_PYTHON, e.g.:
#   python3 -m venv ~/.venvs/pe && ~/.venvs/pe/bin/pip install policyengine-us
#   export PE_PYTHON=~/.venvs/pe/bin/python3
PE_PYTHON = os.environ.get("PE_PYTHON", "python3")
PE_SERVER = HERE / "pe_server.py"

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


# ---------------------------------------------------------------------------
# PolicyEngine worker pool
# ---------------------------------------------------------------------------


class PolicyEngineWorker:
    """One warm pe_server subprocess. Not thread-safe on its own; the pool guards it."""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [PE_PYTHON, str(PE_SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        ready = self.proc.stdout.readline()
        if '"ready": true' not in ready and '"ready":true' not in ready:
            raise RuntimeError(f"pe_server failed to start: {ready!r}")
        # Pay the one-off reformed-system build cost now, not inside a run.
        self.query({"earnings": 8000, "children": 2, "threshold": 1})

    def query(self, req: dict) -> dict:
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("pe_server died")
        return json.loads(line)

    def close(self) -> None:
        try:
            self.proc.stdin.write('{"cmd":"quit"}\n')
            self.proc.stdin.flush()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            self.proc.kill()


class PolicyEnginePool:
    """Fixed pool of warm workers, checked out per tool call."""

    def __init__(self, size: int = 4) -> None:
        self.size = size
        self._q: queue.Queue = queue.Queue()
        self._built = 0
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        with self._lock:
            while self._built < self.size:
                self._q.put(PolicyEngineWorker())
                self._built += 1

    def query(self, req: dict, timeout: float = 120.0) -> dict:
        self._ensure()
        worker = self._q.get(timeout=timeout)
        try:
            return worker.query(req)
        finally:
            self._q.put(worker)

    def close(self) -> None:
        while not self._q.empty():
            self._q.get().close()


_POOL: Optional[PolicyEnginePool] = None
_POOL_LOCK = threading.Lock()


def pool(size: int = 4) -> PolicyEnginePool:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = PolicyEnginePool(size)
    return _POOL


# ---------------------------------------------------------------------------
# tool schema
# ---------------------------------------------------------------------------

POLICYENGINE_TOOL = {
    "name": "policyengine_ctc",
    "description": (
        "Compute a household's federal Child Tax Credit for tax year 2026 using "
        "PolicyEngine-US, the open-source microsimulation model of the US tax and "
        "benefit system. Returns the refundable CTC (the portion payable even with "
        "no income tax liability) and the total CTC, in dollars.\n\n"
        "Set `phase_in_threshold` to model a change to the refundable CTC earned-"
        "income phase-in threshold (IRC 24(d)(1)(B)(i), as overridden by 24(h)(6)). "
        "Omit it to use current law for 2026. Call this tool separately for each "
        "policy scenario you want to compare."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "earnings": {"type": "number", "description": "Annual employment income of the filer, in dollars."},
            "children": {"type": "integer", "description": "Number of CTC-qualifying children (ages 8+, under 17)."},
            "married": {"type": "boolean", "description": "True for a married-filing-jointly couple (spouse has no earnings). Default false."},
            "state": {"type": "string", "description": "Two-letter state code, e.g. 'TX'. Default 'TX'."},
            "phase_in_threshold": {
                "type": "number",
                "description": "Earned-income threshold above which the refundable CTC phases in. Current law for 2026 is 2500. Omit for current law.",
            },
        },
        "required": ["earnings", "children"],
    },
}

SERIES_TOOL = {
    "name": "series_history",
    "description": (
        "Look up the published history of the target indicator series as it stood "
        "at the forecast origin. Returns month/value pairs. Nothing after the "
        "origin is available; this tool cannot see the future."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "last_n_months": {"type": "integer", "description": "How many of the most recent months to return (max 120)."}
        },
        "required": [],
    },
}


def run_tool(name: str, args: dict, context: dict) -> dict:
    """Execute a tool call. `context` carries unit-specific data (e.g. history)."""
    if name == "policyengine_ctc":
        req = {
            "earnings": args.get("earnings", 0),
            "children": args.get("children", 0),
            "married": bool(args.get("married", False)),
            "state": args.get("state", "TX"),
            "threshold": args.get("phase_in_threshold"),
        }
        out = pool().query(req)
        if not out.get("ok"):
            return {"error": out.get("error", "unknown policyengine error")}
        return {
            "refundable_ctc": out["refundable_ctc"],
            "total_ctc": out["ctc"],
            "year": out["year"],
            "assumptions": out["inputs"],
        }
    if name == "series_history":
        n = min(int(args.get("last_n_months", 60) or 60), 120)
        hist = context.get("history", [])[-n:]
        return {"observations": [{"month": h["month"][:7], "value": h["value"]} for h in hist]}
    return {"error": f"unknown tool: {name}"}


# ---------------------------------------------------------------------------
# tool-use conversation loop
# ---------------------------------------------------------------------------


def call_with_tools(
    prompt: str,
    model: str,
    tools: list[dict],
    context: dict,
    temperature: float = 1.0,
    max_tokens: int = 2500,
    max_iterations: int = 8,
    timeout: float = 240.0,
    api_key: Optional[str] = None,
) -> dict:
    """Run an Anthropic tool-use loop. Returns transcript + final text + tool log."""
    from harness import _key  # reuse the same key loader

    key = api_key or _key()
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    tool_log: list[dict] = []
    start = time.time()
    final_text = ""
    stop_reason = None

    for _ in range(max_iterations):
        body = json.dumps(
            {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "tools": tools,
                "messages": messages,
            }
        ).encode()
        req = urllib.request.Request(
            ANTHROPIC_URL,
            data=body,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        last_err = None
        payload = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    payload = json.loads(r.read().decode())
                break
            except Exception as e:  # noqa: BLE001
                detail = ""
                if hasattr(e, "read"):
                    try:
                        detail = e.read().decode()[:200]
                    except Exception:  # noqa: BLE001
                        pass
                last_err = f"{type(e).__name__}: {e} {detail}"
                time.sleep(min(2.0 * (2**attempt), 15.0))
        if payload is None:
            return {"ok": False, "error": last_err, "tool_log": tool_log,
                    "duration_s": time.time() - start}

        blocks = payload.get("content") or []
        stop_reason = payload.get("stop_reason")
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if text:
            final_text = text

        tool_uses = [b for b in blocks if b.get("type") == "tool_use"]
        if not tool_uses:
            break

        messages.append({"role": "assistant", "content": blocks})
        results = []
        for tu in tool_uses:
            out = run_tool(tu["name"], tu.get("input") or {}, context)
            tool_log.append({"name": tu["name"], "input": tu.get("input"), "output": out})
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": json.dumps(out),
                }
            )
        messages.append({"role": "user", "content": results})

    return {
        "ok": True,
        "final_text": final_text,
        "tool_log": tool_log,
        "tool_calls": len(tool_log),
        "stop_reason": stop_reason,
        "duration_s": time.time() - start,
    }
