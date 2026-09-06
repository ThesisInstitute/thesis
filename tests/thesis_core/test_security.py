"""Credential hygiene for the shared thesis_core.security module.

`tests/test_thesis_analyst_env_hygiene.py` still owns the end-to-end legacy
proof that a recorded thesis.analyst run seals clean bytes. These tests own the
shared implementation: the moved primitives are the same objects the runner
uses, the new key-aware/URL/header redaction closes the gap the value-wise text
scrub could not see, and clean content passes through byte-identical so
evidence is never reshaped by being scrubbed.

Planted secrets are assembled by concatenation so no push-protection-shaped
literal ever exists in the repository.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from thesis_core import security

ROOT = Path(__file__).resolve().parents[2]

PLANTED = {
    "anthropic": "sk-ant-" + "planted-core-security-2026-09-04",
    "openai_legacy": "sk-" + "planted0123456789planted",
    "github_pat": "ghp_" + "Planted0123456789abc",
    "google": "AIza" + "PlantedGoogleKey0123",
    "jwt": "eyJhbGciOi" + "JIUzI1NiJ9.planted.signature",
    "aws": "AKIA" + "PLANTED0123456",
    # Opaque values that match no token format and no NAME=value shape: only
    # key-aware redaction can find these.
    "opaque_key": "census-planted-" + "opaque-2026",
    "opaque_token": "bea-planted-" + "opaque-2026",
    "opaque_password": "planted-" + "passphrase-2026",
}

REDACTED = security.REDACTED_PLACEHOLDER


def assert_no_planted(rendered: str) -> None:
    for name, value in PLANTED.items():
        assert value not in rendered, f"{name} survived redaction"


# --- The move is a move, not a copy ------------------------------------------


def test_runner_reexports_the_shared_implementation():
    """The legacy runner must scrub with these exact objects, not a copy."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import run_thesis_analyst as runner
    finally:
        if sys.path[0] == str(ROOT / "scripts"):
            sys.path.pop(0)

    for name in (
        "agent_subprocess_env",
        "redact_text",
        "redact_json_value",
        "redact_stream_line",
        "redact_stream_text",
        "redact_response_text",
        "redact_url",
        "redact_headers",
        "redact_value",
        "is_credential_key",
    ):
        assert getattr(runner, name) is getattr(security, name), name
    for name in (
        "AGENT_ENV_ALLOWLIST",
        "REDACTED_PLACEHOLDER",
        "ENV_SECRET_ASSIGNMENT_RE",
        "JSON_SECRET_FIELD_RE",
        "SECRET_TOKEN_RE",
    ):
        assert getattr(runner, name) is getattr(security, name), name


def test_agent_env_allowlist_is_unchanged_and_holds_no_credential_name():
    assert security.AGENT_ENV_ALLOWLIST == (
        "PATH",
        "HOME",
        "TERM",
        "SHELL",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "CODEX_HOME",
    )
    assert not [
        name
        for name in security.AGENT_ENV_ALLOWLIST
        if security.is_credential_key(name)
    ]


def test_agent_subprocess_env_is_an_allowlist(monkeypatch):
    monkeypatch.setenv("EVIL_PLANTED_API_KEY", PLANTED["opaque_key"])
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("CODEX_HOME", "/tmp/lane")
    env = security.agent_subprocess_env()
    assert "EVIL_PLANTED_API_KEY" not in env
    assert set(env) <= set(security.AGENT_ENV_ALLOWLIST)
    assert env["PATH"] == "/usr/bin"
    assert security.agent_subprocess_env({"CODEX_HOME": "/x"})["CODEX_HOME"] == "/x"
    assert_no_planted(json.dumps(env))


def test_module_imports_without_optional_core_dependencies():
    """Adapters and the legacy runner import this without the `core` extra."""
    probe = (
        "import sys, importlib;"
        "sys.path.insert(0, %r);"
        "importlib.import_module('thesis_core.security');"
        "loaded = sorted(m for m in sys.modules "
        "if m.split('.')[0] in {'pydantic','psycopg','fastapi','uvicorn','numpy'});"
        "print(loaded)" % str(ROOT)
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd="/",
    )
    assert completed.stdout.strip() == "[]"


# --- Name classification ------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "api_key",
        "API-key",
        "apiKey",
        "APIKey",
        "APIKEY",
        "X-Api-Key",
        "ANTHROPIC_API_KEY",
        "CENSUS_DATA_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "LEDGER_PRODUCER_SIGNING_KEY",
        "access_token",
        "accessToken",
        "refresh_token",
        "id_token",
        "token",
        "SLACK_BOT_TOKEN",
        "password",
        "Passwd",
        "passphrase",
        "secret",
        "client_secret",
        "Authorization",
        "authorization",
        "Cookie",
        "Set-Cookie",
        "cookies",
        "credentials",
        "UserID",
        "userId",
        "user_id",
        "userid",
        "key",
        "ocp-apim-subscription-key",
        "x-amz-security-token",
        "authToken",
    ],
)
def test_credential_shaped_names(name):
    assert security.is_credential_key(name), name


@pytest.mark.parametrize(
    "name",
    [
        # Usage counts, not credentials.
        "tokens",
        "input_tokens",
        "output_tokens",
        # SDMX/series identifiers.
        "dataKey",
        "seriesId",
        "dataflowIdentifier",
        "keys",
        # Public RFC 3161 witness evidence in records/.
        "tokenPath",
        "tokenSha256",
        "maxTokenLeadSeconds",
        "tokenType",
        # A non-secret provenance label existing traces already record.
        "auth",
        "authMethod",
        "author",
        # Correlation identifiers.
        "session_id",
        "account_id",
        "requestId",
        # Ordinary transport/metadata names.
        "content-type",
        "measurement_period",
        "pointEstimate",
        "",
    ],
)
def test_non_credential_names_survive(name):
    assert not security.is_credential_key(name), name


