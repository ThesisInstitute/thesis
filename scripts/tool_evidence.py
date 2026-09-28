#!/usr/bin/env python3
"""Capture and replay bounded public tool evidence; custody is handled by Receipt.

This module makes no signature or source-truth claim. An offline replay checks
the bytes, extraction and arithmetic in the supplied artifact. Receipt custody
and the runner's MCP event binding establish which artifact the runner archived.
Redirects are deliberately refused. Bodies are complete or the call fails;
excerpts returned to the model are explicitly bounded views of those bodies.
"""

from __future__ import annotations

import argparse
import ast
import base64
import binascii
import datetime as dt
import hashlib
import http.client
import json
import math
import os
import pathlib
import re
import statistics
import tempfile
import urllib.parse
from collections.abc import Callable
from typing import Any

import announcement_fetch_mcp as transport
from canonical_json import canonical_stringify

SCHEMA_VERSION = "thesis_tool_evidence_v1"
CAPTURE_METHOD = "thesis-controlled-tools-v1"
VERIFICATION_SCHEMA_VERSION = "thesis_tool_evidence_verification_v1"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_CALLS = 128
MAX_ARGUMENT_BYTES = 32 * 1024
MAX_ARTIFACT_BYTES = 52 * 1024 * 1024
EXCERPT_BYTES = 8 * 1024
MAX_JSON_RESULT_BYTES = 32 * 1024
MAX_IRS_SOI_ROWS = 512
MAX_IRS_SOI_COLUMNS = 512
MAX_IRS_SOI_SHEETS = 16
TOOLS = frozenset({"fetch_source", "extract_json", "extract_irs_soi", "calculate"})
REDACTED_URL = "[redacted: unsafe URL]"
REDACTED_PLACEHOLDER = "[REDACTED]"
REDACTED_JSON = "[redacted: unsafe JSON presentation]"
MAX_REDACTION_JSON_DEPTH = 64
TERMINAL_PROJECTION_VERSION = 1
# Shared with the runner: sanitize the MCP presentation before it enters the
# native stream, rather than changing only one side of the custody binding.
ENV_SECRET_ASSIGNMENT_RE = re.compile(
    r"([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)=\S+"
)
SECRET_FIELD_NAME_RE = re.compile(
    r"[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*", re.IGNORECASE
)
JSON_SECRET_FIELD_RE = re.compile(
    r"\"([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)\"\s*:\s*\"[^\"]*\"",
    re.IGNORECASE,
)
SECRET_TOKEN_RE = re.compile(
    "|".join(
        [
            r"sk-(?:ant|proj|or)-[A-Za-z0-9_-]+",
            r"sk-[A-Za-z0-9]{20,}",
            r"ghp_[A-Za-z0-9]+",
            r"github_pat_[A-Za-z0-9_]+",
            r"xox[bp]-[A-Za-z0-9-]+",
            r"AIza[A-Za-z0-9_-]+",
            r"eyJhbGciOi[A-Za-z0-9_.=-]+",
            r"AKIA[A-Z0-9]+",
        ]
    )
)
REQUEST_HEADERS = {
    "Accept": "application/json,text/plain,text/html,*/*;q=0.1",
    "Accept-Encoding": "identity",
    "User-Agent": "Mozilla/5.0 (compatible; thesis-tool-evidence/1.0)",
}
_SENSITIVE_QUERY_NAMES = frozenset(
    {
        "key",
        "apikey",
        "accesskey",
        "token",
        "accesstoken",
        "refreshtoken",
        "idtoken",
        "auth",
        "authorization",
        "password",
        "passwd",
        "secret",
        "clientsecret",
        "signature",
        "sig",
        "credential",
        "credentials",
        "code",
        "session",
        "sessionid",
        "jwt",
        "xamzsecuritytoken",
        "xamzsignature",
        "xamzcredential",
        "xgoogsignature",
        "xgoogcredential",
    }
)


class EvidenceError(ValueError):
    """A call or evidence artifact cannot satisfy the bounded contract."""


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def empty_evidence() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "captureMethod": CAPTURE_METHOD,
        "calls": [],
    }


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def url_contains_credentials(value: str) -> bool:
    """Shared refusal/redaction rule; never return the credential or its value."""
    try:
        parsed = urllib.parse.urlsplit(value)
        user_info = parsed.username is not None or parsed.password is not None
        query = parsed.query
        fragment = parsed.fragment
    except ValueError:
        # Even malformed IPv6 URLs can carry credentials. Their syntax error is
        # not permission to preserve user-info in a public native trace.
        authority = value.split("?", 1)[0].split("://", 1)[-1].split("/", 1)[0]
        user_info = "@" in authority
        query = value.split("?", 1)[1].split("#", 1)[0] if "?" in value else ""
        fragment = value.split("#", 1)[1] if "#" in value else ""
    if user_info:
        return True
    for key, _value in urllib.parse.parse_qsl(
        query + "&" + fragment, keep_blank_values=True
    ):
        normalized = re.sub(r"[^a-z0-9]", "", key.lower())
        if normalized in _SENSITIVE_QUERY_NAMES or normalized.endswith(
            ("token", "password", "secret", "signature", "credential", "apikey")
        ):
            return True
    return False


