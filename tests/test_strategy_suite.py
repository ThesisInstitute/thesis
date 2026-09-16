from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_strategy_suite as suite_runner  # noqa: E402


def test_suite_runner_emits_exact_lane_inventory(tmp_path, monkeypatch) -> None:
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    selection_path = tmp_path / "strategy-targets.json"
    selection = {
        "schemaVersion": "thesis_strategy_selection_v1",
        "sourceSha": source_sha,
        "selectedAtUtc": "2030-01-01T00:00:00Z",
        "selectionPath": (
            "records/thesis-analyst/strategy-selections/2030-01-01/"
            "strategy-123-a1.json"
        ),
        "selectionSetHash": "a" * 64,
        "request": {"suite": "both"},
        "targets": [{"catalogSlug": "fixture-target"}],
    }
    selection_path.write_text(json.dumps(selection) + "\n")

    batches: list[tuple[str, bool]] = []

    def fake_batch(**kwargs):
        batches.append((kwargs["prompt_mode"], kwargs["reviewed"]))
        return {
            "schemaVersion": "thesis_batch_manifest_v1",
            "results": [
                {
                    "ok": True,
                    "target": {"catalogSlug": "fixture-target"},
                }
            ],
        }

    monkeypatch.setattr(suite_runner, "run_batch", fake_batch)
    monkeypatch.setattr(
        suite_runner,
        "derive_medians",
        lambda targets, rollouts: [
            {
                "catalogSlug": targets[0]["catalogSlug"],
                "ok": True,
                "manifestPath": "records/derived/manifest.json",
                "error": None,
            }
        ],
    )
    monkeypatch.setattr(
        suite_runner,
        "batch_path",
        lambda day, run_id, attempt, lane: tmp_path / f"{lane}.json",
    )
    output = tmp_path / "strategy-suites" / "2030-01-02" / "strategy-123-a1.json"
    monkeypatch.setattr(
        suite_runner,
        "suite_path",
        lambda day, run_id, attempt: output,
    )
    monkeypatch.setattr(
        suite_runner,
        "repo_relative",
        lambda path: f"records/fixture/{path.name}",
    )
    monkeypatch.setattr(suite_runner, "utc_now", lambda: "2030-01-02T00:00:00Z")

    payload = suite_runner.run_suite(
        selection_path=selection_path,
        run_id=123,
        run_attempt=1,
        output_path=None,
        model="fixture-model",
        timeout_seconds=1,
    )

    assert batches == [("ladder", True), *[("fast", False)] * 3]
    assert payload["lanes"]["ladder"] == {
        "batchManifest": "records/fixture/ladder.json",
        "promptMode": "ladder",
    }
    assert [row["index"] for row in payload["lanes"]["rollouts"]] == [1, 2, 3]
    assert payload["lanes"]["median3"][0]["ok"] is True
    # Every suite records the System One lane; a codex suite ran none.
    assert payload["lanes"]["systemOne"] is None
    assert payload["selectionSha256"] == hashlib.sha256(
        selection_path.read_bytes()
    ).hexdigest()
    assert json.loads(output.read_text()) == payload