def test_adapter_declared_names_are_honored_ignoring_separators_and_case():
    assert not security.is_credential_key("registration")
    assert security.is_credential_key("registration", ["REGISTRATION"])
    assert security.is_credential_key("data_key", ["dataKey"])
    assert security.is_credential_key("DataKey", ["data-key"])


def test_credential_key_words_splits_every_naming_convention():
    assert security.credential_key_words("UserID") == ("user", "id")
    assert security.credential_key_words("X-Api-Key") == ("x", "api", "key")
    assert security.credential_key_words("ANTHROPIC_API_KEY") == (
        "anthropic",
        "api",
        "key",
    )
    assert security.credential_key_words("tokenSha256") == ("token", "sha256")


# --- Key-aware JSON redaction -------------------------------------------------


def test_opaque_credential_under_a_credential_key_is_redacted():
    """The gap the value-wise text scrub could not see."""
    payload = {"api_key": PLANTED["opaque_key"]}
    assert security.redact_text(PLANTED["opaque_key"]) == PLANTED["opaque_key"]
    redacted = security.redact_value(payload)
    assert redacted == {"api_key": REDACTED}
    assert_no_planted(json.dumps(redacted))
    # The legacy entry point shares the implementation.
    assert security.redact_json_value(payload) == redacted


def test_key_aware_redaction_reaches_nested_objects_and_arrays():
    payload = {
        "request": {
            "url": "https://apps.bea.gov/api/data",
            "params": [
                {"name": "method", "value": "GetData"},
                {"UserID": PLANTED["opaque_key"]},
            ],
            "headers": {"Authorization": "Bearer " + PLANTED["opaque_token"]},
        },
        "auth": "codex-cli-subscription",
        "usage": {"input_tokens": 7, "output_tokens": 3},
        "credentials": {"nested": {"deeper": PLANTED["opaque_password"]}},
    }
    redacted = security.redact_value(payload)
    assert redacted["request"]["params"][1] == {"UserID": REDACTED}
    assert redacted["request"]["headers"] == {"Authorization": REDACTED}
    assert redacted["credentials"] == REDACTED
    # Non-sensitive clean bytes survive intact.
    assert redacted["request"]["params"][0] == {"name": "method", "value": "GetData"}
    assert redacted["request"]["url"] == "https://apps.bea.gov/api/data"
    assert redacted["auth"] == "codex-cli-subscription"
    assert redacted["usage"] == {"input_tokens": 7, "output_tokens": 3}
    assert_no_planted(json.dumps(redacted))


def test_credential_key_hides_every_value_shape_but_keeps_the_shape_of_none():
    assert security.redact_value({"password": 12345}) == {"password": REDACTED}
    assert security.redact_value({"password": ["a", "b"]}) == {"password": REDACTED}
    assert security.redact_value({"password": None}) == {"password": None}
    assert security.redact_value({"password": False}) == {"password": False}
    assert security.redact_value({"password": ""}) == {"password": ""}


def test_clean_payloads_are_returned_equal_and_redaction_is_idempotent():
    clean = {
        "kind": "forecast_run",
        "measurement_period": "2026-Q2",
        "pointEstimate": 5.1,
        "distribution": {"points": [{"value": 1.0, "probability": 0.0}]},
        "sourceUrl": "https://www.abs.gov.au/statistics/labour-force?series=UR",
        "usage": {"input_tokens": 7},
        "tokenSha256": "a" * 64,
    }
    assert security.redact_value(clean) == clean
    dirty = {"api_key": PLANTED["opaque_key"], "note": PLANTED["anthropic"]}
    once = security.redact_value(dirty)
    assert security.redact_value(once) == once


def test_object_keys_carrying_a_leaked_secret_are_scrubbed_too():
    payload = {f"ANTHROPIC_API_KEY={PLANTED['anthropic']}": 1}
    redacted = security.redact_value(payload)
    assert list(redacted) == [f"ANTHROPIC_API_KEY={REDACTED}"]
    assert_no_planted(json.dumps(redacted))


# --- URLs ---------------------------------------------------------------------


def test_clean_url_is_returned_byte_identical():
    for url in (
        "https://apps.bea.gov/api/data?&method=GetData&TableName=T50305&Year=2026",
        "https://api.statcan.gc.ca/data/v1/vector/41690973?refPer=2026-06",
        "https://data.api.abs.gov.au/rest/data/ABS,LF,1.0.0/M3.3.aus.Q?startPeriod=2026",
        "https://example.gov/path%20with%20space/file.json#section-3",
        "not a url at all",
        "",
    ):
        assert security.redact_url(url) == url


def test_query_credentials_are_redacted_including_percent_encoded_names():
    redacted = security.redact_url(
        "https://apps.bea.gov/api/data?%55serID="
        + PLANTED["opaque_key"]
        + "&method=GetData&api_key="
        + PLANTED["opaque_token"]
    )
    assert redacted == (
        f"https://apps.bea.gov/api/data?%55serID={REDACTED}"
        f"&method=GetData&api_key={REDACTED}"
    )
    assert_no_planted(redacted)


def test_declared_credential_parameters_are_redacted():
    url = "https://example.gov/series?registration=" + PLANTED["opaque_key"]
    assert security.redact_url(url) == url
    assert security.redact_url(url, credential_params=["registration"]) == (
        f"https://example.gov/series?registration={REDACTED}"
    )


