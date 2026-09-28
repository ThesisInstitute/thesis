"""Scan validated evidence representations without mistaking base64 for text.

This is a read-only scanning projection, never a rewrite of captured evidence.
Only complete, replay-valid controlled-tool envelopes receive it. Ordinary data
continues through the publisher's raw-byte scanner.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

INVALID_ENVELOPE = "invalid tool evidence secret-scan envelope"


def _is_envelope(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("schemaVersion") == "thesis_tool_evidence_v1"
    )


def _looks_like_invalid_envelope(data: bytes) -> bool:
    # Identification only: accepting a duplicate key, trailing document or
    # alternate encoding here grants no exemption. It forces a blocking result.
    text = data.decode("utf-8", errors="replace").lstrip()
    decoder = json.JSONDecoder()
    # Read only top-level metadata. A nested quoted envelope in a native JSONL
    # event is not this artifact. Canonical captures put captureMethod before
    # calls, so a truncated body still blocks rather than hiding encoded secrets.
    if text.startswith("{"):
        i = 1
        try:
            while True:
                while text[i] in " \t\r\n":
                    i += 1
                key, i = decoder.raw_decode(text, i)
                while text[i] in " \t\r\n":
                    i += 1
                if text[i] != ":":
                    break
                i += 1
                while text[i] in " \t\r\n":
                    i += 1
                value, i = decoder.raw_decode(text, i)
                if (key == "schemaVersion" and value == "thesis_tool_evidence_v1") or (
                    key == "captureMethod" and value == "thesis-controlled-tools-v1"
                ):
                    return True
                while text[i] in " \t\r\n":
                    i += 1
                if text[i] != ",":
                    break
                i += 1
        except (ValueError, IndexError, RecursionError):
            pass
    try:
        return _is_envelope(json.loads(data))
    except (ValueError, UnicodeError, RecursionError):
        return False


def _string_projection(
    text: str,
    approved: dict[tuple[Any, ...], str],
    patterns: dict[str, re.Pattern[bytes]],
) -> tuple[list[tuple[int, int]], set[str]]:
    """Locate exact string spans in already validated JSON, without recursion.

    Offsets refer to the strictly decoded UTF-8 text. Re-encoding its untouched
    slices preserves every original byte, including whitespace and escapes.
    Keys and unexcluded string values are also scanned after JSON unescaping.
    """
    spans: list[tuple[int, int]] = []
    found: set[tuple[Any, ...]] = set()
    hits: set[str] = set()
    stack: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    i = 0

    def path() -> tuple[Any, ...]:
        if not stack:
            return ()
        frame = stack[-1]
        return frame["path"] + (
            frame["key"] if frame["kind"] == "object" else frame["index"],
        )

    while i < len(text):
        char = text[i]
        if char in " \t\r\n":
            i += 1
        elif char in "{[":
            current = path()
            stack.append(
                {
                    "kind": "object" if char == "{" else "array",
                    "path": current,
                    "key": None,
                    "index": 0,
                    "expect_key": char == "{",
                }
            )
            i += 1
        elif char in "}]":
            stack.pop()
            i += 1
        elif char == ",":
            frame = stack[-1]
            if frame["kind"] == "object":
                frame["expect_key"] = True
            else:
                frame["index"] += 1
            i += 1
        elif char == ":":
            i += 1
        elif char == '"':
            value, end = decoder.raw_decode(text, i)
            frame = stack[-1] if stack else None
            if frame and frame["kind"] == "object" and frame["expect_key"]:
                frame["key"] = value
                frame["expect_key"] = False
                excluded = False
            else:
                current = path()
                excluded = current in approved
                if excluded:
                    if value != approved[current] or current in found:
                        raise ValueError(
                            "response string span differs from verified body"
                        )
                    spans.append((i, end))
                    found.add(current)
            if not excluded:
                raw = value.encode("utf-8")
                hits.update(
                    name for name, pattern in patterns.items() if pattern.search(raw)
                )
            i = end
        else:
            _, i = decoder.raw_decode(text, i)
    if found != set(approved):
        raise ValueError("missing verified response string span")
    return spans, hits


def scan_evidence_bytes(
    data: bytes, patterns: dict[str, re.Pattern[bytes]]
) -> list[str] | None:
    """Return findings for recognized evidence, or None for ordinary raw data."""
    # Lazy import avoids changing the dependency path for module initialization.
    import tool_evidence as evidence

    if not data.lstrip().startswith(
        (b"{", b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff", b"\x00")
    ):
        return None
    if len(data) > evidence.MAX_ARTIFACT_BYTES:
        # Classifying an oversized JSON object by a literal schema substring is
        # unsafe: its metadata can be escaped or follow a large encoded body.
        # Refuse the whole JSON candidate before allocating a parsed document.
        return [INVALID_ENVELOPE]
    try:
        text = data.decode("utf-8", errors="strict")
        payload = evidence._strict_json(text)
    except (ValueError, UnicodeError, RecursionError):
        return [INVALID_ENVELOPE] if _looks_like_invalid_envelope(data) else None
    if not _is_envelope(payload):
        return None
    try:
        report = evidence.verify_evidence(payload)
        if report["valid"] is not True:
            return [INVALID_ENVELOPE]
        approved: dict[tuple[Any, ...], str] = {}
        hits: set[str] = set()
        for index, call in enumerate(payload["calls"]):
            if call.get("response") is None:
                continue
            encoded = call["response"]["bodyBase64"]
            # verify_evidence already checked canonical encoding, full size/hash,
            # HTTP identity, per-response/total bounds and offline replay.
            body = base64.b64decode(encoded, validate=True)
            hits.update(
                name for name, pattern in patterns.items() if pattern.search(body)
            )
            approved[("calls", index, "response", "bodyBase64")] = encoded
        spans, string_hits = _string_projection(text, approved, patterns)
        hits.update(string_hits)
        cursor = 0
        for start, end in spans:
            fragment = text[cursor:start].encode("utf-8")
            hits.update(
                name for name, pattern in patterns.items() if pattern.search(fragment)
            )
            cursor = end
        fragment = text[cursor:].encode("utf-8")
        hits.update(
            name for name, pattern in patterns.items() if pattern.search(fragment)
        )
        return [name for name in patterns if name in hits]
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError):
        # No credential, captured value, or parser detail belongs in diagnostics.
        return [INVALID_ENVELOPE]