def redact_text(text: str) -> str:
    """Redact credential values from plain text (idempotent)."""
    if not text:
        return text
    text = re.sub(
        r"https?://[^\s\"'<>\\]+",
        lambda match: REDACTED_URL if url_contains_credentials(match[0]) else match[0],
        text,
        flags=re.IGNORECASE,
    )
    text = ENV_SECRET_ASSIGNMENT_RE.sub(rf"\1={REDACTED_PLACEHOLDER}", text)
    text = JSON_SECRET_FIELD_RE.sub(rf'"\1": "{REDACTED_PLACEHOLDER}"', text)
    return SECRET_TOKEN_RE.sub(REDACTED_PLACEHOLDER, text)


def _within_json_presentation_depth(value: str) -> bool:
    depth = 0
    quoted = False
    escaped = False
    for char in value:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_REDACTION_JSON_DEPTH:
                return False
        elif char in "]}":
            depth -= 1
    return True


def _within_container_depth(value: Any, limit: int) -> bool:
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if isinstance(item, (dict, list)):
            depth += 1
            if depth > limit:
                return False
            children = item.values() if isinstance(item, dict) else item
            pending.extend((child, depth) for child in children)
    return True


def _redact_incomplete_json(value: str) -> str:
    # Keep historical benign/truncated excerpts byte-compatible with the plain
    # text sanitizer. Escaped keys/values and unfinished credential values need
    # a safe marker because that sanitizer cannot interpret their JSON syntax.
    for match in re.finditer(r'("(?:[^"\\]|\\.)*")\s*:\s*', value):
        try:
            name = json.loads(match[1])
        except ValueError:
            return REDACTED_JSON
        if not SECRET_FIELD_NAME_RE.fullmatch(name):
            continue
        tail = value[match.end() :]
        if not tail.startswith('"'):
            continue
        try:
            _decoded, end = json.JSONDecoder().raw_decode(tail)
        except ValueError:
            return REDACTED_JSON
        if "\\" in match[1] or "\\" in tail[:end]:
            return REDACTED_JSON
    return redact_text(value)


def _redact_json_string(value: str) -> str:
    if value in {REDACTED_URL, REDACTED_PLACEHOLDER, REDACTED_JSON}:
        return value
    if re.match(r"https?://", value, re.IGNORECASE) and url_contains_credentials(value):
        return REDACTED_URL
    if value.lstrip().startswith(("{", "[")):
        if not _within_json_presentation_depth(value):
            return REDACTED_JSON
        try:
            nested = _strict_json(value)
        except EvidenceError:
            return _redact_incomplete_json(value)
        redacted = redact_json_value(nested)
        if redacted == nested:
            return value
        try:
            return canonical_stringify(redacted)
        except (ValueError, OverflowError, RecursionError):
            # A syntactically valid JSON number can overflow during parsing.
            # Never let an unrepresentable public excerpt crash the MCP reply.
            return REDACTED_JSON
    return redact_text(value)


def redact_json_value(value: Any) -> Any:
    """Preserve JSON shape, including an MCP text block's serialized JSON.

    Walk containers iteratively: a bounded source excerpt can still contain
    hundreds of nested arrays. Encoded JSON strings have their own depth limit,
    independent of the extra native event wrapper, so repeated projection is
    idempotent. Never apply text regexes to an entire serialized terminal object.
    """
    result: list[Any] = [None]
    pending: list[tuple[Any, Any, Any]] = [(value, result, 0)]
    while pending:
        item, parent, key = pending.pop()
        if isinstance(item, str):
            parent[key] = _redact_json_string(item)
        elif isinstance(item, list):
            shaped: Any = [None] * len(item)
            parent[key] = shaped
            pending.extend((child, shaped, index) for index, child in enumerate(item))
        elif isinstance(item, dict):
            shaped = {}
            parent[key] = shaped
            for name, child in item.items():
                safe_name = redact_text(name) if isinstance(name, str) else name
                if (
                    isinstance(name, str)
                    and SECRET_FIELD_NAME_RE.fullmatch(name)
                    and isinstance(child, str)
                ):
                    shaped[safe_name] = REDACTED_PLACEHOLDER
                else:
                    pending.append((child, shaped, safe_name))
        else:
            parent[key] = item
    return result[0]