def test_userinfo_fragment_and_matrix_credentials_are_redacted():
    assert (
        security.redact_url(
            "https://" + PLANTED["opaque_key"] + ":x@example.gov/data.json"
        )
        == f"https://{REDACTED}@example.gov/data.json"
    )
    assert (
        security.redact_url(
            "https://example.gov/cb#access_token="
            + PLANTED["opaque_token"]
            + "&state=1"
        )
        == f"https://example.gov/cb#access_token={REDACTED}&state=1"
    )
    assert (
        security.redact_url(
            "https://example.gov/data;UserID=" + PLANTED["opaque_key"] + "/rows"
        )
        == f"https://example.gov/data;UserID={REDACTED}/rows"
    )
    assert (
        security.redact_url(
            "https://example.gov/v1/token/" + PLANTED["opaque_token"] + "/rows"
        )
        == f"https://example.gov/v1/token/{REDACTED}/rows"
    )


def test_known_token_formats_are_redacted_anywhere_in_a_url():
    assert (
        security.redact_url(
            "https://example.gov/v1/" + PLANTED["google"] + "/rows?series=UR"
        )
        == f"https://example.gov/v1/{REDACTED}/rows?series=UR"
    )
    assert_no_planted(security.redact_url("https://x.gov/?t=" + PLANTED["jwt"]))


def test_malformed_urls_never_raise():
    for bad in ("http://[::1", "://", "%", "https://%ZZ.example/?key=abc"):
        assert isinstance(security.redact_url(bad), str)


def test_url_shaped_strings_inside_payloads_are_redacted_structurally():
    payload = {"sourceUrl": "https://apps.bea.gov/api/?UserID=" + PLANTED["opaque_key"]}
    assert security.redact_value(payload) == {
        "sourceUrl": f"https://apps.bea.gov/api/?UserID={REDACTED}"
    }


# --- Headers ------------------------------------------------------------------


def test_transport_headers_keep_the_safe_allowlist_and_lose_the_secrets():
    redacted = security.redact_headers(
        {
            "Content-Type": "application/json; charset=utf-8",
            "Last-Modified": "Wed, 02 Sep 2026 12:00:00 GMT",
            "ETag": '"abc123"',
            "Authorization": "Bearer " + PLANTED["opaque_token"],
            "Set-Cookie": "session=" + PLANTED["opaque_token"] + "; HttpOnly",
            "X-Api-Key": PLANTED["opaque_key"],
            "X-Internal-Trace": "worker-7",
        }
    )
    assert redacted == {
        "Content-Type": "application/json; charset=utf-8",
        "Last-Modified": "Wed, 02 Sep 2026 12:00:00 GMT",
        "ETag": '"abc123"',
        "Authorization": REDACTED,
        "Set-Cookie": REDACTED,
        "X-Api-Key": REDACTED,
    }
    assert "X-Internal-Trace" not in redacted
    assert_no_planted(json.dumps(redacted))


def test_unlisted_headers_can_be_kept_with_redacted_values():
    redacted = security.redact_headers(
        {"X-Trace": "ANTHROPIC_API_KEY=" + PLANTED["anthropic"]}, drop_unlisted=False
    )
    assert redacted == {"X-Trace": f"ANTHROPIC_API_KEY={REDACTED}"}


def test_url_valued_headers_and_repeated_values_are_redacted():
    redacted = security.redact_headers(
        {
            "Location": "https://example.gov/next?api_key=" + PLANTED["opaque_key"],
            "Link": ["<https://example.gov/p2>; rel=next"],
        }
    )
    assert redacted["Location"] == f"https://example.gov/next?api_key={REDACTED}"
    assert redacted["Link"] == ["<https://example.gov/p2>; rel=next"]


def test_headers_accept_pairs_declared_names_and_none():
    assert security.redact_headers(None) == {}
    assert security.redact_headers([("Date", "now"), ("X-Serial", "1")]) == {
        "Date": "now"
    }
    assert security.redact_headers(
        {"X-Serial": "s"}, credential_headers=["x-serial"], drop_unlisted=False
    ) == {"X-Serial": REDACTED}
    assert security.redact_headers({"X-Serial": "s"}, safe_headers=["X-Serial"]) == {
        "X-Serial": "s"
    }


# --- Streams and documents ----------------------------------------------------


def test_streams_stay_parseable_and_clean_lines_are_byte_identical():
    event = {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "cat $CODEX_HOME/auth.json",
            "aggregated_output": json.dumps(
                {
                    "OPENAI_API_KEY": PLANTED["openai_legacy"],
                    "tokens": {
                        "id_token": PLANTED["jwt"],
                        "access_token": PLANTED["opaque_token"],
                        "account_id": "acct-1",
                    },
                    "credentials": {"nested": PLANTED["opaque_password"]},
                }
            ),
        },
    }
    clean = {"type": "turn.completed", "usage": {"input_tokens": 3}}
    stream = json.dumps(event) + "\n" + json.dumps(clean) + "\n"

    redacted = security.redact_stream_text(stream)
    lines = [line for line in redacted.split("\n") if line]
    parsed = [json.loads(line) for line in lines]
    inner = json.loads(parsed[0]["item"]["aggregated_output"])
    assert inner["OPENAI_API_KEY"] == REDACTED
    assert inner["tokens"]["access_token"] == REDACTED
    assert inner["tokens"]["account_id"] == "acct-1"
    assert inner["credentials"] == REDACTED
    assert lines[1] == json.dumps(clean)
    assert_no_planted(redacted)
    assert security.redact_stream_text(redacted) == redacted


