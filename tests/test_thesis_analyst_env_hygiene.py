"""Credential hygiene for recorded thesis.analyst agent runs.

Incident 2026-07-21: during an aging-wave-2 batch, the codex agent ran
`env | rg -i 'CENSUS|API|KEY'` while hunting for a Census API key, and 18
credential env vars inherited from the interactive shell landed verbatim in
recorded trace files (draft_codex_events.jsonl and friends); GitHub push
protection was the only backstop. These tests pin both defenses in
scripts/run_thesis_analyst.py: the minimal allowlisted subprocess
environment, and the credential redaction applied to every captured agent
stream (draft, pre-submit review, and final) before records are written.

Planted secrets below are assembled by concatenation so no push-protection-
shaped literal ever exists in the repository, in this file or in records.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_thesis_analyst.py"
sys.path.insert(0, str(ROOT / "scripts"))
import run_thesis_analyst as analyst_runner  # noqa: E402
from verify_custody import verify_run  # noqa: E402

from tests.test_thesis_analyst_runner import (  # noqa: E402
    review_test_cell,
    write_fake_gemini,
)

PLANTED = {
    "anthropic": "sk-ant-" + "planted-incident-2026-07-21",
    "openai_legacy": "sk-" + "planted0123456789planted",
    "openai_project": "sk-proj-" + "planted-0123456789",
    "openrouter": "sk-or-" + "v1-planted-0123",
    "github_pat": "ghp_" + "Planted0123456789abc",
    "github_fine_grained": "github_pat_" + "planted_0123456789",
    "slack": "xoxb-" + "1111-2222-planted",
    "google": "AIza" + "PlantedGoogleKey0123",
    "jwt": "eyJhbGciOi" + "JIUzI1NiJ9.planted.signature",
    "aws": "AKIA" + "PLANTED0123456",
    # Caught by the NAME=value rule, not by any token-format rule.
    "census": "census-planted-" + "env-value-2026",
}

CREDENTIAL_NAME_RE = re.compile(r"KEY|TOKEN|SECRET|PASSWORD")


def assert_no_planted_content(root: Path, extra_values: list[str]) -> None:
    """No planted secret survives anywhere in the written record."""
    values = [*PLANTED.values(), *extra_values]
    files = [path for path in sorted(root.rglob("*")) if path.is_file()]
    assert files, f"no record files written under {root}"
    for path in files:
        data = path.read_text()
        for value in values:
            assert value not in data, f"{path.name} leaked {value!r}"


def test_redact_text_covers_incident_token_formats():
    for name, token in PLANTED.items():
        if name == "census":
            continue
        redacted = analyst_runner.redact_text(f"prefix {token} suffix")
        assert redacted == "prefix [REDACTED] suffix", name


def test_redact_text_redacts_env_dump_lines_and_stays_idempotent():
    env_dump = "\n".join(
        [
            f"ANTHROPIC_API_KEY={PLANTED['anthropic']}",
            f"CENSUS_DATA_API_KEY={PLANTED['census']}",
            f"LEDGER_PRODUCER_SIGNING_KEY={PLANTED['jwt']}",
            f"SLACK_BOT_TOKEN={PLANTED['slack']}",
            "PATH=/usr/bin:/bin",
            "The Census API key policy page mentions no key at all.",
        ]
    )
    redacted = analyst_runner.redact_text(env_dump)
    assert "ANTHROPIC_API_KEY=[REDACTED]" in redacted
    assert "CENSUS_DATA_API_KEY=[REDACTED]" in redacted
    assert "LEDGER_PRODUCER_SIGNING_KEY=[REDACTED]" in redacted
    assert "SLACK_BOT_TOKEN=[REDACTED]" in redacted
    # Non-credential names and prose survive untouched.
    assert "PATH=/usr/bin:/bin" in redacted
    assert "mentions no key at all." in redacted
    for value in PLANTED.values():
        assert value not in redacted
    assert analyst_runner.redact_text(redacted) == redacted


def test_redact_text_redacts_credential_json_fields():
    auth_dump = (
        '{"OPENAI_API_KEY": "'
        + PLANTED["openai_legacy"]
        + '", "tokens": 5, "api_key":"'
        + PLANTED["openai_project"]
        + '"}'
    )
    redacted = analyst_runner.redact_text(auth_dump)
    assert '"OPENAI_API_KEY": "[REDACTED]"' in redacted
    assert '"api_key": "[REDACTED]"' in redacted
    assert '"tokens": 5' in redacted
    assert PLANTED["openai_legacy"] not in redacted
    assert PLANTED["openai_project"] not in redacted


def test_redact_stream_text_keeps_event_lines_parseable():
    event = {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "env | rg -i 'CENSUS|API|KEY'",
            "aggregated_output": (
                f"ANTHROPIC_API_KEY={PLANTED['anthropic']}\n"
                f"CENSUS_DATA_API_KEY={PLANTED['census']}\n"
            ),
        },
    }
    clean = {"type": "turn.completed", "usage": {"input_tokens": 3}}
    stream = json.dumps(event) + "\n" + json.dumps(clean) + "\n"

    redacted = analyst_runner.redact_stream_text(stream)
    lines = [line for line in redacted.split("\n") if line]
    parsed = [json.loads(line) for line in lines]

    output = parsed[0]["item"]["aggregated_output"]
    assert "ANTHROPIC_API_KEY=[REDACTED]" in output
    assert "CENSUS_DATA_API_KEY=[REDACTED]" in output
    for value in PLANTED.values():
        assert value not in redacted
    # A clean line passes through byte-identical.
    assert lines[1] == json.dumps(clean)


def test_redact_response_text_preserves_json_document_structure():
    cell = {
        "reasoning": [
            {
                "kind": "tool",
                "result": (
                    "Fetched rate 5.1; stray "
                    f"ANTHROPIC_API_KEY={PLANTED['anthropic']}"
                ),
            }
        ]
    }
    redacted = analyst_runner.redact_response_text(json.dumps(cell, indent=2))
    parsed = json.loads(redacted)
    assert parsed["reasoning"][0]["result"] == (
        "Fetched rate 5.1; stray ANTHROPIC_API_KEY=[REDACTED]"
    )
    clean_document = json.dumps({"pointEstimate": 5.1}, indent=2)
    assert analyst_runner.redact_response_text(clean_document) == clean_document


def test_agent_subprocess_env_is_an_allowlist(monkeypatch):
    monkeypatch.setenv("EVIL_PLANTED_API_KEY", "super-secret")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("CODEX_HOME", "/tmp/lane")
    env = analyst_runner.agent_subprocess_env()
    assert "EVIL_PLANTED_API_KEY" not in env
    assert env["PATH"] == "/usr/bin"
    assert env["CODEX_HOME"] == "/tmp/lane"
    assert set(env) <= set(analyst_runner.AGENT_ENV_ALLOWLIST)
    overridden = analyst_runner.agent_subprocess_env({"CODEX_HOME": "/tmp/x"})
    assert overridden["CODEX_HOME"] == "/tmp/x"


def planted_cell(
    *,
    point: float,
    ci_low: float,
    ci_high: float,
    review_disposition: str | None = None,
) -> dict:
    cell = review_test_cell(
        point=point,
        ci_low=ci_low,
        ci_high=ci_high,
        review_disposition=review_disposition,
    )
    cell["reasoning"][2]["result"] += (
        f" Stray shell noise: ANTHROPIC_API_KEY={PLANTED['anthropic']}"
        f" and bearer {PLANTED['jwt']}."
    )
    return cell


def test_codex_stages_get_minimal_env_and_redacted_records(tmp_path):
    """Draft, review, and final codex streams all seal redacted, and the
    codex child process only ever sees the allowlisted environment."""
    out_dir = tmp_path / "codex-run"
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}\n")
    fake_codex = tmp_path / "fake_codex.py"
    parent_secret = "parent-only-planted-" + "value-777"

    draft = planted_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    final = planted_cell(
        point=5.2,
        ci_low=4.6,
        ci_high=5.9,
        review_disposition=(
            "Review disposition: accepted the interval-source clarification "
            "and widened the upper tail by 0.1."
        ),
    )
    review = {
        "summary": (
            "Solid draft. Stray shell noise: "
            f"ANTHROPIC_API_KEY={PLANTED['anthropic']}"
        ),
        "requiredFixes": [],
        "optionalSuggestions": [],
    }
    env_dump_output = "\n".join(
        [
            f"ANTHROPIC_API_KEY={PLANTED['anthropic']}",
            f"CENSUS_DATA_API_KEY={PLANTED['census']}",
            f"GOOGLE_API_KEY={PLANTED['google']}",
            f"SLACK_BOT_TOKEN={PLANTED['slack']}",
            f"AWS_ACCESS_KEY_ID={PLANTED['aws']}",
        ]
    )

    fake_codex.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, os, pathlib, sys",
                "args = sys.argv[1:]",
                "prompt = args[-1]",
                "last_message = pathlib.Path(args[args.index('-o') + 1])",
                "pathlib.Path(__file__).with_name('env_dump.json').write_text(",
                "    json.dumps(dict(os.environ))",
                ")",
                f"draft = {json.dumps(json.dumps(draft))}",
                f"final = {json.dumps(json.dumps(final))}",
                f"review = {json.dumps(json.dumps(review))}",
                "if 'Thesis pre-submit forecast review' in prompt:",
                "    text = review",
                "elif 'Pre-submit review loop' in prompt:",
                "    text = final",
                "else:",
                "    text = draft",
                "last_message.write_text(text)",
                f"env_dump_output = {json.dumps(env_dump_output)}",
                "print(json.dumps({",
                "  'type': 'item.completed',",
                "  'item': {",
                "    'type': 'command_execution',",
                "    'command': \"env | rg -i 'CENSUS|API|KEY'\",",
                "    'aggregated_output': env_dump_output,",
                "  },",
                "}))",
                "print(json.dumps({",
                "  'type': 'item.completed',",
                "  'item': {'type': 'agent_message', 'text': text},",
                "}))",
                "print(json.dumps({",
                "  'type': 'turn.completed',",
                "  'usage': {'input_tokens': 7, 'output_tokens': 3},",
                "}))",
                "print(",
                f"    'warning: OPENROUTER_API_KEY=' + {json.dumps(PLANTED['jwt'])},",
                "    file=sys.stderr,",
                ")",
            ]
        )
    )
    fake_codex.chmod(0o755)

    env = {
        **os.environ,
        "THESIS_CODEX_BIN": str(fake_codex),
        "CODEX_HOME": str(codex_home),
        "PLANTED_PARENT_ONLY_API_KEY": parent_secret,
    }
    subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.env_hygiene_rate",
            "--period",
            "2030-01",
            "--codex-model",
            "gpt-5.5",
            "--pre-submit-review-codex-model",
            "gpt-5.5",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    # 1. The codex child only ever saw the allowlisted environment.
    child_env = json.loads((tmp_path / "env_dump.json").read_text())
    assert "PLANTED_PARENT_ONLY_API_KEY" not in child_env
    assert "THESIS_CODEX_BIN" not in child_env
    assert "PATH" in child_env
    assert "HOME" in child_env
    assert Path(child_env["CODEX_HOME"]).name.startswith("thesis-codex-home-")
    credential_named = [name for name in child_env if CREDENTIAL_NAME_RE.search(name)]
    assert credential_named == []

    # 2. No planted secret survives anywhere in the record.
    assert_no_planted_content(out_dir, [parent_secret])

    # 3. Draft, review, and final streams are all redacted and still
    #    structurally valid JSONL.
    for prefix in ("draft_", "pre_submit_review_", ""):
        stdout_jsonl = (out_dir / f"{prefix}codex_stdout.jsonl").read_text()
        assert "ANTHROPIC_API_KEY=[REDACTED]" in stdout_jsonl
        assert "CENSUS_DATA_API_KEY=[REDACTED]" in stdout_jsonl
        stderr_log = (out_dir / f"{prefix}codex_stderr.log").read_text()
        assert "OPENROUTER_API_KEY=[REDACTED]" in stderr_log
        events_text = (out_dir / f"{prefix}codex_events.jsonl").read_text()
        assert "ANTHROPIC_API_KEY=[REDACTED]" in events_text
        for line in filter(None, events_text.split("\n")):
            json.loads(line)

    # 4. The redacted final cell still parses, validates, and seals green.
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is True
    assert manifest["preSubmitReview"]["status"] == "completed"
    assert "ANTHROPIC_API_KEY=[REDACTED]" in (manifest["preSubmitReview"]["summary"])
    cells = json.loads((out_dir / "cells.with_activity.json").read_text())
    assert cells[0]["pointEstimate"] == 5.2
    assert "ANTHROPIC_API_KEY=[REDACTED]" in json.dumps(cells)
    verification = verify_run(out_dir)
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is True


def test_gemini_stage_gets_only_its_key_and_seals_redacted(tmp_path: Path) -> None:
    """Gemini gets its one backend-only key and every echoed copy is redacted."""
    out_dir = tmp_path / "gemini-run"
    fake_gemini = tmp_path / "gemini"
    probe_path = tmp_path / "gemini_probe.json"
    parent_secret = "parent-only-planted-" + "value-999"
    parent_google_secret = "parent-google-only-" + "value-999"
    cell = planted_cell(point=5.1, ci_low=4.7, ci_high=5.8)
    cell["reasoning"][2]["result"] += (
        f" Stray Gemini output: GEMINI_API_KEY={PLANTED['google']} and the "
        "forecast continues."
    )
    write_fake_gemini(
        fake_gemini,
        cell,
        extra_lines=[
            f"probe_path = pathlib.Path({json.dumps(str(probe_path))})",
            "gemini_home = pathlib.Path(os.environ['HOME'])",
            "probe_path.write_text(json.dumps({",
            "  'envNames': sorted(os.environ),",
            "  'geminiKeyPresent': bool(os.environ.get('GEMINI_API_KEY')),",
            "  'googleKeyPresent': 'GOOGLE_API_KEY' in os.environ,",
            "  'home': str(gemini_home),",
            "  'cwd': str(pathlib.Path.cwd()),",
            "  'settings': json.loads(",
            "    (gemini_home / '.gemini' / 'settings.json').read_text()",
            "  ),",
            "}))",
            "tool_output = 'GEMINI_API_KEY=' + os.environ['GEMINI_API_KEY']",
            "print(",
            "  'GEMINI_API_KEY=' + os.environ['GEMINI_API_KEY'],",
            "  file=sys.stderr,",
            ")",
        ],
    )

    env = {
        **os.environ,
        "THESIS_GEMINI_BIN": str(fake_gemini),
        "GEMINI_API_KEY": PLANTED["google"],
        "GOOGLE_API_KEY": parent_google_secret,
        "PLANTED_PARENT_ONLY_API_KEY": parent_secret,
    }
    subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.env_hygiene_rate",
            "--period",
            "2030-01",
            "--gemini-model",
            "gemini-3.7-flash",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    probe = json.loads(probe_path.read_text())
    child_names = set(probe["envNames"])
    allowed_names = {
        *analyst_runner.AGENT_ENV_ALLOWLIST,
        "GEMINI_API_KEY",
    }
    assert "GEMINI_API_KEY" not in analyst_runner.AGENT_ENV_ALLOWLIST
    # macOS injects this locale/encoding hint after execve; command.json pins
    # the exact pre-exec allowlist below.
    assert child_names <= allowed_names | {"__CF_USER_TEXT_ENCODING"}
    assert probe["geminiKeyPresent"] is True
    assert probe["googleKeyPresent"] is False
    assert "GOOGLE_API_KEY" not in child_names
    assert "THESIS_GEMINI_BIN" not in child_names
    assert "PLANTED_PARENT_ONLY_API_KEY" not in child_names
    assert [name for name in child_names if CREDENTIAL_NAME_RE.search(name)] == [
        "GEMINI_API_KEY"
    ]
    assert Path(probe["home"]).name.startswith("thesis-gemini-home-")
    assert Path(probe["cwd"]).name.startswith("thesis-gemini-work-")
    assert Path(probe["cwd"]) != ROOT
    assert probe["settings"] == {
        "security": {"auth": {"selectedType": "gemini-api-key"}}
    }

    assert_no_planted_content(
        out_dir,
        [parent_secret, parent_google_secret],
    )
    stdout_jsonl = (out_dir / "gemini_stdout.jsonl").read_text()
    events_jsonl = (out_dir / "gemini_events.jsonl").read_text()
    last_message = (out_dir / "gemini_last_message.txt").read_text()
    stderr_text = (out_dir / "stderr.txt").read_text()
    assert "GEMINI_API_KEY=[REDACTED]" in stdout_jsonl
    assert "GEMINI_API_KEY=[REDACTED]" in events_jsonl
    assert "GEMINI_API_KEY=[REDACTED]" in last_message
    assert "GEMINI_API_KEY=[REDACTED]" in stderr_text
    for stream in (stdout_jsonl, events_jsonl):
        for line in filter(None, stream.splitlines()):
            json.loads(line)

    manifest = json.loads((out_dir / "manifest.json").read_text())
    [cell_with_activity] = json.loads(
        (out_dir / "cells.with_activity.json").read_text()
    )
    command = json.loads((out_dir / "command.json").read_text())
    assert manifest["ok"] is True
    assert set(command["envVarNames"]) <= allowed_names
    assert command["envVarNames"].count("GEMINI_API_KEY") == 1
    assert "GEMINI_API_KEY=[REDACTED]" in json.dumps(cell_with_activity)
    verification = verify_run(out_dir)
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is True


def test_command_run_replays_incident_env_dump_redacted(tmp_path):
    """The incident shape: a --command agent prints an env dump. The child
    gets the allowlisted env, and the failed trace is recorded redacted."""
    out_dir = tmp_path / "incident-run"
    dumper = tmp_path / "env_dumper.py"
    parent_secret = "parent-only-planted-" + "value-888"

    dumper.write_text(
        "\n".join(
            [
                "import json, os, pathlib, sys",
                "_prompt = sys.stdin.read()",
                "here = pathlib.Path(__file__)",
                "here.with_name('cmd_env_dump.json').write_text(",
                "    json.dumps(dict(os.environ))",
                ")",
                f"print('ANTHROPIC_API_KEY=' + {json.dumps(PLANTED['anthropic'])})",
                f"print('CENSUS_DATA_API_KEY=' + {json.dumps(PLANTED['census'])})",
                f"print('aws id ' + {json.dumps(PLANTED['aws'])})",
                "print(",
                f"    'GEMINI_API_KEY=' + {json.dumps(PLANTED['google'])},",
                "    file=sys.stderr,",
                ")",
            ]
        )
    )

    env = {**os.environ, "PLANTED_PARENT_ONLY_API_KEY": parent_secret}
    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--series",
            "test.env_hygiene",
            "--period",
            "2030-01",
            "--command",
            (
                f"{shlex.quote(sys.executable)} {shlex.quote(str(dumper))} "
                f"--token {PLANTED['github_pat']}"
            ),
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    # An env dump is not a forecast: the run fails but the trace is kept.
    assert result.returncode == 1
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["ok"] is False
    assert manifest["error"]["phase"] == "parse"

    child_env = json.loads((tmp_path / "cmd_env_dump.json").read_text())
    assert "PLANTED_PARENT_ONLY_API_KEY" not in child_env
    assert "PATH" in child_env
    credential_named = [name for name in child_env if CREDENTIAL_NAME_RE.search(name)]
    assert credential_named == []

    assert_no_planted_content(out_dir, [parent_secret])
    stdout_text = (out_dir / "stdout.txt").read_text()
    assert "ANTHROPIC_API_KEY=[REDACTED]" in stdout_text
    assert "CENSUS_DATA_API_KEY=[REDACTED]" in stdout_text
    assert "aws id [REDACTED]" in stdout_text
    assert "GEMINI_API_KEY=[REDACTED]" in (out_dir / "stderr.txt").read_text()
    assert "ANTHROPIC_API_KEY=[REDACTED]" in (
        (out_dir / "raw_response.txt").read_text()
    )
    # Secrets passed on the command line never reach command.json either.
    command = json.loads((out_dir / "command.json").read_text())
    assert "[REDACTED]" in command["argv"]
    verification = verify_run(out_dir)
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is False