def test_suite_runner_honors_trusted_ladder_prompt_mode(
    tmp_path, monkeypatch
) -> None:
    # ladder_v2 comes from the TRUSTED selection request; the ladder lane
    # runs under it and the manifest records it.
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    selection_path = tmp_path / "strategy-targets.json"
    selection = {
        "schemaVersion": "thesis_strategy_selection_v1",
        "sourceSha": source_sha,
        "selectedAtUtc": "2030-01-01T00:00:00Z",
        "selectionPath": (
            "records/thesis-analyst/strategy-selections/2030-01-01/"
            "strategy-124-a1.json"
        ),
        "selectionSetHash": "a" * 64,
        "request": {"suite": "ladder", "ladderPromptMode": "ladder_v2"},
        "targets": [{"catalogSlug": "fixture-target"}],
    }
    selection_path.write_text(json.dumps(selection) + "\n")

    batches: list[tuple[str, bool]] = []

    def fake_batch(**kwargs):
        batches.append((kwargs["prompt_mode"], kwargs["reviewed"]))
        return {
            "schemaVersion": "thesis_batch_manifest_v1",
            "results": [{"ok": True, "target": {"catalogSlug": "fixture-target"}}],
        }

    monkeypatch.setattr(suite_runner, "run_batch", fake_batch)
    monkeypatch.setattr(
        suite_runner,
        "batch_path",
        lambda day, run_id, attempt, lane: tmp_path / f"{lane}.json",
    )
    output = tmp_path / "strategy-suites" / "2030-01-02" / "strategy-124-a1.json"
    monkeypatch.setattr(
        suite_runner, "suite_path", lambda day, run_id, attempt: output
    )
    monkeypatch.setattr(
        suite_runner, "repo_relative", lambda path: f"records/fixture/{path.name}"
    )
    monkeypatch.setattr(suite_runner, "utc_now", lambda: "2030-01-02T00:00:00Z")

    payload = suite_runner.run_suite(
        selection_path=selection_path,
        run_id=124,
        run_attempt=1,
        output_path=None,
        model="fixture-model",
        timeout_seconds=1,
    )
    assert batches == [("ladder_v2", True)]
    assert payload["lanes"]["ladder"]["promptMode"] == "ladder_v2"

    # An unknown mode in the selection fails closed.
    bad = dict(selection)
    bad["request"] = {"suite": "ladder", "ladderPromptMode": "ladder_v3"}
    selection_path.write_text(json.dumps(bad) + "\n")
    with pytest.raises(suite_runner.StrategySuiteError, match="ladder prompt mode"):
        suite_runner.run_suite(
            selection_path=selection_path,
            run_id=124,
            run_attempt=1,
            output_path=None,
            model="fixture-model",
            timeout_seconds=1,
        )


# A stand-in for scripts/run_system_one_forecast.py: it records its argv,
# writes a sealed-looking manifest and the --out-manifest pointer, and takes
# its exit code from the slug so one fixture covers passing, sealed-failure
# and refused-input runs.
STUB_RUNNER = """
import json
import pathlib
import sys

argv = sys.argv[1:]
with (pathlib.Path.cwd() / "argv.log").open("a") as log:
    log.write(json.dumps(argv) + "\\n")


def option(name):
    return argv[argv.index(name) + 1] if name in argv else None


target = json.loads(pathlib.Path(option("--target-json")).read_text())
slug = target["catalogSlug"]
if slug.endswith("refuse"):
    print("system_one: TYPESAFE_API_KEY is not set", file=sys.stderr)
    raise SystemExit(2)
if slug.endswith("crash"):
    print("system_one: killed mid-run", file=sys.stderr)
    raise SystemExit(1)
if slug.endswith("escape"):
    pathlib.Path(option("--out-manifest")).write_text("/etc/passwd\\n")
    raise SystemExit(0)
ok = not slug.endswith("fail")
run = pathlib.Path("records/thesis-analyst/2030-01-02") / (
    "2030-01-02t00-00-00z-system-one-" + slug
)
run.mkdir(parents=True, exist_ok=True)
cells = run / "cells.with_activity.json"
cells.write_text("[]\\n")
manifest = {
    "schemaVersion": "thesis_system_one_run_manifest_v1",
    "runMode": "system_one",
    "promptMode": "system_one_noul_ladder",
    "targetContext": target,
    "ok": ok,
    "cellsPath": cells.as_posix() if ok else None,
    "error": None if ok else {"phase": "ladder", "message": "off-ladder mass"},
}
(run / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\\n")
pathlib.Path(option("--out-manifest")).write_text(
    (run / "manifest.json").as_posix() + "\\n"
)
print(json.dumps(manifest))
raise SystemExit(0 if ok else 1)
"""


def install_stub_runner(tmp_path, monkeypatch) -> pathlib.Path:
    stub = tmp_path / "stub_system_one.py"
    stub.write_text(STUB_RUNNER)
    monkeypatch.setattr(suite_runner, "ROOT", tmp_path)
    monkeypatch.setattr(suite_runner, "RUN_SYSTEM_ONE", stub)
    return stub