def validate_public_url(value: Any) -> str:
    """Validate without echoing credentials. DNS is vetted at connection time."""
    if not isinstance(value, str) or len(value) > 4096:
        raise EvidenceError("URL must be a bounded public HTTPS URL")
    if any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise EvidenceError("URL contains whitespace or control characters")
    try:
        parsed = urllib.parse.urlsplit(value)
        host = parsed.hostname
        port = parsed.port
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or port not in {None, 443}
            or "%" in host
        ):
            raise EvidenceError(
                "only public HTTPS URLs on port 443 without credentials or fragments "
                "are allowed"
            )
        if url_contains_credentials(value):
            raise EvidenceError("credential-bearing URLs are refused")
        # http.client's ASCII request target must be explicit, never transformed
        # silently into a different URL. Callers percent-encode non-ASCII paths.
        value.encode("ascii")
        if host.lower().rstrip(".") == "localhost":
            raise EvidenceError("non-public hosts are refused")
        try:
            address = transport._ip_address(host)
        except ValueError:
            pass
        else:
            if not address.is_global or address.is_multicast:
                raise EvidenceError("non-public addresses are refused")
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError("invalid public HTTPS URL") from exc
    return value


def fetch_public_https(url: str) -> dict[str, Any]:
    """Fetch without proxies, cookies, redirects, or a second DNS resolution.

    Reuses the exact pinned-socket/TLS protections of the announcement tool.
    All HTTP status bodies, including errors, are archived if within the limit.
    Response headers omit Set-Cookie so ephemeral server credentials stay private.
    """
    validate_public_url(url)
    parsed = urllib.parse.urlsplit(url)
    destinations = transport._resolve_public_destinations(url)
    target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    last_error: Exception | None = None
    for destination in destinations:
        connection = transport._PinnedHTTPSConnection(
            parsed.hostname, 443, destination, timeout=transport.FETCH_TIMEOUT_SECONDS
        )
        try:
            connection.request("GET", target, headers=REQUEST_HEADERS)
            response = connection.getresponse()
            if type(response.status) is not int or not 100 <= response.status <= 599:
                raise EvidenceError("invalid HTTP response status")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(min(64 * 1024, MAX_RESPONSE_BYTES + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise EvidenceError("response exceeds the complete-body limit")
                chunks.append(chunk)
            body = b"".join(chunks)
            lengths = response.headers.get_all("Content-Length", [])
            if lengths and (
                any(not item.isdigit() for item in lengths)
                or len(set(lengths)) != 1
                or int(lengths[0]) != len(body)
            ):
                raise EvidenceError("response body does not match Content-Length")
            headers = [
                [name.lower(), value]
                for name, value in response.headers.items()
                if name.lower() not in {"set-cookie", "set-cookie2"}
            ]
            if len(_json_bytes(headers)) > 64 * 1024:
                raise EvidenceError("response headers exceed the capture limit")
            return {
                "url": url,
                "status": response.status,
                "headers": headers,
                "bodyBase64": base64.b64encode(body).decode("ascii"),
                "sha256": hashlib.sha256(body).hexdigest(),
                "bytes": len(body),
            }
        except (OSError, http.client.HTTPException) as exc:
            last_error = exc
        finally:
            connection.close()
    raise EvidenceError(
        f"HTTPS transport failed ({type(last_error).__name__})"
    ) from last_error


def _decode_response(response: Any, url: str) -> bytes:
    required = {"url", "status", "headers", "bodyBase64", "sha256", "bytes"}
    if not isinstance(response, dict) or set(response) != required:
        raise EvidenceError("response must include its complete embedded body")
    if response["url"] != url:
        raise EvidenceError("response URL does not match the requested URL")
    validate_public_url(url)
    if type(response["status"]) is not int or not 100 <= response["status"] <= 599:
        raise EvidenceError("invalid HTTP response status")
    headers = response["headers"]
    if not isinstance(headers, list) or len(_json_bytes(headers)) > 64 * 1024:
        raise EvidenceError("invalid response headers")
    for item in headers:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(part, str) for part in item)
            or item[0] != item[0].lower()
            or item[0] in {"set-cookie", "set-cookie2"}
        ):
            raise EvidenceError("invalid response header entry")
    encoded = response["bodyBase64"]
    if (
        not isinstance(encoded, str)
        or len(encoded) > ((MAX_RESPONSE_BYTES + 2) // 3) * 4
    ):
        raise EvidenceError("invalid or oversized response body")
    try:
        body = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise EvidenceError("response body is not valid base64") from exc
    if base64.b64encode(body).decode("ascii") != encoded:
        raise EvidenceError("response body is not canonical base64")
    if (
        len(body) > MAX_RESPONSE_BYTES
        or type(response["bytes"]) is not int
        or response["bytes"] != len(body)
    ):
        raise EvidenceError("response byte count does not match its body")
    if response["sha256"] != hashlib.sha256(body).hexdigest():
        raise EvidenceError("response SHA-256 does not match its body")
    return body


def _fetch_result(response: dict[str, Any], body: bytes) -> dict[str, Any]:
    content_type = next(
        (value for name, value in response["headers"] if name == "content-type"), ""
    )
    return {
        "url": response["url"],
        "status": response["status"],
        "sha256": response["sha256"],
        "bytes": len(body),
        "contentType": content_type,
        "excerpt": body[:EXCERPT_BYTES].decode("utf-8", errors="replace"),
        "excerptTruncated": len(body) > EXCERPT_BYTES,
    }


def _strict_json(data: str | bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise EvidenceError("ambiguous duplicate JSON object key")
            result[key] = value
        return result

    def constant(_value: str) -> None:
        raise EvidenceError("non-finite JSON number")

    try:
        return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise EvidenceError("response is not unambiguous finite JSON") from exc


def _prior_call(call_id: Any, previous: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(call_id, str) or call_id not in previous:
        raise EvidenceError("source call ID must refer to an earlier captured call")
    call = previous[call_id]
    if call["status"] != "succeeded":
        raise EvidenceError("source call did not succeed")
    return call


def _extract_result(arguments: dict[str, Any], previous: dict) -> dict[str, Any]:
    if set(arguments) != {"sourceCallId", "pointer"}:
        raise EvidenceError("extract_json requires sourceCallId and pointer")
    source = _prior_call(arguments["sourceCallId"], previous)
    if source["tool"] != "fetch_source":
        raise EvidenceError("JSON extraction requires a captured fetch_source call")
    pointer = arguments["pointer"]
    if not isinstance(pointer, str) or len(pointer) > 2048:
        raise EvidenceError("JSON pointer must be a bounded string")
    if pointer and not pointer.startswith("/"):
        raise EvidenceError("JSON pointer must be empty or begin with a slash")
    body = _decode_response(source["response"], source["arguments"]["url"])
    value = _strict_json(body)
    for raw_token in pointer.split("/")[1:] if pointer else []:
        if re.search(r"~(?![01])", raw_token):
            raise EvidenceError("invalid JSON pointer escape")
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", token):
            if len(token) > 9 or int(token) >= len(value):
                raise EvidenceError("JSON pointer array index does not exist")
            value = value[int(token)]
        else:
            raise EvidenceError("JSON pointer does not identify a value")
    if len(_json_bytes(value)) > MAX_JSON_RESULT_BYTES:
        raise EvidenceError("extracted value exceeds the result limit")
    return {"value": value}


def _extract_irs_soi_result(
    arguments: dict[str, Any], previous: dict
) -> dict[str, Any]:
    """Replay a reviewed Table 3.3 adapter against an earlier captured body.

    The official URL and printed tax year identify the requested workbook;
    neither they nor this extraction authenticate its publication vintage.
    Anchor years are parser checks, not a limit on available history.
    """

    if set(arguments) != {"sourceCallId", "seriesId", "year"}:
        raise EvidenceError("extract_irs_soi requires sourceCallId, seriesId, and year")
    series_id, year = arguments["seriesId"], arguments["year"]
    if not isinstance(year, str) or not re.fullmatch(r"[0-9]{4}", year):
        raise EvidenceError("IRS SOI year must be an ASCII YYYY string")
    try:
        import resolve_pending as resolver
    except ImportError as exc:
        raise EvidenceError("reviewed IRS SOI adapters are unavailable") from exc
    if (
        not isinstance(series_id, str)
        or series_id not in resolver.IRS_SOI_PUB1304_ADAPTERS
    ):
        raise EvidenceError("seriesId must identify a reviewed IRS SOI adapter")
    spec = resolver.IRS_SOI_PUB1304_ADAPTERS[series_id]
    source = _prior_call(arguments["sourceCallId"], previous)
    if source["tool"] != "fetch_source":
        raise EvidenceError("IRS SOI extraction requires a captured fetch_source call")
    expected_url = spec["file_url_template"].format(yy=year[-2:], ext="xls")
    source_url = source["arguments"].get("url")
    if source_url != expected_url:
        raise EvidenceError("source URL is not the exact official IRS SOI year URL")
    body = _decode_response(source["response"], source_url)
    if not 200 <= source["response"]["status"] <= 299:
        raise EvidenceError("IRS SOI source has an unsuccessful HTTP status")

    # The bounded loader reads only the selected sheet and checks dimensions
    # before materializing its grid. Parser diagnostics must not enter MCP's
    # stdout protocol; the complete input bytes remain in the source call.
    try:
        grid, refusal = resolver.irs_soi_pub1304_grid(
            body,
            spec,
            max_rows=MAX_IRS_SOI_ROWS,
            max_columns=MAX_IRS_SOI_COLUMNS,
            max_sheets=MAX_IRS_SOI_SHEETS,
            quiet=True,
        )
    except Exception as exc:
        # Parser exceptions may contain untrusted workbook cell strings.
        raise EvidenceError(
            f"IRS SOI workbook parsing failed ({type(exc).__name__})"
        ) from exc
    if refusal or grid is None:
        reason = redact_text(str(refusal or "missing workbook grid"))[:1024]
        raise EvidenceError(f"IRS SOI workbook loader refused: {reason}")
    refusal = resolver.irs_soi_pub1304_identity_refusal(grid, source_url, year)
    if refusal:
        raise EvidenceError(f"IRS SOI identity refused: {redact_text(refusal)[:1024]}")
    raw_value, refusal = resolver.irs_soi_pub1304_count_from_grid(grid, spec)
    if refusal or raw_value is None:
        reason = redact_text(str(refusal or "missing published value"))[:1024]
        raise EvidenceError(f"IRS SOI table contract refused: {reason}")
    if (
        type(raw_value) not in {int, float}
        or not math.isfinite(raw_value)
        or not 0 <= raw_value <= 2**53 - 1
        or int(raw_value) != raw_value
    ):
        raise EvidenceError("IRS SOI raw value must be a nonnegative safe integer")
    value = resolver.irs_soi_pub1304_apply_transform(spec, raw_value)
    if type(value) not in {int, float} or not math.isfinite(value):
        raise EvidenceError("IRS SOI transformed value must be finite")
    return {
        "value": value,
        "sourceCallId": arguments["sourceCallId"],
        "sourceSha256": source["response"]["sha256"],
        "sourceUrl": source_url,
        "seriesId": series_id,
        "year": year,
        "rawValue": int(raw_value),
        "unit": spec["unit"],
        "transform": dict(spec["value_transform"]),
    }


def _number(value: Any) -> int | float:
    if type(value) not in {int, float}:
        raise EvidenceError("calculator values must be finite numbers, not booleans")
    try:
        if not math.isfinite(value) or abs(value) > 1e100:
            raise EvidenceError("calculator value exceeds the finite numeric range")
    except OverflowError as exc:
        raise EvidenceError(
            "calculator value exceeds the finite numeric range"
        ) from exc
    return value


def _numeric_input(value: Any, *, source_strings: bool = False) -> Any:
    if isinstance(value, list):
        if len(value) > 512 or any(isinstance(item, list) for item in value):
            raise EvidenceError("calculator arrays require at most 512 scalar values")
        return [_numeric_input(item, source_strings=source_strings) for item in value]
    if isinstance(value, str) and source_strings:
        if len(value) > 128 or not re.fullmatch(
            r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", value
        ):
            raise EvidenceError("source string is not a strict JSON number")
        value = float(value) if any(char in value for char in ".eE") else int(value)
    return _number(value)


def _calculate_result(arguments: dict[str, Any], previous: dict) -> dict[str, Any]:
    if set(arguments) != {"expression", "inputs"}:
        raise EvidenceError("calculate requires expression and inputs")
    expression, inputs = arguments["expression"], arguments["inputs"]
    if not isinstance(expression, str) or len(expression) > 2048:
        raise EvidenceError("expression must be a bounded string")
    if not isinstance(inputs, dict) or len(inputs) > 64:
        raise EvidenceError("inputs must be an object of at most 64 named numbers")
    resolved = {}
    for name, source in inputs.items():
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_]{0,63}", name
        ):
            raise EvidenceError("invalid calculator input name")
        is_reference = isinstance(source, dict)
        if is_reference:
            if set(source) != {"callId"}:
                raise EvidenceError("referenced input requires exactly callId")
            call = _prior_call(source["callId"], previous)
            if call["tool"] not in {"extract_json", "extract_irs_soi", "calculate"}:
                raise EvidenceError("input call must be an extraction or calculation")
            source = call["result"]["value"]
        resolved[name] = _numeric_input(source, source_strings=is_reference)
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, RecursionError) as exc:
        raise EvidenceError("invalid arithmetic expression") from exc
    if sum(1 for _ in ast.walk(tree)) > 256:
        raise EvidenceError("expression exceeds the operation limit")

    def evaluate(node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return _number(node.value)
        if isinstance(node, ast.Name) and node.id in resolved:
            return resolved[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = _number(evaluate(node.operand))
            return _number(value if isinstance(node.op, ast.UAdd) else -value)
        if isinstance(node, ast.BinOp):
            left, right = _number(evaluate(node.left)), _number(evaluate(node.right))
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            elif isinstance(node.op, ast.Mult):
                value = left * right
            elif isinstance(node.op, ast.Div):
                value = left / right
            elif isinstance(node.op, ast.FloorDiv):
                value = left // right
            elif isinstance(node.op, ast.Mod):
                value = left % right
            elif isinstance(node.op, ast.Pow):
                if abs(right) > 32:
                    raise EvidenceError("power exponent exceeds the operation limit")
                value = left**right
            else:
                raise EvidenceError("unsupported arithmetic operator")
            return _number(value)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.keywords or len(node.args) > 64:
                raise EvidenceError("unsupported calculator function arguments")
            values = [evaluate(argument) for argument in node.args]
            name = node.func.id
            if name in {"mean", "median", "stdev", "diff", "min", "max"}:
                samples = (
                    values[0]
                    if len(values) == 1 and isinstance(values[0], list)
                    else values
                )
                samples = [_number(sample) for sample in samples]
                if not samples:
                    raise EvidenceError("statistics require at least one value")
                if name == "diff":
                    if len(samples) < 2:
                        raise EvidenceError("diff requires at least two values")
                    return [_number(b - a) for a, b in zip(samples, samples[1:])]
                functions = {
                    "mean": statistics.mean,
                    "median": statistics.median,
                    "stdev": statistics.stdev,
                    "min": min,
                    "max": max,
                }
                return _number(functions[name](samples))
            values = [_number(value) for value in values]
            if name == "abs" and len(values) == 1:
                return _number(abs(values[0]))
            if name == "sqrt" and len(values) == 1:
                return _number(math.sqrt(values[0]))
            if name == "round" and len(values) in {1, 2}:
                if len(values) == 2 and (
                    type(values[1]) is not int or abs(values[1]) > 15
                ):
                    raise EvidenceError(
                        "round precision must be an integer from -15 to 15"
                    )
                return _number(round(*values))
            raise EvidenceError("unsupported calculator function")
        raise EvidenceError("expression contains unsupported syntax")

    try:
        value = evaluate(tree.body)
    except (ArithmeticError, ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError("arithmetic operation has no finite real result") from exc
    return {"value": value, "resolvedInputs": resolved}


def _check_arguments(arguments: Any) -> None:
    if (
        not isinstance(arguments, dict)
        or len(_json_bytes(arguments)) > MAX_ARGUMENT_BYTES
    ):
        raise EvidenceError("tool arguments must be a bounded JSON object")


def captured_arguments(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Public argument projection, also applied to matching native MCP events.

    Only refused fetch requests lose their unsafe URL/extra fields. A successful
    fetch and every calculation/extraction retain their exact arguments. Event
    verifiers may use this projection only for failed, explicitly redacted fetch
    calls, so a valid native request cannot masquerade as a credential refusal.
    """
    _check_arguments(arguments)
    if tool == "fetch_source":
        if set(arguments) != {"url"}:
            return {"url": REDACTED_URL}
        try:
            validate_public_url(arguments["url"])
        except EvidenceError:
            return {"url": REDACTED_URL}
    return arguments


def verify_evidence(payload: Any) -> dict[str, Any]:
    """Replay without network or local file access. Failure captures stay failures."""
    report: dict[str, Any] = {
        "schemaVersion": VERIFICATION_SCHEMA_VERSION,
        "captureMethod": CAPTURE_METHOD,
        "valid": False,
        "errors": [],
        "callCount": 0,
        "succeededCount": 0,
        "failedCount": 0,
        "checks": [],
    }
    try:
        encoded = _json_bytes(payload)
        report["evidenceCanonicalSha256"] = hashlib.sha256(encoded).hexdigest()
        if len(encoded) > MAX_ARTIFACT_BYTES:
            raise EvidenceError("evidence exceeds the artifact size limit")
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schemaVersion", "captureMethod", "calls"}
            or payload["schemaVersion"] != SCHEMA_VERSION
            or payload["captureMethod"] != CAPTURE_METHOD
            or not isinstance(payload["calls"], list)
            or len(payload["calls"]) > MAX_CALLS
        ):
            raise EvidenceError("invalid tool evidence envelope")
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        report["errors"].append(str(exc))
        return report

    previous: dict[str, dict[str, Any]] = {}
    total_bytes = 0
    for index, call in enumerate(payload["calls"], 1):
        call_id = f"call-{index:04d}"
        report["callCount"] += 1
        checks: list[str] = []
        try:
            required = {
                "callId",
                "tool",
                "arguments",
                "startedAt",
                "completedAt",
                "status",
                "result",
            }
            if not isinstance(call, dict) or not required <= call.keys():
                raise EvidenceError("invalid call envelope")
            optional = {"response", "error", "terminalProjectionVersion"}
            if set(call) - required - optional:
                raise EvidenceError("unknown call fields")
            if "terminalProjectionVersion" in call and (
                type(call["terminalProjectionVersion"]) is not int
                or call["terminalProjectionVersion"] != TERMINAL_PROJECTION_VERSION
            ):
                raise EvidenceError("unsupported terminal projection version")
            if call["callId"] != call_id or call["tool"] not in TOOLS:
                raise EvidenceError("call ID/order or tool name is invalid")
            times = []
            for field in ("startedAt", "completedAt"):
                if not isinstance(call[field], str):
                    raise EvidenceError("call timestamp is not an ISO UTC timestamp")
                timestamp = dt.datetime.fromisoformat(
                    call[field].replace("Z", "+00:00")
                )
                if timestamp.tzinfo is None or timestamp.utcoffset() != dt.timedelta(0):
                    raise EvidenceError("call timestamp is not UTC")
                times.append(timestamp)
            if times[1] < times[0]:
                raise EvidenceError("call completion precedes its start")
            _check_arguments(call["arguments"])
            status = call["status"]
            if status not in {"succeeded", "failed"}:
                raise EvidenceError("call has no terminal status")
            response = call.get("response")
            if response is not None:
                if call["tool"] != "fetch_source" or set(call["arguments"]) != {"url"}:
                    raise EvidenceError("only a fetch may contain an HTTP response")
                body = _decode_response(response, call["arguments"]["url"])
                total_bytes += len(body)
                if total_bytes > MAX_TOTAL_RESPONSE_BYTES:
                    raise EvidenceError("total captured response limit exceeded")
                checks.extend(["response_sha256", "response_bytes"])
            if status == "failed":
                if (
                    call["result"] is not None
                    or not isinstance(call.get("error"), str)
                    or not call["error"]
                    or len(call["error"]) > 2048
                ):
                    raise EvidenceError("failed call requires an error and no result")
                report["failedCount"] += 1
                report["checks"].append(
                    {"callId": call_id, "status": "failed", "checks": checks}
                )
            else:
                if "error" in call:
                    raise EvidenceError("successful call contains an error")
                if call["tool"] == "fetch_source":
                    if response is None:
                        raise EvidenceError(
                            "successful fetch is missing its response body"
                        )
                    if not 200 <= response["status"] <= 299:
                        raise EvidenceError(
                            "successful fetch has an unsuccessful HTTP status"
                        )
                    expected = _fetch_result(response, body)
                    checks.append("fetch_result")
                    replay_status = "captured"
                elif call["tool"] == "extract_json":
                    expected = _extract_result(call["arguments"], previous)
                    checks.append("json_pointer_replay")
                    replay_status = "replayed"
                elif call["tool"] == "extract_irs_soi":
                    expected = _extract_irs_soi_result(call["arguments"], previous)
                    checks.append("irs_soi_workbook_replay")
                    replay_status = "replayed"
                else:
                    expected = _calculate_result(call["arguments"], previous)
                    checks.append("arithmetic_replay")
                    replay_status = "replayed"
                if _json_bytes(call["result"]) != _json_bytes(expected):
                    raise EvidenceError("recorded result does not match replay")
                report["succeededCount"] += 1
                report["checks"].append(
                    {"callId": call_id, "status": replay_status, "checks": checks}
                )
            previous[call_id] = call
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            report["errors"].append(f"{call_id}: {exc}")
    report["valid"] = not report["errors"]
    return report


def load_evidence(path: str | pathlib.Path) -> dict[str, Any]:
    path = pathlib.Path(path)
    if path.is_symlink() or not path.is_file():
        raise EvidenceError("evidence must be a regular file, not a symlink")
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise EvidenceError("evidence exceeds the artifact size limit")
    payload = _strict_json(path.read_bytes())
    if not isinstance(payload, dict):
        raise EvidenceError("evidence must be a JSON object")
    return payload


def terminal_call(call: dict[str, Any]) -> dict[str, Any]:
    """Exact public MCP projection used both before reply and for native binding.

    The complete response and replayable result stay unchanged in the capture.
    Sanitizing this presentation before replying makes the runner's later
    credential hygiene pass idempotent, preserving exact native-event equality.
    """
    if "terminalProjectionVersion" not in call:
        # Historical native events bound the original projection. Never apply
        # a new presentation policy retroactively or accept either projection.
        return {key: value for key, value in call.items() if key != "response"}
    if (
        type(call["terminalProjectionVersion"]) is not int
        or call["terminalProjectionVersion"] != TERMINAL_PROJECTION_VERSION
    ):
        raise EvidenceError("unsupported terminal projection version")
    # Reserve one level for this terminal object, so its serialized text block
    # stays within the same depth bound when the native stream redacts it again.
    # Keep call identity and raw evidence even when an extracted value is too
    # deeply nested for a useful presentation.
    return redact_json_value(
        {
            key: (
                value
                if _within_container_depth(value, MAX_REDACTION_JSON_DEPTH - 1)
                else REDACTED_JSON
            )
            for key, value in call.items()
            if key != "response"
        }
    )


class EvidenceRecorder:
    """One controlled server session, atomically persisted before each reply."""

    def __init__(
        self,
        output: str | pathlib.Path,
        *,
        fetcher: Callable[[str], dict[str, Any]] = fetch_public_https,
        allow_fetch: bool = True,
    ) -> None:
        self.output = pathlib.Path(output)
        if not self.output.parent.is_dir() or self.output.parent.is_symlink():
            raise EvidenceError("output parent must be an existing real directory")
        if self.output.is_symlink():
            raise EvidenceError("output must not be a symlink")
        if self.output.exists() and load_evidence(self.output) != empty_evidence():
            raise EvidenceError("refusing to overwrite a previous evidence session")
        self.payload = empty_evidence()
        self.fetcher = fetcher
        self.allow_fetch = allow_fetch
        self._total_response_bytes = 0
        self._write()

    def _write(self) -> None:
        encoded = _json_bytes(self.payload) + b"\n"
        if len(encoded) > MAX_ARTIFACT_BYTES:
            raise EvidenceError("evidence exceeds the artifact size limit")
        fd, temporary = tempfile.mkstemp(
            prefix=".tool-evidence-", dir=self.output.parent
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.output)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if len(self.payload["calls"]) >= MAX_CALLS:
            raise EvidenceError("tool session call limit reached")
        if tool not in TOOLS:
            raise EvidenceError("unknown evidence tool")
        _check_arguments(arguments)
        arguments = _strict_json(_json_bytes(arguments))
        call: dict[str, Any] = {
            "callId": f"call-{len(self.payload['calls']) + 1:04d}",
            "tool": tool,
            "terminalProjectionVersion": TERMINAL_PROJECTION_VERSION,
            "arguments": captured_arguments(tool, arguments),
            "startedAt": _now(),
            "completedAt": "",
            "status": "failed",
            "result": None,
        }
        previous = {item["callId"]: item for item in self.payload["calls"]}
        try:
            if tool == "fetch_source":
                if set(arguments) != {"url"}:
                    # No extra fields (including accidentally supplied credentials)
                    # are echoed into public evidence for this tool.
                    raise EvidenceError("fetch_source requires only a public URL")
                validate_public_url(arguments["url"])
                if not self.allow_fetch:
                    raise EvidenceError("source fetching is disabled for this stage")
                response = self.fetcher(arguments["url"])
                body = _decode_response(response, arguments["url"])
                if self._total_response_bytes + len(body) > MAX_TOTAL_RESPONSE_BYTES:
                    raise EvidenceError("total captured response limit exceeded")
                call["response"] = response
                self._total_response_bytes += len(body)
                if 300 <= response["status"] <= 399:
                    raise EvidenceError(
                        "HTTP redirect refused; request the final public URL explicitly"
                    )
                if not 200 <= response["status"] <= 299:
                    raise EvidenceError(f"source returned HTTP {response['status']}")
                result = _fetch_result(response, body)
            elif tool == "extract_json":
                result = _extract_result(arguments, previous)
            elif tool == "extract_irs_soi":
                result = _extract_irs_soi_result(arguments, previous)
            else:
                result = _calculate_result(arguments, previous)
            call["result"] = result
            call["status"] = "succeeded"
        except (EvidenceError, transport.FetchError) as exc:
            call["error"] = str(exc)[:2048]
        except Exception as exc:
            # Third-party/network errors can include sensitive request details.
            # Preserve the failure type, never arbitrary exception text.
            call["error"] = f"tool execution failed ({type(exc).__name__})"
        call["completedAt"] = _now()
        self.payload["calls"].append(call)
        self._write()
        return call


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        report = verify_evidence(load_evidence(args.verify))
    except (OSError, EvidenceError) as exc:
        report = {
            "schemaVersion": VERIFICATION_SCHEMA_VERSION,
            "valid": False,
            "errors": [str(exc)],
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
