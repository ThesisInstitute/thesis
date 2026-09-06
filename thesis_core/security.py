"""Shared credential hygiene for recorded agent runs and source capture.

This module is the single implementation of two independent defenses that the
repository already relied on, moved here so the legacy thesis.analyst runner,
the new `thesis_core` execution path and the source adapters all scrub with the
same code:

1. Recorded subprocesses run under a minimal explicit environment
   (``AGENT_ENV_ALLOWLIST``, an allowlist and never a denylist), so an ``env``
   dump inside an agent has nothing secret to print.
2. Every captured stream, response document, URL, header map and metadata
   payload is redacted *before* any artifact is written, hashed or
   content-addressed, so a secret read from disk or echoed by a tool never
   reaches a record and no post-hoc scrub can break an attestation.

Incident 2026-07-21: during an aging-wave batch, the codex agent ran
``env | rg -i 'CENSUS|API|KEY'`` while hunting for a Census API key, and 18
credential env vars inherited from the interactive shell landed verbatim in
recorded trace files; GitHub push protection was the only thing that kept them
out of the public repo.

Two properties are load-bearing and are pinned by tests:

* **Clean content is byte-identical.** Redacting text, a stream, a response
  document, a URL or a JSON payload that contains no credential returns the
  input unchanged. Evidence bytes are not reshaped by passing through here.
* **Redaction is idempotent.** Re-redacting redacted content is a no-op, so a
  value can be scrubbed at more than one boundary safely.

The module is standard library only, by design: `scripts/run_thesis_analyst.py`
and the source adapters must keep working in a checkout without the `core`
extra installed.

These functions are for text and JSON-compatible payloads only. Never route
opaque binary evidence through them — an RFC 3161 request/response DER, a
signature, a raw archived response body — because verification is over exact
bytes and any normalization would break it. Hash and store those as they
arrived; scrub the metadata that describes them instead.

Nothing here reads a keychain, a credential store or a secret file. It only
ever *removes* values that are already in front of it.
"""

from __future__ import annotations

import ast
import json
import keyword
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import unquote_plus, urlsplit, urlunsplit

__all__ = [
    "AGENT_ENV_ALLOWLIST",
    "CREDENTIAL_COLLAPSED_NEEDLES",
    "CREDENTIAL_WORD_PAIRS",
    "NON_CREDENTIAL_TRAILING_WORDS",
    "RedactionError",
    "ENV_SECRET_ASSIGNMENT_RE",
    "JSON_SECRET_FIELD_RE",
    "REDACTED_PLACEHOLDER",
    "SAFE_TRANSPORT_HEADERS",
    "SECRET_TOKEN_RE",
    "STANDALONE_CREDENTIAL_WORDS",
    "agent_subprocess_env",
    "credential_key_words",
    "is_credential_key",
    "redact_headers",
    "redact_json_value",
    "redact_response_text",
    "redact_stream_line",
    "redact_stream_text",
    "redact_text",
    "redact_url",
    "redact_value",
]


# --- Minimal subprocess environment -----------------------------------------

AGENT_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "TERM",
    "SHELL",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    # Non-secret directory path selecting which codex auth/config dir to use.
    "CODEX_HOME",
)