def system_one_target(slug: str) -> dict:
    return {"catalogSlug": slug, "targetUnit": "percent", "series": "agency.test"}


def test_system_one_batch_runs_the_runner_once_per_target(
    tmp_path, monkeypatch
) -> None:
    install_stub_runner(tmp_path, monkeypatch)
    ledger = tmp_path / "pinned-ledger.jsonl"
    ledger.write_text("")
    output = tmp_path / "records" / "batches" / "system-one.json"

    batch = suite_runner.run_system_one_batch(
        targets=[system_one_target("zz-second"), system_one_target("aa-first-fail")],
        output_path=output,
        backend="adapter",
        model=None,
        ledger_path=ledger,
        timeout_seconds=120,
    )

    assert batch["schemaVersion"] == "thesis_batch_manifest_v1"
    assert batch["promptMode"] == "system_one_noul_ladder"
    assert batch["backend"] == "adapter"
    assert batch["model"] is None
    assert (batch["targets"], batch["ok"], batch["failed"]) == (2, 1, 1)
    assert batch["startedAt"] <= batch["results"][0]["startedAt"]
    assert batch["results"][-1]["finishedAt"] <= batch["finishedAt"]
    assert json.loads(output.read_text()) == batch

    failed, passed = batch["results"]
    assert [row["target"]["catalogSlug"] for row in batch["results"]] == [
        "aa-first-fail",
        "zz-second",
    ]
    assert set(passed) == {
        "target",
        "startedAt",
        "finishedAt",
        "ok",
        "manifestPath",
        "cellsPath",
        "error",
    }
    assert passed["ok"] is True
    assert passed["manifestPath"] == (
        "records/thesis-analyst/2030-01-02/"
        "2030-01-02t00-00-00z-system-one-zz-second/manifest.json"
    )
    assert passed["cellsPath"] == (
        "records/thesis-analyst/2030-01-02/"
        "2030-01-02t00-00-00z-system-one-zz-second/cells.with_activity.json"
    )
    assert passed["error"] is None
    # A sealed failure still carries its run, and its phase reaches the batch.
    assert failed["ok"] is False
    assert failed["manifestPath"].endswith("aa-first-fail/manifest.json")
    assert failed["cellsPath"] is None
    assert failed["error"] == "ladder: off-ladder mass"

    argv = [
        json.loads(line)
        for line in (tmp_path / "argv.log").read_text().splitlines()
        if line.strip()
    ]
    assert len(argv) == 2
    for call in argv:
        assert call[call.index("--backend") + 1] == "adapter"
        assert call[call.index("--ledger-jsonl") + 1] == str(ledger)
        assert "--out-manifest" in call
        # A null trusted model means the runner's own default.
        assert "--model" not in call


def test_system_one_batch_passes_the_trusted_model_and_fails_on_refusal(
    tmp_path, monkeypatch
) -> None:
    install_stub_runner(tmp_path, monkeypatch)

    suite_runner.run_system_one_batch(
        targets=[system_one_target("fixture-target")],
        output_path=tmp_path / "batch.json",
        backend="typesafe",
        model="jev-1",
        ledger_path=None,
        timeout_seconds=120,
    )
    call = json.loads((tmp_path / "argv.log").read_text().strip())
    assert call[call.index("--backend") + 1] == "typesafe"
    assert call[call.index("--model") + 1] == "jev-1"
    assert "--ledger-jsonl" not in call

    # Refused input means nothing was recorded: that is a misconfigured lane,
    # not a forecast failure, so the suite fails instead of publishing zeros.
    with pytest.raises(suite_runner.StrategySuiteError, match="refused"):
        suite_runner.run_system_one_batch(
            targets=[system_one_target("fixture-refuse")],
            output_path=tmp_path / "refused.json",
            backend="typesafe",
            model=None,
            ledger_path=None,
            timeout_seconds=120,
        )
    assert not (tmp_path / "refused.json").exists()

    # A run that dies before sealing leaves nothing the boundary could
    # publish, so the lane fails where the reason is still legible.
    with pytest.raises(suite_runner.StrategySuiteError, match="sealed no manifest"):
        suite_runner.run_system_one_batch(
            targets=[system_one_target("fixture-crash")],
            output_path=tmp_path / "crashed.json",
            backend="adapter",
            model=None,
            ledger_path=None,
            timeout_seconds=120,
        )
    assert not (tmp_path / "crashed.json").exists()

    # The lane reads the run back out of the records tree, so a pointer
    # aimed anywhere else is refused before anything is loaded.
    with pytest.raises(
        suite_runner.StrategySuiteError, match="outside the records tree"
    ):
        suite_runner.run_system_one_batch(
            targets=[system_one_target("fixture-escape")],
            output_path=tmp_path / "escaped.json",
            backend="adapter",
            model=None,
            ledger_path=None,
            timeout_seconds=120,
        )
    assert not (tmp_path / "escaped.json").exists()


