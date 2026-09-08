"""Actual process boundaries for the exploratory paired runner (no model calls)."""

import json
import sys
import time

import pytest

from thesis_core.conditional_runner import capture_pair


@pytest.mark.parametrize(
    "model",
    [
        None,
        123,
        "",
        "model name",
        "model+preview",
        "model@provider",
        "model#1",
        "x" * 101,
    ],
)
def test_invalid_model_is_rejected_before_dispatch(monkeypatch, model):
    from thesis_core.conditional_runner import run_conditional

    def unexpected_lookup(_):
        pytest.fail("Invalid model must be rejected before resolving a transport")

    monkeypatch.setattr(
        "thesis_core.conditional_runner.shutil.which", unexpected_lookup
    )
    with pytest.raises(ValueError, match="requested model"):
        run_conditional(None, None, model=model)


def invoke(tmp_path, code, *, timeout=3):
    return capture_pair(
        (sys.executable, "-c", code),
        b"the frozen pair",
        directory=tmp_path,
        timeout_seconds=timeout,
    )


def test_one_process_gets_pair_and_preserves_separate_channels(tmp_path, monkeypatch):
    monkeypatch.setenv("THESIS_SYNTHETIC_API_KEY", "private-test-value")
    result = invoke(
        tmp_path,
        """
import json, os, sys
from pathlib import Path
prompt = sys.stdin.buffer.read().decode()
assert 'THESIS_SYNTHETIC_API_KEY' not in os.environ
Path('response.json').write_text(json.dumps({'prompt': prompt}))
print('provider event stream')
print('provider diagnostic', file=sys.stderr)
""",
    )
    assert result.error_code is None
    assert json.loads(result.response) == {"prompt": "the frozen pair"}
    assert result.stdout == b"provider event stream\n"
    assert result.stderr == b"provider diagnostic\n"


def test_timeout_does_not_retry_or_accept_partial_response(tmp_path):
    started = time.monotonic()
    result = invoke(
        tmp_path,
        """
import time
from pathlib import Path
Path('response.json').write_text('{"partial":true}')
with Path('invocations').open('a') as f: f.write('one\\n')
time.sleep(20)
""",
        timeout=0.2,
    )
    assert time.monotonic() - started < 3
    assert result.error_code == "timeout"
    assert (tmp_path / "invocations").read_text() == "one\n"


def test_exited_parent_cannot_leave_descendant_holding_streams(tmp_path):
    started = time.monotonic()
    result = invoke(
        tmp_path,
        """
import subprocess, sys
subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])
""",
    )
    assert time.monotonic() - started < 3
    assert result.error_code == "missing_response"


@pytest.mark.parametrize("channel", ["stdout", "response"])
def test_oversized_stream_or_response_is_refused(tmp_path, channel):
    code = """
import sys
from pathlib import Path
data = b'x' * (9 * 1024 * 1024)
if CHANNEL == 'stdout':
    sys.stdout.buffer.write(data)
else:
    Path('response.json').write_bytes(data)
""".replace("CHANNEL", repr(channel))
    result = invoke(tmp_path, code)
    assert result.error_code == "output_too_large"
    assert len(result.stdout) <= 8 * 1024 * 1024
    assert result.response is None


def test_response_symlink_is_never_ingested(tmp_path):
    result = invoke(
        tmp_path,
        """
from pathlib import Path
Path('outside.json').write_text('do not ingest')
Path('response.json').symlink_to('outside.json')
""",
    )
    assert result.error_code == "missing_response"
    assert result.response is None


def test_spawn_failure_has_no_fabricated_model_response(tmp_path):
    result = capture_pair(
        ("/this-executable-does-not-exist",),
        b"",
        directory=tmp_path,
        timeout_seconds=1,
    )
    assert result.error_code == "spawn_failed"
    assert result.response is None


def test_runner_dispatch_is_durable_before_one_complete_pair_call(
    core_store, monkeypatch
):
    from thesis_core.conditional_runner import CapturedPair, run_conditional
    from thesis_core.conditionals import conditional_page

    from .test_conditionals import contract, response_data

    spec = contract(core_store.artifacts.put_bytes(b"official"))
    calls = []

    def captured(argv, prompt, *, directory, timeout_seconds):
        calls.append(argv)
        page = conditional_page(core_store)
        assert page.total == 1
        assert page.items[0].execution_state == "running"
        assert page.items[0].requested_model == "test-model"
        assert 0 < timeout_seconds < 30
        assert b'"enacted"' in prompt and b'"neither"' in prompt
        return CapturedPair(
            b"provider event\n", b"", json.dumps(response_data(spec)).encode(), None
        )

    monkeypatch.setattr(
        "thesis_core.conditional_runner.shutil.which", lambda _: sys.executable
    )
    monkeypatch.setattr("thesis_core.conditional_runner.capture_pair", captured)
    detail = run_conditional(core_store, spec, model="test-model", timeout_seconds=30)
    assert len(calls) == 1
    assert detail.execution_state == "succeeded"
    assert detail.observed_model is None
    assert detail.scoring_status == "not_registered"
    assert tuple(core_store.iter_records()) == ()


def test_operator_interrupt_seals_partial_channels_without_retry(
    core_store, monkeypatch
):
    from thesis_core.conditional_runner import (
        CapturedPair,
        CaptureInterrupted,
        run_conditional,
    )
    from thesis_core.conditionals import conditional_detail, conditional_page

    from .test_conditionals import contract

    spec = contract(core_store.artifacts.put_bytes(b"official"))
    calls = []

    def interrupted(*args, **kwargs):
        calls.append(True)
        raise CaptureInterrupted(
            CapturedPair(
                b"partial provider event", b"diagnostic", b"partial JSON", "interrupted"
            ),
            KeyboardInterrupt(),
        )

    monkeypatch.setattr(
        "thesis_core.conditional_runner.shutil.which", lambda _: sys.executable
    )
    monkeypatch.setattr("thesis_core.conditional_runner.capture_pair", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_conditional(core_store, spec, model="test-model", timeout_seconds=30)
    page = conditional_page(core_store)
    assert len(calls) == page.total == 1
    detail = conditional_detail(core_store, page.items[0].id)
    assert detail.execution_state == "failed"
    assert detail.error_code == "interrupted"
    assert detail.response is None
    refs = {item.role: item.sha256 for item in detail.artifacts}
    assert core_store.artifacts.read_bytes(refs["stdout"]) == b"partial provider event"
    assert core_store.artifacts.read_bytes(refs["response"]) == b"partial JSON"