def agent_subprocess_env(
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Minimal explicit environment for recorded agent subprocesses."""
    env = {
        name: os.environ[name] for name in AGENT_ENV_ALLOWLIST if os.environ.get(name)
    }
    if overrides:
        env.update(overrides)
    return env


# --- Text-level credential patterns -----------------------------------------

REDACTED_PLACEHOLDER = "[REDACTED]"

# Match complete assignment candidates once, then classify their names. Putting
# a greedy prefix before KEY/TOKEN/etc. causes quadratic backtracking on output
# such as a long uppercase hex dump, even when no assignment exists.
ENV_SECRET_ASSIGNMENT_RE = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]+)=\S+")

# `"name": "value"` JSON fields with credential-shaped names — catches an
# agent cat-ing auth/config files (auth.json and friends) into its trace.
JSON_SECRET_FIELD_RE = re.compile(
    r'"([A-Z0-9_-]+)"\s*:\s*"([^"\r\n]*)"',
    re.IGNORECASE,
)

# Well-known credential token formats (the incident list plus legacy
# OpenAI `sk-` keys, which auth.json can hold under API-key login).
SECRET_TOKEN_RE = re.compile(
    "|".join(
        [
            r"sk-(?:ant|proj|or)-[A-Za-z0-9_-]+",  # Anthropic/OpenAI/OpenRouter
            r"sk-[A-Za-z0-9]{20,}",  # legacy OpenAI secret keys
            r"ghp_[A-Za-z0-9]+",  # GitHub classic PAT
            r"github_pat_[A-Za-z0-9_]+",  # GitHub fine-grained PAT
            r"xox[bp]-[A-Za-z0-9-]+",  # Slack bot/user tokens
            r"AIza[A-Za-z0-9_-]+",  # Google API keys
            r"eyJhbGciOi[A-Za-z0-9_.=-]+",  # JWTs (Supabase service keys, ...)
            r"AKIA[A-Z0-9]+",  # AWS access key ids
        ]
    )
)


def redact_text(text: str) -> str:
    """Redact credential values from plain text (idempotent)."""
    if not text:
        return text

    def assignment(match: re.Match[str]) -> str:
        name = match.group(1)
        # Lowercase URL query/fragment names belong to redact_url: treating
        # their entire remaining query as a CLI value would erase clean params.
        sensitive = any(
            word in name for word in ("KEY", "TOKEN", "SECRET", "PASSWORD")
        ) or (name.startswith("-") and is_credential_key(name))
        return f"{name}={REDACTED_PLACEHOLDER}" if sensitive else match.group(0)

    def json_field(match: re.Match[str]) -> str:
        name = match.group(1)
        if match.group(2) in ("", REDACTED_PLACEHOLDER):
            return match.group(0)
        return (
            f'"{name}": "{REDACTED_PLACEHOLDER}"'
            if _text_credential_name(name)
            else match.group(0)
        )

    text = ENV_SECRET_ASSIGNMENT_RE.sub(assignment, text)
    text = JSON_SECRET_FIELD_RE.sub(json_field, text)
    return SECRET_TOKEN_RE.sub(REDACTED_PLACEHOLDER, text)


def _text_credential_name(name: str) -> bool:
    # Preserve the historical conservative env-name defense while recognizing
    # lowercase/camel-case CLI and JSON names through the structural matcher.
    return any(
        word in name.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD")
    ) or is_credential_key(name)


# --- Credential-shaped names ------------------------------------------------
#
# The text patterns above only recognize credential *values*: a `NAME=value`
# assignment, a quoted JSON field in raw text, or a well-known token format.
# They cannot see an arbitrary opaque credential that arrives as a parsed value
# under a credential-shaped key — `{"api_key": "plain-secret"}` survives a
# value-wise text scrub because "plain-secret" matches no pattern. Source
# adapters hand us exactly that shape (query parameters, request headers,
# archived exchange metadata), so name matching is a separate, structural
# defense.
#
# Names are matched on words, not substrings, so that a credential-shaped word
# is required rather than merely contained: `input_tokens` (a usage count) and
# `dataKey` (an SDMX series key) survive, while `apiKey`, `X-Api-Key`,
# `ANTHROPIC_API_KEY`, `access_token`, `UserID` and `Set-Cookie` do not.

_KEY_WORD_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")

# Words that are credential-shaped standing alone.
STANDALONE_CREDENTIAL_WORDS = frozenset(
    {
        "authentication",
        "authorization",
        "bearer",
        "cookie",
        "cookies",
        "credential",
        "credentials",
        "passphrase",
        "passwd",
        "password",
        "pwd",
        "secret",
        "secrets",
        "token",
    }
)

# Adjacent word pairs that are credential-shaped together. Deliberately absent:
# ("session", "id") and ("account", "id"), which are correlation identifiers
# that agent traces legitimately carry. Bare "auth" is a pair prefix rather
# than a standalone word for the same reason: existing thesis.analyst traces
# record `"auth": "codex-cli-subscription"`, a non-secret provenance label.
CREDENTIAL_WORD_PAIRS = frozenset(
    {
        ("access", "key"),
        ("access", "token"),
        ("account", "key"),
        ("api", "key"),
        ("api", "secret"),
        ("api", "token"),
        ("app", "key"),
        ("application", "key"),
        ("auth", "credential"),
        ("auth", "header"),
        ("auth", "key"),
        ("auth", "secret"),
        ("auth", "token"),
        ("auth", "value"),
        ("bearer", "token"),
        ("client", "secret"),
        ("consumer", "key"),
        ("consumer", "secret"),
        ("csrf", "token"),
        ("encryption", "key"),
        ("id", "token"),
        ("license", "key"),
        ("private", "key"),
        ("refresh", "token"),
        ("registration", "key"),
        ("secret", "key"),
        ("security", "token"),
        ("session", "key"),
        ("session", "token"),
        ("shared", "key"),
        ("shared", "secret"),
        ("signing", "key"),
        ("subscription", "key"),
        ("user", "id"),
        ("xsrf", "token"),
    }
)

# Needles matched against the separator-free lowercase name, for keys written
# without any word boundary at all (`apikey`, `XAPIKEY`, `userid`). Bare
# "token" and bare "key" are deliberately excluded here: they would swallow
# `input_tokens` and `dataKey`. Bare "auth" is excluded because it is a
# substring of "author".
CREDENTIAL_COLLAPSED_NEEDLES = (
    "accesskey",
    "accesstoken",
    "apikey",
    "apisecret",
    "apitoken",
    "authorization",
    "authentication",
    "bearer",
    "clientsecret",
    "cookie",
    "credential",
    "csrftoken",
    "idtoken",
    "licensekey",
    "passphrase",
    "passwd",
    "password",
    "privatekey",
    "refreshtoken",
    "secret",
    "securitytoken",
    "sessiontoken",
    "signingkey",
    "subscriptionkey",
    "userid",
    "xsrftoken",
)

# A name that is exactly this, ignoring case and separators, is credential
# shaped on its own. `?key=` is the Google API-key query convention.
_EXACT_CREDENTIAL_NAMES = frozenset({"key"})

# A trailing word that describes a credential rather than carrying it: the
# *path* to a token file, the *sha256* of a timestamp token, the *size* of a
# key. Existing witness records use `tokenPath` and `tokenSha256` for public
# RFC 3161 evidence, and redacting those would destroy proof, not protect it.
# `records/trust/tsa-anchors-v1.json` likewise configures `maxTokenLeadSeconds`.
# "id" is deliberately absent so `UserID` stays credential-shaped.
NON_CREDENTIAL_TRAILING_WORDS = frozenset(
    {
        "alg",
        "algorithm",
        "at",
        "bytes",
        "count",
        "day",
        "days",
        "digest",
        "dir",
        "directory",
        "exists",
        "file",
        "filename",
        "format",
        "hash",
        "hour",
        "hours",
        "index",
        "length",
        "limit",
        "millis",
        "milliseconds",
        "minute",
        "minutes",
        "mode",
        "offset",
        "path",
        "policy",
        "present",
        "scheme",
        "sha1",
        "sha256",
        "second",
        "seconds",
        "sha512",
        "size",
        "status",
        "timestamp",
        "type",
        "uri",
        "url",
        "version",
    }
)

# Exact public settings/package names found in captured source pages. These
# names do not carry credentials, but their children still receive the normal
# recursive inspection. Adapter-declared credential names take precedence.
_PUBLIC_FIELD_NAMES = frozenset(
    {
        "historyfloorauthorization",
        "cookiecontentblocker",
        "cookiebot",
        "tough-cookie",
        "message_placeholder_cookieconsent_optout_marketing",
    }
)


def credential_key_words(name: str) -> tuple[str, ...]:
    """Split a key/parameter/header name into lowercase words.

    Handles `snake_case`, `kebab-case`, `camelCase`, `PascalCase`, SCREAMING
    case and acronym runs: ``UserID`` -> ``("user", "id")``, ``APIKey`` ->
    ``("api", "key")``, ``X-Api-Key`` -> ``("x", "api", "key")``.
    """
    if not name:
        return ()
    return tuple(word.lower() for word in _KEY_WORD_RE.findall(name))


def is_credential_key(name: Any, extra: Iterable[str] = ()) -> bool:
    """Return True when a key/parameter/header name should hide its value.

    ``extra`` carries adapter-declared credential-bearing names (the plan's
    "adapters declare credential-bearing URL parameters and headers"); they are
    compared case-insensitively and ignoring separators, so an adapter may
    declare ``UserID``, ``userid`` or ``user_id`` interchangeably.
    """
    if not isinstance(name, str) or not name:
        return False
    words = credential_key_words(name)
    if not words:
        return False
    collapsed = "".join(words)
    for declared in extra:
        if not isinstance(declared, str):
            continue
        if "".join(credential_key_words(declared)) == collapsed:
            return True
    if name.casefold() in _PUBLIC_FIELD_NAMES:
        return False
    if words[-1] in NON_CREDENTIAL_TRAILING_WORDS:
        # A path to, hash of, or size of a credential is not the credential.
        return False
    if collapsed in _EXACT_CREDENTIAL_NAMES:
        return True
    if any(word in STANDALONE_CREDENTIAL_WORDS for word in words):
        return True
    if any(pair in CREDENTIAL_WORD_PAIRS for pair in zip(words, words[1:])):
        return True
    return any(needle in collapsed for needle in CREDENTIAL_COLLAPSED_NEEDLES)


def _redacted_for_credential_key(value: Any) -> Any:
    """Replace a value held under a credential-shaped key.

    ``None`` and booleans carry no secret and are preserved so a payload keeps
    its shape; an empty string is preserved for the same reason. Everything
    else — strings, numbers, objects, arrays — collapses to the placeholder,
    because a credential may hide anywhere inside it.
    """
    if value is None or isinstance(value, bool) or value == "":
        return value
    return REDACTED_PLACEHOLDER


# --- URLs -------------------------------------------------------------------

_URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")

# Path segments that unambiguously introduce a credential as the next segment
# (`/token/<value>`). Bare "key" is excluded: official series paths use it
# (SDMX data keys) and mangling an evidence URL is worse than the residual
# risk, which adapter-declared parameters cover.
_CREDENTIAL_PATH_LABELS = frozenset(
    {
        "apikey",
        "accesstoken",
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
        "token",
    }
)


def _safe_unquote(text: str) -> str:
    """Percent-decode a URL key without ever raising on malformed input."""
    try:
        return unquote_plus(text, errors="replace")
    except (UnicodeDecodeError, ValueError):  # pragma: no cover - defensive
        return text


def _redact_param_string(
    raw: str, separator: str, credential_params: Iterable[str]
) -> tuple[str, bool]:
    """Redact `name=value` pairs in a query, fragment or matrix-param string.

    Non-sensitive pairs are copied through verbatim — including their original
    percent-encoding, ordering and empty segments — so a clean string is
    returned byte-identical.
    """
    if not raw:
        return raw, False
    changed = False
    pieces = []
    for piece in raw.split(separator):
        name, sep, value = piece.partition("=")
        if sep and value and is_credential_key(_safe_unquote(name), credential_params):
            pieces.append(f"{name}={REDACTED_PLACEHOLDER}")
            changed = True
        else:
            pieces.append(piece)
    return separator.join(pieces), changed


def _redact_url_path(path: str, credential_params: Iterable[str]) -> tuple[str, bool]:
    if not path:
        return path, False
    changed = False
    segments = path.split("/")
    previous_label = ""
    for index, segment in enumerate(segments):
        if not segment:
            previous_label = ""
            continue
        if previous_label in _CREDENTIAL_PATH_LABELS:
            segments[index] = REDACTED_PLACEHOLDER
            changed = True
            previous_label = ""
            continue
        if "=" in segment:
            # Matrix parameters: `/data;UserID=secret/`.
            redacted, segment_changed = _redact_param_string(
                segment, ";", credential_params
            )
            segments[index] = redacted
            changed = changed or segment_changed
        previous_label = "".join(credential_key_words(_safe_unquote(segment)))
    return "/".join(segments), changed


def redact_url(url: str, *, credential_params: Iterable[str] = ()) -> str:
    """Redact credentials carried in a URL, preserving a clean URL verbatim.

    Handles the three places a credential actually travels in a URL: the
    userinfo component (``https://key@host/``), ``name=value`` parameters in the
    query, fragment and path matrix segments, and a value that matches a
    well-known token format anywhere in the string. ``credential_params``
    carries the adapter-declared credential-bearing parameter names.

    A URL with nothing to redact is returned unchanged, so archived exchange
    URLs keep their exact bytes and hashes.
    """
    if not isinstance(url, str) or not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return redact_text(url)

    netloc = parts.netloc
    changed = False
    if "@" in netloc:
        userinfo, _, hostport = netloc.rpartition("@")
        if userinfo:
            netloc = f"{REDACTED_PLACEHOLDER}@{hostport}"
            changed = True

    path, path_changed = _redact_url_path(parts.path, credential_params)
    query, query_changed = _redact_param_string(parts.query, "&", credential_params)
    fragment, fragment_changed = _redact_param_string(
        parts.fragment, "&", credential_params
    )
    changed = changed or path_changed or query_changed or fragment_changed

    if not changed:
        # Byte-identical for clean URLs: redact_text is the identity on text
        # holding no known credential format.
        return redact_text(url)
    rebuilt = urlunsplit((parts.scheme, netloc, path, query, fragment))
    return redact_text(rebuilt)


# --- Headers ----------------------------------------------------------------

# Response/request headers that describe the exchange rather than authorize it.
# The plan already forbids treating any of them as publication evidence; they
# are retained because they are useful descriptive capture metadata.
SAFE_TRANSPORT_HEADERS = frozenset(
    {
        "accept-ranges",
        "age",
        "cache-control",
        "content-disposition",
        "content-encoding",
        "content-language",
        "content-length",
        "content-location",
        "content-range",
        "content-type",
        "date",
        "etag",
        "expires",
        "last-modified",
        "link",
        "location",
        "retry-after",
        "server",
        "vary",
        "x-cache",
        "x-content-type-options",
    }
)

_URL_VALUED_HEADERS = frozenset({"content-location", "link", "location"})


def _redact_header_value(
    lowered_name: str, value: Any, credential_params: Iterable[str]
) -> Any:
    if isinstance(value, (list, tuple)):
        return [
            _redact_header_value(lowered_name, item, credential_params)
            for item in value
        ]
    if not isinstance(value, str):
        return value
    if lowered_name in _URL_VALUED_HEADERS:
        return redact_url(value, credential_params=credential_params)
    return redact_text(value)


def redact_headers(
    headers: Mapping[str, Any] | Iterable[tuple[str, Any]] | None,
    *,
    credential_headers: Iterable[str] = (),
    safe_headers: Iterable[str] = (),
    drop_unlisted: bool = True,
) -> dict[str, Any]:
    """Return persistable headers: no transport secrets, allowlisted names.

    A credential-shaped header keeps its *name* — that a request carried an
    ``Authorization`` header is worth recording — and loses its value. Any
    other header not on the safe allowlist is removed entirely rather than
    persisted on the hope that it holds nothing sensitive; pass
    ``drop_unlisted=False`` to keep unknown headers with redacted values
    instead. ``credential_headers``/``safe_headers`` carry adapter-declared
    additions.
    """
    if headers is None:
        return {}
    items: Iterable[tuple[str, Any]]
    if isinstance(headers, Mapping):
        items = headers.items()
    else:
        items = headers
    allowed = set(SAFE_TRANSPORT_HEADERS)
    allowed.update(name.strip().lower() for name in safe_headers)

    result: dict[str, Any] = {}
    for name, value in items:
        if not isinstance(name, str):
            continue
        lowered = name.strip().lower()
        if is_credential_key(name, credential_headers):
            result[name] = _redacted_for_credential_key(value)
            continue
        if lowered in allowed:
            result[name] = _redact_header_value(lowered, value, credential_headers)
            continue
        if not drop_unlisted:
            result[name] = _redact_header_value(lowered, value, credential_headers)
    return result


# --- JSON payloads ----------------------------------------------------------


MAX_REDACTION_DEPTH = 128


class RedactionError(ValueError):
    """The input cannot safely be preserved by the public-trace redactor."""


class _DuplicateJsonObject(dict[str, Any]):
    """Retain every original member for inspection and lossless serialization."""

    def __init__(self, pairs: list[tuple[str, Any]]):
        super().__init__(pairs)
        self.original_pairs = tuple(pairs)

    def __eq__(self, other: object) -> bool:
        # A last-value dict comparison can conceal an earlier changed member
        # and make the caller return original bytes containing a credential.
        return (
            isinstance(other, _DuplicateJsonObject)
            and self.original_pairs == other.original_pairs
        )

    def __ne__(self, other: object) -> bool:
        return not self == other


def _redact_argv(
    value: list[Any] | tuple[Any, ...], credential_keys: Iterable[str], depth: int
) -> list[Any]:
    """Preserve argv structure while scrubbing flag/value credential pairs."""
    result: list[Any] = []
    redact_next = False
    for item in value:
        if redact_next:
            result.append(REDACTED_PLACEHOLDER)
            redact_next = False
            continue
        if isinstance(item, str) and not _URL_SCHEME_RE.match(item):
            # Query-bearing URLs in arbitrary string vectors are not atomic
            # credential flags; their public parameters survive URL redaction.
            name, separator, _ = item.partition("=")
            if is_credential_key(name, credential_keys):
                if separator:
                    # An argv element is atomic: its credential value can
                    # contain whitespace or newlines. A text token regex cannot
                    # safely decide where that value ends.
                    result.append(f"{redact_text(name)}={REDACTED_PLACEHOLDER}")
                    continue
                redact_next = item.startswith("-")
        result.append(redact_value(item, credential_keys=credential_keys, _depth=depth))
    return result


def redact_value(
    value: Any, *, credential_keys: Iterable[str] = (), _depth: int = 0
) -> Any:
    """Redact a JSON-compatible payload before it is hashed or persisted.

    Four defenses compose:

    * every string is scrubbed for known credential formats and `NAME=value`
      shapes (:func:`redact_text`);
    * every URL-shaped string is scrubbed structurally (:func:`redact_url`);
    * every value held under a credential-shaped key is replaced outright,
      recursively, which is the only defense that catches an opaque secret such
      as ``{"api_key": "plain-secret"}``;
    * registered ``argv`` vectors also scrub values adjacent to credential flags.

    Object keys themselves are scrubbed too, because a leaked env dump can
    arrive as a key. A payload with nothing to redact compares equal to its
    input, and callers rely on that to keep clean bytes untouched.
    Excessively deep payloads raise :class:`RedactionError`; callers must not
    persist their original bytes or substitute a weaker text-only scrub.
    """
    if _depth > MAX_REDACTION_DEPTH:
        raise RedactionError("JSON exceeds the public-trace redaction depth limit")
    if isinstance(value, str):
        if _URL_SCHEME_RE.match(value):
            return redact_url(value, credential_params=credential_keys)
        if value.lstrip().startswith(("{", "[", '"')):
            # Tool events often hold serialized JSON under aggregated_output.
            # Restore its structural key context before scrubbing; recursively
            # encoded documents consume the same depth budget as containers.
            try:
                return _redact_json_text(
                    value, credential_keys=credential_keys, _depth=_depth + 1
                )
            except json.JSONDecodeError:
                return _redact_mixed_text(
                    value, credential_keys=credential_keys, _depth=_depth + 1
                )
        # A serialized tool result may have a prose prefix before its JSON.
        # Inspect mixed fragments too; do not let that prefix remove key context.
        return _redact_mixed_text(
            value, credential_keys=credential_keys, _depth=_depth + 1
        )
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            return _redact_argv(value, credential_keys, _depth + 1)
        return [
            redact_value(item, credential_keys=credential_keys, _depth=_depth + 1)
            for item in value
        ]
    if isinstance(value, tuple):
        if all(isinstance(item, str) for item in value):
            return _redact_argv(value, credential_keys, _depth + 1)
        return [
            redact_value(item, credential_keys=credential_keys, _depth=_depth + 1)
            for item in value
        ]
    if isinstance(value, _DuplicateJsonObject):
        pairs: list[tuple[str, Any]] = []
        for key, item in value.original_pairs:
            member = {key: item}
            # The temporary one-member mapping occupies the SAME node depth.
            # Never redact in the decoder hook or reset nested-string budgets.
            cleaned = redact_value(
                member, credential_keys=credential_keys, _depth=_depth
            )
            pairs.extend(cleaned.items())
        return _DuplicateJsonObject(pairs)
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            clean_key = redact_text(key) if isinstance(key, str) else key
            if is_credential_key(key, credential_keys):
                redacted[clean_key] = _redacted_for_credential_key(item)
            elif key == "argv" and isinstance(item, (list, tuple)):
                redacted[clean_key] = _redact_argv(item, credential_keys, _depth + 1)
            else:
                redacted[clean_key] = redact_value(
                    item, credential_keys=credential_keys, _depth=_depth + 1
                )
        return redacted
    return value


def redact_json_value(value: Any) -> Any:
    """Legacy name for :func:`redact_value`, kept for the analyst runner."""
    return redact_value(value)


# --- Streams and response documents -----------------------------------------


def _check_json_depth(text: str, *, used_depth: int = 0) -> None:
    """Bound nesting before passing untrusted output to the JSON decoder."""
    if "[" not in text and "{" not in text:
        return
    depth = used_depth
    quoted = False
    escaped = False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            if depth > MAX_REDACTION_DEPTH:
                raise RedactionError(
                    "JSON exceeds the public-trace redaction depth limit"
                )
        elif character in "]}":
            depth -= 1


def _json_object_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            return _DuplicateJsonObject(pairs)
        result[key] = value
    return result


def _dump_redacted_json(value: Any, indent: int | None, level: int = 0) -> str:
    """Keep inspected duplicate members when another part of a document changes."""
    if isinstance(value, dict):
        pairs = (
            value.original_pairs
            if isinstance(value, _DuplicateJsonObject)
            else value.items()
        )
        items = [
            f"{json.dumps(key)}: {_dump_redacted_json(item, indent, level + 1)}"
            for key, item in pairs
        ]
        opening, closing = "{", "}"
    elif isinstance(value, list):
        items = [_dump_redacted_json(item, indent, level + 1) for item in value]
        opening, closing = "[", "]"
    else:
        return json.dumps(value)
    if not items:
        return opening + closing
    if indent is None:
        return opening + ", ".join(items) + closing
    pad = " " * indent * (level + 1)
    return (
        opening
        + "\n"
        + pad
        + (",\n" + pad).join(items)
        + "\n"
        + " " * indent * level
        + closing
    )


def _redact_json_text(
    text: str,
    *,
    indent: int | None = None,
    credential_keys: Iterable[str] = (),
    _depth: int = 0,
) -> str:
    try:
        _check_json_depth(text, used_depth=_depth)
        payload = json.loads(text, object_pairs_hook=_json_object_members)
        redacted = redact_value(payload, credential_keys=credential_keys, _depth=_depth)
        return text if redacted == payload else _dump_redacted_json(redacted, indent)
    except json.JSONDecodeError:
        raise
    except (ValueError, RecursionError) as exc:
        # The decoder's integer limit and every subsequent recursive operation
        # must fail closed. Plain-text fallback loses the structural key context
        # that protects opaque credentials inside an otherwise JSON document.
        raise RedactionError("JSON cannot be safely redacted") from exc


_SAFE_FRAGMENT_SCALAR = re.compile(
    r"(?:null|true|false|None|True|False|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"
    r"(?:[eE][+-]?[0-9]+)?)(?=$|[\s,}\];])"
)

# Fragment scanning sees prose as well as actual field syntax. Bound decoded
# names and admit ordinary identifier separators, not whole quoted paragraphs
# or markup. Real keys in parsed JSON are inspected without this lexical limit.
_MAX_FRAGMENT_NAME_LENGTH = 256
_FRAGMENT_NAME_RE = re.compile(r"[A-Za-z0-9_.$@:/+ -]+\Z")
_FRAGMENT_IDENTIFIER_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_PLAIN_PROSE_SUFFIX_RE = re.compile(
    r"[ \t]+[A-Za-z]+(?:[ \t]+[A-Za-z]+)*[.!?]?[ \t]*(?:\r?\n)?\Z"
)
_EXPRESSION_WORDS = frozenset(
    word.casefold()
    for word in keyword.kwlist
    + ["instanceof", "typeof", "void", "delete", "new", "function"]
)
_MAX_PYTHON_LITERAL_BYTES = 64 * 1024


def _fragment_value_delimited(text: str, end: int) -> bool:
    while end < len(text) and text[end].isspace():
        end += 1
    return end == len(text) or text[end] in ",;)]}" or text.startswith("</", end)


def _scalar_value_delimited(text: str, end: int) -> bool:
    if _fragment_value_delimited(text, end):
        return True
    # A diagnostic may append plain prose after its value. Keep that narrow:
    # no code punctuation, keywords, multiline expression or unbounded scan.
    if len(text) - end > 256:
        return False
    suffix = text[end:]
    return bool(_PLAIN_PROSE_SUFFIX_RE.fullmatch(suffix)) and not any(
        word.casefold() in _EXPRESSION_WORDS
        for word in suffix.strip(" .!?\r\n\t").split()
    )


def _validate_container_literal(text: str, start: int, end: int) -> None:
    literal = text[start:end]
    try:
        json.loads(literal)
        return
    except json.JSONDecodeError:
        pass
    except (ValueError, RecursionError) as exc:
        raise RedactionError("Credential container cannot be safely parsed") from exc
    # Existing Python repr logs are supported without compiling arbitrarily
    # large source input. The bracket scanner already bounded shared depth.
    if (
        len(literal) > _MAX_PYTHON_LITERAL_BYTES
        or len(literal.encode()) > _MAX_PYTHON_LITERAL_BYTES
    ):
        raise RedactionError("Credential repr exceeds the safe parser size limit")
    try:
        ast.literal_eval(literal)
    except (ValueError, SyntaxError, RecursionError) as exc:
        raise RedactionError("Credential container is not a supported literal") from exc


def _bounded_container_end(text: str, start: int, used_depth: int) -> int:
    """Find a complete removable container with one bounded, quote-aware scan."""
    stack: list[str] = []
    quote: str | None = None
    escaped = False
    for position in range(start, len(text)):
        character = text[position]
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in ('"', "'"):
            if text.startswith(character * 3, position):
                raise RedactionError("Ambiguous credential container quoting")
            quote = character
        elif character in "`#" or text.startswith(("//", "/*"), position):
            # Template literals/comments can contain unmatched brackets whose
            # apparent closer is not the end of the credential value.
            raise RedactionError("Ambiguous credential container syntax")
        elif character in "[{":
            stack.append("]" if character == "[" else "}")
            if used_depth + len(stack) > MAX_REDACTION_DEPTH:
                raise RedactionError("Credential container exceeds redaction depth")
        elif character in "]}":
            if not stack or stack.pop() != character:
                raise RedactionError("Mismatched credential container brackets")
            if not stack:
                end = position + 1
                if _fragment_value_delimited(text, end):
                    _validate_container_literal(text, start, end)
                    return end
                raise RedactionError("Ambiguous credential container continuation")
    raise RedactionError("Unterminated credential container")


def _quoted_token_end(text: str, start: int) -> int | None:
    quote = text[start]
    cursor = start + 1
    while cursor < len(text):
        if text[cursor] == "\\":
            cursor += 2
        elif text[cursor] == quote:
            return cursor + 1
        else:
            cursor += 1
    return None


def _decode_quoted_name(token: str) -> str:
    # Almost every source/page key is unescaped. Avoid a JSON decoder or Python
    # compiler invocation for each key in a large captured tool response.
    if "\\" not in token:
        return token[1:-1]
    try:
        if token[0] == '"':
            try:
                return json.loads(token)
            except json.JSONDecodeError:
                pass  # Python repr may use double quotes and Python escapes.
        return ast.literal_eval(token)
    except (ValueError, SyntaxError, RecursionError) as exc:
        raise RedactionError(
            "Malformed quoted field cannot be safely redacted"
        ) from exc


def _credential_fragment_edits(
    text: str,
    credential_keys: Iterable[str],
    scalar_ranges: Sequence[tuple[int, int]] = (),
    *,
    value_text: str | None = None,
    used_depth: int = 0,
) -> list[tuple[int, int, str]]:
    """Bound and scrub scalar values; refuse unsafe structural credentials.

    Adjacent unescaped quotes are tracked separately for each quote type, so
    prose apostrophes cannot hide a later JSON key. Candidate spans are linear
    in the input. Complete bounded values are replaced by their actual offsets,
    preserving escaped names and safely handling quoted values across lines.
    """
    edits: list[tuple[int, int, str]] = []
    previous: dict[str, int | None] = {'"': None, "'": None}
    classifications: dict[str, tuple[bool, bool]] = {}
    backslashes = 0
    scalar_index = 0
    covered_until = 0
    values = text if value_text is None else value_text
    for position, character in enumerate(text):
        if position < covered_until:
            continue
        if character == "\\":
            backslashes += 1
            continue
        escaped = backslashes % 2 != 0
        backslashes = 0
        if character not in previous or escaped:
            continue
        start = previous[character]
        previous[character] = position
        if start is None:
            continue
        after = position + 1
        while after < len(text) and text[after].isspace():
            after += 1
        if after >= len(text) or text[after] != ":":
            continue
        before = start - 1
        while before >= 0 and values[before].isspace():
            before -= 1
        if before >= 0 and values[before] == "=":
            # In captured conditional code, `name="key":...` is an
            # assignment operand followed by a ternary separator. Its quoted
            # value is not a field name, even if it contains a credential word.
            continue
        if before >= 0 and values[before] == "?":
            condition = before - 1
            while condition >= 0 and values[condition].isspace():
                condition -= 1
            alternate = after + 1
            while alternate < len(values) and values[alternate].isspace():
                alternate += 1
            identifier = _FRAGMENT_IDENTIFIER_RE.match(values, alternate)
            if identifier:
                continuation = identifier.end()
                while continuation < len(values) and values[continuation].isspace():
                    continuation += 1
                if (
                    condition >= 0
                    and values[condition] in ")]"
                    and values.startswith("?", continuation)
                ):
                    # `predicate()?"password":flag?call():other` contains a
                    # quoted branch result, not a credential field. Ordinary
                    # question prose followed by a field keeps its protection.
                    continue
        while (
            scalar_index < len(scalar_ranges)
            and scalar_ranges[scalar_index][1] <= position
        ):
            scalar_index += 1
        if scalar_index < len(scalar_ranges):
            scalar_start, scalar_end = scalar_ranges[scalar_index]
            if scalar_start < start and position < scalar_end - 1:
                # Its decoded contents were already inspected. Raw interior
                # quote syntax is not an independent fragment or key boundary.
                # The complete quoted token remains available as a multiline key.
                continue
        # A Python \U escape uses at most ten bytes per decoded character.
        # Avoid decoding an arbitrarily large pseudo-key found between quotes.
        if position - start - 1 > _MAX_FRAGMENT_NAME_LENGTH * 10:
            continue
        key = _decode_quoted_name(text[start : position + 1])
        if len(key) > _MAX_FRAGMENT_NAME_LENGTH or not _FRAGMENT_NAME_RE.fullmatch(key):
            continue
        if key in classifications:
            structural, sensitive = classifications[key]
        else:
            structural = is_credential_key(key, credential_keys)
            sensitive = structural or _text_credential_name(key)
            if len(classifications) < 512:
                classifications[key] = structural, sensitive
        if not sensitive:
            continue
        value_start = after + 1
        while value_start < len(values) and values[value_start].isspace():
            value_start += 1
        if value_start >= len(values):
            if structural:
                raise RedactionError("Credential fragment has no bounded value")
            continue
        scalar = _SAFE_FRAGMENT_SCALAR.match(values, value_start)
        if scalar:
            if structural and not _scalar_value_delimited(values, scalar.end()):
                raise RedactionError("Ambiguous credential scalar continuation")
            if structural and scalar.group() not in (
                "null",
                "true",
                "false",
                "None",
                "True",
                "False",
            ):
                edits.append(
                    (value_start, scalar.end(), json.dumps(REDACTED_PLACEHOLDER))
                )
            continue
        if values.startswith(REDACTED_PLACEHOLDER, value_start):
            end = value_start + len(REDACTED_PLACEHOLDER)
            if _scalar_value_delimited(values, end):
                continue
        if structural and values[value_start] in "[{":
            end = _bounded_container_end(values, value_start, used_depth)
            edits.append((value_start, end, json.dumps(REDACTED_PLACEHOLDER)))
            covered_until = end
            previous = {'"': None, "'": None}
            continue
        if structural:
            identifier = _FRAGMENT_IDENTIFIER_RE.match(values, value_start)
            if identifier and _fragment_value_delimited(values, identifier.end()):
                edits.append(
                    (value_start, identifier.end(), json.dumps(REDACTED_PLACEHOLDER))
                )
                continue
            if identifier:
                assignment = identifier.end()
                if (
                    values.startswith("=", assignment)
                    and assignment + 1 < len(values)
                    and values[assignment + 1] in ('"', "'")
                ):
                    end = _quoted_token_end(values, assignment + 1)
                    following = end
                    if following is not None:
                        while following < len(values) and values[following].isspace():
                            following += 1
                    if end is not None and (
                        _fragment_value_delimited(values, end)
                        or values.startswith((">", "/>"), following)
                    ):
                        # A captured markup attribute is one value. Removing
                        # only its identifier would expose the quoted contents.
                        edits.append(
                            (value_start, end, json.dumps(REDACTED_PLACEHOLDER))
                        )
                        covered_until = end
                        previous = {'"': None, "'": None}
                        continue
        if values[value_start] in ('"', "'"):
            end = _quoted_token_end(values, value_start)
            if end is not None and _scalar_value_delimited(values, end):
                value = values[value_start + 1 : end - 1]
                if value in ("", REDACTED_PLACEHOLDER):
                    continue
                edits.append((value_start, end, json.dumps(REDACTED_PLACEHOLDER)))
                continue
            # Do not fall back to text patterns that only replace an initial
            # quoted token while preserving a later operand of its expression.
            raise RedactionError("Credential string has no safe scalar boundary")
        # The substring defense still scrubs bounded strings for legacy names
        # like census_key, but cannot make source_row_keys/modal_keyboard source
        # snippets into credential-bearing containers.
        if structural:
            raise RedactionError("Credential fragment cannot be safely redacted")
    return edits


def _apply_fragment_edits(
    text: str,
    parsed: list[tuple[int, int, str]],
    fragments: list[tuple[int, int, str]],
) -> str:
    # Fragment values can contain a parsed JSON line. Their outer credential
    # boundary wins; never reinsert that line into an already-redacted value.
    bounded: list[tuple[int, int, str]] = []
    for edit in fragments:
        if bounded and edit[0] < bounded[-1][1]:
            if edit[1] <= bounded[-1][1]:
                continue
            raise RedactionError("Overlapping credential value boundaries")
        bounded.append(edit)
    selected: list[tuple[int, int, str]] = []
    outer_fragments: list[tuple[int, int, str]] = []
    index = 0
    for fragment in bounded:
        start, end, _ = fragment
        while index < len(parsed) and parsed[index][1] <= start:
            selected.append(parsed[index])
            index += 1
        if index == len(parsed) or parsed[index][0] >= end:
            outer_fragments.append(fragment)
            continue
        parsed_start, parsed_end, _ = parsed[index]
        if (
            parsed_start <= start
            and parsed_end >= end
            and (parsed_start < start or parsed_end > end)
        ):
            # A fragment inside a JSON scalar string was already redacted and
            # escaped by that scalar's parser. Inserting its raw replacement
            # into the enclosing quoted bytes would break their JSON syntax.
            continue
        if start <= parsed_start and end >= parsed_end:
            # An outer credential value wins, including equal spans: the scalar
            # parser cannot see a credential key on the preceding line.
            while index < len(parsed) and parsed[index][0] < end:
                if parsed[index][1] > end:
                    raise RedactionError("Crossing parsed and credential boundaries")
                index += 1
            outer_fragments.append(fragment)
            continue
        raise RedactionError("Crossing parsed and credential boundaries")
    selected.extend(parsed[index:])
    # Both sequences are ordered by their original offsets; merging is linear.
    from heapq import merge

    pieces: list[str] = []
    cursor = 0
    for start, end, replacement in merge(selected, outer_fragments):
        # Only unparsed gaps get plain-text patterns. Applying them to a JSONL
        # event can consume escaped newlines, quotes and its closing braces.
        pieces.extend((redact_text(text[cursor:start]), replacement))
        cursor = end
    pieces.append(redact_text(text[cursor:]))
    return "".join(pieces)


def _redact_mixed_text(
    text: str, *, credential_keys: Iterable[str] = (), _depth: int = 0
) -> str:
    """Scrub JSONL events, bounded scalar fragments and ordinary diagnostics."""
    if "\n" not in text:
        edits = _credential_fragment_edits(text, credential_keys, used_depth=_depth)
        return _apply_fragment_edits(text, [], edits)
    parsed: list[tuple[int, int, str]] = []
    scalars: list[tuple[int, int]] = []
    fragments: list[str] = []
    offset = 0
    for line in text.split("\n"):
        try:
            cleaned = _redact_json_text(
                line, credential_keys=credential_keys, _depth=_depth
            )
            container = line.lstrip().startswith(("{", "["))
            # The actual token bounds exclude indentation for containers too:
            # a credential key on an earlier line owns the whole value token.
            start = len(line) - len(line.lstrip())
            end = offset + len(line.rstrip())
            parsed.append((offset + start, end, cleaned.strip()))
            if not container:
                scalars.append((offset + start, end))
            # Keep original offsets. Scalar string lines may be multiline keys;
            # only complete containers have independent key/value structure.
            fragments.append(" " * len(line) if container else line)
        except json.JSONDecodeError:
            fragments.append(line)
        offset += len(line) + 1
    edits = _credential_fragment_edits(
        "\n".join(fragments),
        credential_keys,
        scalars,
        value_text=text,
        used_depth=_depth,
    )
    return _apply_fragment_edits(text, parsed, edits)


def redact_stream_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return line
    try:
        return _redact_json_text(line)
    except json.JSONDecodeError:
        return _redact_mixed_text(line)


def redact_stream_text(text: str) -> str:
    """Redact a line-oriented agent stream without breaking its structure.

    JSONL event lines are redacted value-wise so they stay parseable;
    non-JSON lines get plain-text redaction. Clean content passes through
    byte-identical. Unsafe JSON or credential fragments raise RedactionError.
    """
    if not text:
        return text
    # Pretty-printed whole documents are a valid stream shape too. Try the
    # complete document before losing structural context at line breaks.
    try:
        return _redact_json_text(text)
    except json.JSONDecodeError:
        return _redact_mixed_text(text)


def redact_response_text(text: str) -> str:
    """Redact an agent response document.

    A whole-document JSON response (the usual final-message shape) is
    redacted value-wise so it stays parseable even when pretty-printed;
    anything else falls back to line-oriented stream redaction.
    """
    if not text:
        return text
    try:
        return _redact_json_text(text, indent=2)
    except json.JSONDecodeError:
        return _redact_mixed_text(text)