def system_one_selection_file(tmp_path, request: dict) -> pathlib.Path:
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    path = tmp_path / "strategy-targets.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": "thesis_strategy_selection_v1",
                "sourceSha": source_sha,
                "selectedAtUtc": "2030-01-01T00:00:00Z",
                "selectionPath": (
                    "records/thesis-analyst/strategy-selections/2030-01-01/"
                    "strategy-125-a1.json"
                ),
                "selectionSetHash": "a" * 64,
                "request": request,
                "targets": [{"catalogSlug": "fixture-target"}],
            }
        )
        + "\n"
    )
    return path


def test_suite_runner_emits_the_system_one_lane(tmp_path, monkeypatch) -> None:
    selection_path = system_one_selection_file(
        tmp_path,
        {
            "suite": "system_one",
            "systemOneBackend": "typesafe",
            "systemOneModel": "jev-1",
        },
    )
    calls: dict = {}

    def fake_system_one_batch(**kwargs):
        calls.update(kwargs)
        return {"schemaVersion": "thesis_batch_manifest_v1", "results": []}

    def never(*args, **kwargs):
        raise AssertionError("the codex lanes must not run for a system_one suite")

    lanes_seen: list[tuple] = []

    monkeypatch.setattr(suite_runner, "run_system_one_batch", fake_system_one_batch)
    monkeypatch.setattr(suite_runner, "run_batch", never)
    monkeypatch.setattr(suite_runner, "derive_medians", never)
    monkeypatch.setattr(
        suite_runner,
        "batch_path",
        lambda day, run_id, attempt, lane: (
            lanes_seen.append((day, run_id, attempt, lane)) or tmp_path / f"{lane}.json"
        ),
    )
    output = tmp_path / "strategy-suites" / "2030-01-02" / "strategy-125-a1.json"
    monkeypatch.setattr(suite_runner, "suite_path", lambda day, run_id, attempt: output)
    monkeypatch.setattr(
        suite_runner, "repo_relative", lambda path: f"records/fixture/{path.name}"
    )
    monkeypatch.setattr(suite_runner, "utc_now", lambda: "2030-01-02T00:00:00Z")

    ledger = tmp_path / "pinned-ledger.jsonl"
    ledger.write_text("")
    payload = suite_runner.run_suite(
        selection_path=selection_path,
        run_id=125,
        run_attempt=1,
        output_path=None,
        model="fixture-model",
        timeout_seconds=17,
        ledger_path=ledger,
    )

    assert payload["suite"] == "system_one"
    assert payload["lanes"] == {
        "ladder": None,
        "rollouts": [],
        "median3": [],
        "systemOne": {
            "batchManifest": "records/fixture/system-one.json",
            "backend": "typesafe",
            "model": "jev-1",
        },
    }
    assert lanes_seen == [("2030-01-01", 125, 1, "system-one")]
    assert calls["backend"] == "typesafe"
    assert calls["model"] == "jev-1"
    assert calls["ledger_path"] == ledger
    assert calls["timeout_seconds"] == 17
    assert calls["targets"] == [{"catalogSlug": "fixture-target"}]
    assert json.loads(output.read_text()) == payload