def test_response_documents_keep_their_structure():
    cell = {
        "pointEstimate": 5.1,
        "reasoning": [
            {"kind": "tool", "result": f"stray AWS_ACCESS_KEY_ID={PLANTED['aws']}"}
        ],
        "debug": {"apiKey": PLANTED["opaque_key"]},
    }
    parsed = json.loads(security.redact_response_text(json.dumps(cell, indent=2)))
    assert parsed["reasoning"][0]["result"] == f"stray AWS_ACCESS_KEY_ID={REDACTED}"
    assert parsed["debug"] == {"apiKey": REDACTED}
    clean = json.dumps({"pointEstimate": 5.1}, indent=2)
    assert security.redact_response_text(clean) == clean


def test_plain_text_redaction_still_covers_the_incident_formats():
    for name, token in PLANTED.items():
        if name.startswith("opaque_"):
            continue
        cleaned = security.redact_text(f"prefix {token} suffix")
        assert cleaned == f"prefix {REDACTED} suffix", name
    dump = f"CENSUS_DATA_API_KEY={PLANTED['opaque_key']}\nPATH=/usr/bin:/bin"
    redacted = security.redact_text(dump)
    assert redacted == f"CENSUS_DATA_API_KEY={REDACTED}\nPATH=/usr/bin:/bin"
    assert security.redact_text(redacted) == redacted