def test_system_one_batch_path_is_invocation_scoped() -> None:
    # The lane name the suite runner passes must land on exactly this path.
    assert suite_runner.batch_path("2030-01-01", 125, 1, "system-one") == (
        ROOT
        / "records/thesis-analyst/batches/2030-01-01/strategy-125-a1-system-one.json"
    )


def test_suite_runner_refuses_an_untrusted_system_one_forecaster(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        suite_runner,
        "run_system_one_batch",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("the lane must not run on a refused forecaster")
        ),
    )
    bad_backend = system_one_selection_file(
        tmp_path, {"suite": "system_one", "systemOneBackend": "openai"}
    )
    with pytest.raises(suite_runner.StrategySuiteError, match="system_one backend"):
        suite_runner.run_suite(
            selection_path=bad_backend,
            run_id=126,
            run_attempt=1,
            output_path=None,
            model="fixture-model",
            timeout_seconds=1,
        )

    bad_model = system_one_selection_file(
        tmp_path,
        {
            "suite": "system_one",
            "systemOneBackend": "adapter",
            "systemOneModel": "--records-root",
        },
    )
    with pytest.raises(suite_runner.StrategySuiteError, match="system_one model"):
        suite_runner.run_suite(
            selection_path=bad_model,
            run_id=127,
            run_attempt=1,
            output_path=None,
            model="fixture-model",
            timeout_seconds=1,
        )


def test_system_one_lane_drives_the_real_runner_to_sealed_custody(
    tmp_path, monkeypatch
) -> None:
    # The stub above pins the batch shape; this pins the contract with the
    # real runner: argv, the --out-manifest pointer, the exit code and the
    # manifest keys the lane reads.  The runner resolves its own repository
    # root from its file, so a scratch copy keeps every write out of the
    # checkout's records tree.
    import importlib.util
    import shutil

    import verify_custody

    # Load the runner suite's own fixtures by path rather than
    # hand-writing a second primary cell that could drift from it.
    spec = importlib.util.spec_from_file_location(
        "system_one_fixtures", ROOT / "tests" / "test_run_system_one_forecast.py"
    )
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    primary_cell = fixtures.primary_cell
    target_context = fixtures.target_context
    write_primary_run = fixtures.write_primary_run

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for module in sorted((ROOT / "scripts").glob("*.py")):
        shutil.copyfile(module, scripts / module.name)
    write_primary_run(tmp_path, primary_cell())

    monkeypatch.setattr(suite_runner, "ROOT", tmp_path)
    monkeypatch.setattr(suite_runner, "RUN_SYSTEM_ONE", scripts / "run_system_one.py")
    shutil.copyfile(
        ROOT / "scripts" / "run_system_one_forecast.py",
        scripts / "run_system_one.py",
    )
    monkeypatch.setattr(verify_custody, "REPOSITORY_ROOT", tmp_path)

    target = target_context()
    batch = suite_runner.run_system_one_batch(
        targets=[target],
        output_path=tmp_path / "records" / "batch.json",
        backend="mock",
        model=None,
        ledger_path=None,
        timeout_seconds=300,
    )

    assert (batch["targets"], batch["ok"], batch["failed"]) == (1, 1, 0)
    result = batch["results"][0]
    assert result["ok"] is True
    assert result["error"] is None
    assert result["target"] == target
    manifest_path = tmp_path / result["manifestPath"]
    manifest = json.loads(manifest_path.read_text())
    assert manifest["runMode"] == "system_one"
    assert manifest["promptMode"] == "system_one_noul_ladder"
    assert manifest["agent"]["agent"] == "thesis.system_one"
    assert result["cellsPath"] == manifest["cellsPath"]

    verification = verify_custody.verify_run(manifest_path.parent)
    assert verification.run_mode == "system_one"
    assert verification.inventory_status == "complete"
    assert verification.run_succeeded is True