def test_maximum_captured_output_redacts_with_a_bounded_runtime():
    """A subprocess timeout makes a regex regression fail without hanging CI."""
    script = """
import json
from thesis_core.execution import MAX_CAPTURED_BYTES
from thesis_core.security import redact_response_text, redact_text
for character in ('A', '7', '_'):
    payload = character * MAX_CAPTURED_BYTES
    assert redact_text(payload) == payload
    encoded = json.dumps(payload)
    assert redact_response_text(encoded) == encoded
# Repeated keyword candidates also cannot induce nested backtracking.
payload = 'KEY' * (MAX_CAPTURED_BYTES // 3)
assert redact_text(payload) == payload
print('bounded redaction complete')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    assert result.stdout.strip() == "bounded redaction complete"


@pytest.mark.parametrize(
    "redactor", [security.redact_stream_text, security.redact_response_text]
)
@pytest.mark.parametrize(
    "payload",
    [
        "[" * 1100 + '"planted-opaque"' + "]" * 1100,
        "7" * 5000,
        '{"api_key": {"nested": "planted-opaque"',
    ],
)
def test_unsafe_json_refuses_instead_of_losing_structural_redaction(redactor, payload):
    with pytest.raises(security.RedactionError):
        redactor(payload)


def test_depth_limit_ignores_json_delimiters_inside_strings():
    clean = json.dumps({"text": "Literal delimiters: " + '["' * 2000})
    assert security.redact_response_text(clean) == clean


def test_stream_redaction_preserves_log_labels_and_whole_pretty_json():
    label = "[tool] fetched public data\n[REDACTED]\n"
    assert security.redact_stream_text(label) == label
    pretty = json.dumps({"nested": {"api_key": PLANTED["opaque_key"]}}, indent=2)
    assert PLANTED["opaque_key"] not in security.redact_stream_text(pretty)
    clean = json.dumps({"pointEstimate": 5.1}, indent=2)
    assert security.redact_stream_text(clean) == clean


@pytest.mark.parametrize(
    "arguments",
    [
        ["--api-key=planted-opaque"],
        ["--token=planted-opaque"],
        ["--api-key", "planted-opaque"],
        ["--password", "planted-opaque"],
        ["--api-key=Bearer planted-opaque"],
        ["--password=prefix\nplanted-opaque"],
        ["API_KEY=prefix planted-opaque"],
    ],
)
def test_structured_argv_redacts_opaque_equals_and_adjacent_credentials(arguments):
    value = {"argv": ["forecaster", "--max-tokens", "5", *arguments]}
    cleaned = security.redact_value(value)
    assert "planted-opaque" not in json.dumps(cleaned)
    assert cleaned["argv"][:3] == value["argv"][:3]
    assert cleaned["argv"][-1].endswith(REDACTED)
    assert security.redact_value(cleaned) == cleaned


@pytest.mark.parametrize(
    "payload",
    [
        '{"branch":{"credentials":{"nested":"planted-opaque"}},"branch":{}}',
        '{"branch":{"credentials":{"nested":"planted-opaque"}},"br\\u0061nch":{}}',
    ],
)
@pytest.mark.parametrize(
    "redactor", [security.redact_stream_text, security.redact_response_text]
)
def test_duplicate_members_redact_hidden_earlier_credentials(payload, redactor):
    cleaned = redactor(payload)
    assert json.loads(cleaned, object_pairs_hook=list) == [
        ("branch", [("credentials", REDACTED)]),
        ("branch", []),
    ]
    assert "planted-opaque" not in cleaned
    assert redactor(cleaned) == cleaned
    event = json.dumps({"item": {"aggregated_output": payload}})
    cleaned_event = redactor(event)
    assert "planted-opaque" not in cleaned_event
    assert json.loads(
        json.loads(cleaned_event)["item"]["aggregated_output"], object_pairs_hook=list
    ) == json.loads(cleaned, object_pairs_hook=list)
    assert redactor(cleaned_event) == cleaned_event


def test_serialized_json_strings_share_the_nesting_budget_and_fail_closed():
    inner = json.dumps({"credentials": {"nested": PLANTED["opaque_key"]}})
    event = json.dumps({"item": {"aggregated_output": json.dumps({"result": inner})}})
    cleaned = security.redact_response_text(event)
    assert_no_planted(cleaned)
    assert security.redact_response_text(cleaned) == cleaned

    # The surrounding JSON and the JSON encoded in its string are one budget.
    wrapped = "[" * 127 + json.dumps('{"public":{"value":1}}') + "]" * 127
    with pytest.raises(security.RedactionError):
        security.redact_response_text(wrapped)
    malformed = json.dumps({"aggregated_output": '{"credentials":{"nested":"x"'})
    with pytest.raises(security.RedactionError):
        security.redact_response_text(malformed)


def test_clean_serialized_previews_and_log_labels_are_byte_identical():
    preview = json.dumps({"label": "[tool]", "public": {"value": 3}}, indent=2)
    event = json.dumps({"item": {"aggregated_output": preview}})
    assert security.redact_response_text(event) == event
    assert security.redact_stream_text(event + "\n") == event + "\n"


@pytest.mark.parametrize("name", ["census_key", "fred_key", "mytoken"])
def test_plain_text_keeps_case_insensitive_credential_substring_defense(name):
    assert security.redact_text(f'prefix "{name}": "planted-opaque" suffix') == (
        f'prefix "{name}": "{REDACTED}" suffix'
    )


@pytest.mark.parametrize("key", ["argv", "args", "unexpected"])
def test_every_string_vector_scrubs_atomic_and_adjacent_credentials(key):
    payload = {
        key: ["driver", "--api-key=Bearer planted-opaque", "--token", "opaque-2"]
    }
    cleaned = security.redact_value(payload)
    assert cleaned[key] == ["driver", f"--api-key={REDACTED}", "--token", REDACTED]


@pytest.mark.parametrize(
    "fragment",
    [
        'starting\n{ "creden\\u0074ials":\n {"nested": "planted-opaque"}\n}\nfinished',
        'starting\n{\n"credentials"\n:\n {"nested": "planted-opaque"}\n}\nfinished',
        (
            'starting\n{\n"creden\\u0074ials"\n:\n'
            ' {"nested": "planted-opaque"}\n}\nfinished'
        ),
        "{'credentials': {'nested': 'planted-opaque'}}",
        "{'creden\\u0074ials': {'nested': 'planted-opaque'}}",
        'can\'t parse {"credentials":{"nested":"planted-opaque"}}',
        'unmatched " prose {"credentials":{"nested":"planted-opaque"}}',
    ],
)
def test_mixed_fragments_scrub_escaped_and_multiline_credential_containers(fragment):
    cleaned = security.redact_stream_text(fragment)
    assert "planted-opaque" not in cleaned
    assert security.redact_stream_text(cleaned) == cleaned
    event = json.dumps({"aggregated_output": fragment})
    assert "planted-opaque" not in security.redact_response_text(event)


def test_mixed_diagnostics_keep_public_fragments_and_scrub_complete_jsonl_events():
    prefix = "[1/3] Building\n[2026-09-05 12:00:00] INFO starting\n{'a': 1}\n"
    public = '# Required JSON shape\n{\n  "slug": "example",\n  "pointEstimate": 0\n}\n'
    nested = json.dumps({"credentials": {"nested": PLANTED["opaque_key"]}}, indent=2)
    event = json.dumps({"item": {"aggregated_output": nested}})
    stream = prefix + event + "\n" + public
    cleaned = security.redact_stream_text(stream)
    assert cleaned.startswith(prefix)
    assert cleaned.endswith(public)
    assert_no_planted(cleaned)
    inner = json.loads(json.loads(cleaned.splitlines()[3])["item"]["aggregated_output"])
    assert inner["credentials"] == REDACTED


@pytest.mark.parametrize(
    "snippet",
    [
        (
            'Fetched page:\n<script>{"theme_token":null,'
            '"environment_token": "[REDACTED]"}</script>'
        ),
        '17: Drupal setting "modal_keyboard":1,',
        'source excerpt:\n    "source_row_keys": [week],',
        'rg result: "measureKey": "[REDACTED]",',
        'log: "credentials": null, "token":false, "keyboard_count":1.25e2',
        'log: "credentials": [REDACTED], "api_key": "",',
    ],
)
def test_page_settings_and_source_snippets_remain_idempotent(snippet):
    assert security.redact_stream_text(snippet) == snippet
    event = json.dumps({"item": {"aggregated_output": snippet}})
    assert security.redact_stream_text(event + "\n") == event + "\n"


@pytest.mark.parametrize(
    "fragment",
    [
        'log: "api_key": "Bearer planted-opaque", done',
        'log: "api_key": "prefix\\" planted-opaque", done',
        'log: "api_key": "prefix\nplanted-opaque", done',
        'log: "creden\\u0074ials": "planted-opaque", done',
        "log: 'api_key': 'prefix\\' planted-opaque', done",
        "log: 'creden\\u0074ials': 'planted-opaque', done",
        'log: "census_key": "prefix\\" planted-opaque", done',
        'log\n{\n"credentials"\n:\n"planted-opaque"\n}\n',
    ],
)
def test_bounded_credential_scalars_are_redacted_structurally(fragment):
    cleaned = security.redact_stream_text(fragment)
    assert "planted-opaque" not in cleaned
    assert REDACTED in cleaned
    assert security.redact_stream_text(cleaned) == cleaned
    event = json.dumps({"item": {"aggregated_output": fragment}})
    assert "planted-opaque" not in security.redact_stream_text(event)


@pytest.mark.parametrize(
    "fragment",
    [
        'log: "api_key": "prefix\\" planted-opaque',
        'log: "creden\\u0074ials": {"nested":"planted-opaque"',
        "log: 'credentials': {'nested':'planted-opaque'",
        'log: "api_key": """planted-opaque"""',
        'log: "api_key": "prefix" "planted-opaque"',
        'log: "api_key": "prefix" + "planted-opaque"',
        'log: "api_key": bare_planted_opaque + continuation',
    ],
)
def test_unbounded_credential_fragments_never_get_raw_text_fallback(fragment):
    with pytest.raises(security.RedactionError):
        security.redact_stream_text(fragment)


@pytest.mark.parametrize(
    "value",
    [
        '{"operator":"equals","name":"consent","value":"planted-opaque"}',
        "{'nested': ['planted-opaque', {'escaped': 'bracket } \\' text'}]}",
        '[{"nested":"planted-opaque"}]',
        '"planted-opaque"',
        "planted_opaque",
        'aa="planted-opaque"',
    ],
)
def test_complete_credential_fragment_values_are_replaced_wholesale(value):
    text = f'page: "cookie": {value}; public setting'
    cleaned = security.redact_stream_text(text)
    assert cleaned == f'page: "cookie": "{REDACTED}"; public setting'
    assert security.redact_stream_text(cleaned) == cleaned
    event = json.dumps({"aggregated_output": text})
    assert (
        json.loads(security.redact_stream_text(event))["aggregated_output"] == cleaned
    )


def test_container_on_separate_parsed_line_uses_the_outer_credential_boundary():
    text = 'log\n"credentials":\n{"nested":"planted-opaque"}\n'
    cleaned = security.redact_stream_text(text)
    assert cleaned == f'log\n"credentials":\n"{REDACTED}"\n'
    assert security.redact_stream_text(cleaned) == cleaned


@pytest.mark.parametrize(
    "value",
    [
        '{"nested":"planted-opaque"',
        '{"nested":"planted-opaque"]',
        '{"nested":"planted-opaque} trailing',
        '{"nested":"planted-opaque"} + continuation',
        '{"nested":"planted-opaque"}\n+ continuation',
        '{"nested":"planted-opaque"}.suffix',
        '{"nested":/* } */ "planted-opaque"}',
        '{"nested":` } planted-opaque`}',
        "{'nested':''' } planted-opaque'''}",
        "planted_opaque + continuation",
        "planted_opaque\ncontinuation",
        'aa="planted-opaque',
        'aa="prefix" + "planted-opaque"',
        'aa="prefix" "planted-opaque"',
    ],
)
def test_incomplete_or_ambiguous_credential_values_still_refuse(value):
    with pytest.raises(security.RedactionError):
        security.redact_stream_text(f'page: "cookie": {value}')


@pytest.mark.parametrize(
    "value",
    [
        "'%s' % 'planted-opaque'",
        "'prefix' if condition else 'planted-opaque'",
        "'prefix' if condition else planted_opaque",
        "'prefix' and planted_opaque",
        "'prefix' instanceof planted_opaque",
        "'prefix' // comment\n + 'planted-opaque'",
        "'prefix' /* comment */ + 'planted-opaque'",
        "'prefix' # comment\n + 'planted-opaque'",
        "1 + 'planted-opaque'",
        "1\n+ 'planted-opaque'",
        "1 if condition else planted_opaque",
        "None or planted_opaque",
        '"[REDACTED]" + "planted-opaque"',
        '[REDACTED] + "planted-opaque"',
    ],
)
def test_scalar_expression_operands_never_survive_partial_redaction(value):
    text = f'log: "credentials": {value}'
    with pytest.raises(security.RedactionError):
        security.redact_stream_text(text)
    with pytest.raises(security.RedactionError):
        security.redact_response_text(json.dumps({"aggregated_output": text}))


def test_legacy_substring_string_matching_cannot_reintroduce_partial_expressions():
    with pytest.raises(security.RedactionError):
        security.redact_stream_text('log: "census_key": "%s" % "planted-opaque"')


@pytest.mark.parametrize(
    "value",
    [
        "{match: /},planted-opaque/};",
        '{"match": /},planted-opaque/};',
        '{"nested": /* } */ "planted-opaque"}',
        '{"nested": // }\n "planted-opaque"}',
        "{'nested': # }\n 'planted-opaque'}",
        '{"nested": f"planted-opaque"}',
        '{"nested": retrieve("planted-opaque")}',
        '{"nested": `planted-opaque`}',
    ],
)
def test_credential_container_boundaries_require_a_supported_complete_literal(value):
    with pytest.raises(security.RedactionError):
        security.redact_stream_text(f'log: "credentials": {value}')


def test_large_non_json_container_does_not_invoke_the_python_compiler(monkeypatch):
    def refuse_compilation(*args, **kwargs):
        raise AssertionError("oversized Python literal was compiled")

    monkeypatch.setattr(security.ast, "literal_eval", refuse_compilation)
    text = "log: \"credentials\": {'nested': '" + "x" * 65536 + "'}"
    with pytest.raises(security.RedactionError, match="size limit"):
        security.redact_stream_text(text)


@pytest.mark.parametrize(
    "suffix", [" trailing", " trailing diagnostic.", " trailing\n"]
)
def test_plain_diagnostic_prose_can_follow_a_complete_credential_scalar(suffix):
    text = 'log: "password": "planted-opaque"' + suffix
    assert security.redact_stream_text(text) == 'log: "password": "[REDACTED]"' + suffix


def test_public_cookie_presentation_text_can_be_truncated():
    text = (
        'page: {"message_placeholder_cookieconsent_optout_marketing": '
        '"Public consent instructions\ncontinued without closing quote'
    )
    assert security.redact_stream_text(text) == text


@pytest.mark.parametrize("assignment", ["=", "= "])
def test_quoted_assignment_operands_are_not_ternary_field_names(assignment):
    text = f'source: check(obj,"field")?left{assignment}"key":right="public":tail;'
    assert security.redact_stream_text(text) == text
    event = json.dumps({"aggregated_output": text})
    assert security.redact_stream_text(event) == event
    # A real field later in the same source still gets structural protection.
    with_field = text + ' config={"credentials":{"nested":"planted-opaque"}};'
    cleaned = security.redact_stream_text(with_field)
    assert cleaned.startswith(text)
    assert "planted-opaque" not in cleaned


def test_assignment_before_a_parsed_event_does_not_hide_a_later_field():
    text = 'log =\n{"public":1}\n"credentials": {"nested":"planted-opaque"}'
    cleaned = security.redact_stream_text(text)
    assert "planted-opaque" not in cleaned
    assert cleaned.startswith('log =\n{"public":1}\n')


def test_quoted_nested_conditional_operand_is_not_a_password_field():
    text = 'source: obj.check("public")?"password":flag?call(arg):other;'
    assert security.redact_stream_text(text) == text
    event = json.dumps({"aggregated_output": text})
    assert security.redact_stream_text(event) == event
    with_field = text + ' config={"password":{"nested":"planted-opaque"}};'
    cleaned = security.redact_stream_text(with_field)
    assert cleaned.startswith(text)
    assert "planted-opaque" not in cleaned


def test_question_prose_does_not_hide_a_following_credential_field():
    text = 'Found it? "password": {"nested":"planted-opaque"}'
    assert "planted-opaque" not in security.redact_stream_text(text)


def test_bounded_container_fragments_share_the_decoded_document_depth_budget():
    payload = 'log: "credentials": ' + "[" * 3 + '"planted-opaque"' + "]" * 3
    with pytest.raises(security.RedactionError):
        security.redact_value(payload, _depth=security.MAX_REDACTION_DEPTH - 2)


def test_large_nested_credential_container_is_scanned_once():
    script = """
from thesis_core.security import redact_stream_text
from thesis_core.execution import MAX_CAPTURED_BYTES
entry = '{"credentials":{"nested":"planted-opaque"}}'
entries = ','.join([entry] * (MAX_CAPTURED_BYTES // (len(entry) + 1) - 2))
payload = 'log: "credentials": [' + entries + ']'
assert redact_stream_text(payload) == 'log: "credentials": "[REDACTED]"'
print('bounded container scan complete')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    assert result.stdout.strip() == "bounded container scan complete"


def test_outer_credential_scalar_wins_over_parsed_lines_inside_it():
    fragment = (
        'log\n"credentials": "start\n'
        '{"public":"planted-opaque","api_key":"other-opaque"}\n'
        'end"\n'
    )
    # The unescaped interior quotes make this an ambiguous multiline value.
    # Refusal is safe; if it can be bounded, neither inner value may survive.
    try:
        cleaned = security.redact_stream_text(fragment)
    except security.RedactionError:
        return
    assert "planted-opaque" not in cleaned
    assert "other-opaque" not in cleaned


def test_pathological_plain_quoted_names_do_not_invoke_a_parser_per_token():
    script = """
from unittest.mock import patch
from thesis_core.security import _credential_fragment_edits
from thesis_core.execution import MAX_CAPTURED_BYTES
payload = "'':" * (MAX_CAPTURED_BYTES // 3)
with patch('thesis_core.security.ast.literal_eval', side_effect=AssertionError), \\
     patch('thesis_core.security.json.loads', side_effect=AssertionError):
    assert _credential_fragment_edits(payload, ()) == []
print('bounded quoted-name scan complete')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    assert result.stdout.strip() == "bounded quoted-name scan complete"


@pytest.mark.parametrize(
    "payload",
    [
        '{"id":"first","id":"second"}',
        '{"id":"first","\\u0069d":"second"}',
        '{"item":{"id":"first","id":"second"},"public":1}',
        '{"item":{"result":"first"},"item":{"result":"second"}}',
    ],
)
def test_clean_duplicate_transport_members_remain_byte_identical(payload):
    assert security.redact_stream_text(payload) == payload
    assert security.redact_stream_text("[tool] starting\n" + payload + "\n") == (
        "[tool] starting\n" + payload + "\n"
    )
    serialized = json.dumps({"aggregated_output": payload})
    assert security.redact_response_text(serialized) == serialized


def test_duplicate_members_share_the_original_depth_budget():
    nested = "[" * 126 + json.dumps('{"public":{"value":1}}') + "]" * 126
    payload = '{"item":' + nested + ',"item":{}}'
    with pytest.raises(security.RedactionError):
        security.redact_stream_text(payload)


def test_changed_sibling_preserves_every_clean_duplicate_member_when_serialized():
    payload = '{"trace":{"id":"first","id":"second"},"api_key":"planted-opaque"}'
    cleaned = security.redact_response_text(payload)
    assert "planted-opaque" not in cleaned
    assert '"id": "first"' in cleaned
    assert '"id": "second"' in cleaned
    assert cleaned.count('"id"') == 2
    assert security.redact_response_text(cleaned) == cleaned
    # An outer credential boundary removes the complete duplicate node safely.
    hidden = '{"credentials":{"id":"planted-opaque","id":"other-opaque"}}'
    assert json.loads(security.redact_response_text(hidden)) == {
        "credentials": REDACTED
    }


def test_duplicate_action_members_redact_queries_without_losing_public_ids():
    query = "https://agency.example/data?api_key=planted-opaque&series=unemployment"
    payload = (
        '{"id":"first","action":{"queries":[' + json.dumps(query) + "]},"
        '"id":"second","action":{"queries":["public data"]}}'
    )
    cleaned = security.redact_response_text(payload)
    assert "planted-opaque" not in cleaned
    assert json.loads(cleaned, object_pairs_hook=list) == [
        ("id", "first"),
        ("action", [("queries", [query.replace("planted-opaque", REDACTED)])]),
        ("id", "second"),
        ("action", [("queries", ["public data"])]),
    ]
    assert security.redact_response_text(cleaned) == cleaned


@pytest.mark.parametrize(
    "name",
    [
        "historyFloorAuthorization",
        "cookieContentBlocker",
        "cookiebot",
        "Cookiebot",
        "tough-cookie",
        "message_placeholder_cookieconsent_optout_marketing",
    ],
)
def test_exact_public_settings_names_still_inspect_children_and_declarations(name):
    public = {name: {"enabled": True, "message": "Consent settings"}}
    text = json.dumps(public)
    assert not security.is_credential_key(name)
    assert security.redact_stream_text(text) == text
    assert security.redact_stream_text("page: " + text) == "page: " + text
    assert security.redact_value({name: {"api_key": "planted-opaque"}}) == {
        name: {"api_key": REDACTED}
    }
    assert security.is_credential_key(name, [name])
    assert security.redact_value(public, credential_keys=[name]) == {name: REDACTED}


@pytest.mark.parametrize(
    "name",
    ["cookie", "authorization", "customCookiebot", "historyFloorAuthorizationToken"],
)
def test_public_settings_exceptions_do_not_exempt_generic_or_extended_names(name):
    assert security.is_credential_key(name)
    assert security.redact_value({name: {"nested": "planted-opaque"}}) == {
        name: REDACTED
    }


@pytest.mark.parametrize(
    "pseudo_key",
    [
        "public source authorization " + "x" * 2420,
        "public source authorization\n<p>" + "x" * 429850 + "</p>",
        "source says authorization <example>",
    ],
)
def test_quoted_prose_spans_are_not_fragment_field_names(pseudo_key):
    text = f'page excerpt: "{pseudo_key}": public_expression'
    assert security.redact_stream_text(text) == text


@pytest.mark.parametrize(
    "name", ["API key", "provider.api_key", "x-api-key", "credentials"]
)
def test_bounded_name_shaped_fragments_support_spaces_separators_and_escapes(name):
    escaped = '"' + "".join(f"\\u{ord(character):04x}" for character in name) + '"'
    for quoted_name in (json.dumps(name), escaped):
        scalar = f'log: {quoted_name}: "planted-opaque"'
        assert "planted-opaque" not in security.redact_stream_text(scalar)
        assert "planted-opaque" not in security.redact_stream_text(
            f'log: {quoted_name}: {{"nested":"planted-opaque"}}'
        )


def test_actual_json_keys_are_inspected_without_the_fragment_name_limit():
    name = "public source " * 300 + " authorization <example>"
    cleaned = security.redact_response_text(
        json.dumps({name: {"nested": "planted-opaque"}})
    )
    assert "planted-opaque" not in cleaned
    assert json.loads(cleaned)[name] == REDACTED


def test_mixed_stream_does_not_reapply_text_patterns_to_complete_json_events():
    output = f"ANTHROPIC_API_KEY={PLANTED['anthropic']}\ntrailing diagnostic\n"
    event = json.dumps({"monkey": "public", "aggregated_output": output})
    stream = "[tool] starting\n" + event + "\nfinished\n"
    cleaned = security.redact_stream_text(stream)
    parsed = json.loads(cleaned.splitlines()[1])
    assert parsed["monkey"] == "public"
    assert parsed["aggregated_output"] == (
        f"ANTHROPIC_API_KEY={REDACTED}\ntrailing diagnostic\n"
    )
    assert security.redact_stream_text(cleaned) == cleaned


@pytest.mark.parametrize("name", ["api_key", "password", "credentials", "access_token"])
@pytest.mark.parametrize("value", ["123456", "0", "-1.25e2"])
def test_numeric_credentials_are_redacted_in_fragment_scalars(name, value):
    text = f'log: "{name}": {value}, "modal_keyboard": 1'
    assert security.redact_stream_text(text) == (
        f'log: "{name}": "{REDACTED}", "modal_keyboard": 1'
    )


def test_inner_fragment_redaction_yields_to_the_enclosing_json_scalar():
    scalar = json.dumps("tool said 'password': 'planted-opaque' trailing")
    cleaned = security.redact_stream_text("log\n" + scalar + "\n")
    parsed = json.loads(cleaned.splitlines()[1])
    assert "planted-opaque" not in parsed
    assert parsed == f"tool said 'password': \"{REDACTED}\" trailing"
    assert security.redact_stream_text(cleaned) == cleaned


def test_already_redacted_json_scalar_does_not_receive_plain_text_patterns():
    scalar = json.dumps(f"API_KEY={REDACTED}\ntrailing diagnostic")
    stream = "log\n" + scalar + "\n"
    assert security.redact_stream_text(stream) == stream
    assert json.loads(security.redact_stream_text(stream).splitlines()[1]) == (
        f"API_KEY={REDACTED}\ntrailing diagnostic"
    )


@pytest.mark.parametrize("padding", ["", "   "])
def test_outer_credential_fragment_wins_over_equal_scalar_bounds(padding):
    scalar = json.dumps("prefix " + PLANTED["github_pat"] + " planted-opaque")
    stream = f'log\n"credentials":\n{padding}{scalar}{padding}\n'
    cleaned = security.redact_stream_text(stream)
    assert "planted-opaque" not in cleaned
    assert PLANTED["github_pat"] not in cleaned
    assert json.loads(cleaned.splitlines()[2]) == REDACTED
    assert security.redact_stream_text(cleaned) == cleaned


def test_partially_crossing_redaction_boundaries_refuse():
    with pytest.raises(security.RedactionError, match="Crossing"):
        security._apply_fragment_edits(
            "0123456789", [(2, 7, "parsed")], [(5, 9, "fragment")]
        )
    with pytest.raises(security.RedactionError, match="Crossing"):
        security._apply_fragment_edits(
            "0123456789", [(4, 8, "parsed")], [(2, 6, "fragment")]
        )
