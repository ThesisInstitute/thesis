from __future__ import annotations

import collections
import datetime as dt
import json
import math
import pathlib
import re
import subprocess
import sys
from urllib.parse import urlparse

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_thesis_analyst import BASE_RATE_FETCH_COMMANDS  # noqa: E402
from verify_records_attestations import ALLOWED_WORKFLOWS  # noqa: E402

BATTERY = ROOT / "agents/thesis-analyst/canary/battery.json"
WORKFLOW = ROOT / ".github/workflows/api-canary.yml"
SAFE_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def test_api_canary_battery_is_fixed_synthetic_and_runner_complete() -> None:
    battery = json.loads(BATTERY.read_text())
    assert battery["schemaVersion"] == "thesis_api_canary_battery_v1"
    assert battery["preregistrationBasis"] == "introducing_git_commit"
    assert battery["promptMode"] == "fast"
    items = battery["items"]
    assert 4 <= len(items) <= 6

    required_context = {
        "series",
        "period",
        "catalogSlug",
        "country",
        "targetUnit",
        "dataPointId",
        "resolutionDate",
        "resolutionSource",
        "resolutionSourceUrl",
        "resolutionRule",
        "resolutionPolicy",
        "conditional",
        "anchors",
        "sourceBinding",
    }
    ids = set()
    slugs = set()
    data_points = set()
    pairs: collections.Counter[str] = collections.Counter()
    conditionals: dict[str, set[str]] = collections.defaultdict(set)
    for item in items:
        assert set(item) == {
            "id",
            "pairId",
            "series",
            "period",
            "conditional",
            "targetContext",
        }
        assert item["id"] not in ids
        assert SAFE_SLUG.fullmatch(item["id"])
        assert SAFE_SLUG.fullmatch(item["pairId"].removeprefix("canary."))
        assert item["conditional"].strip()
        ids.add(item["id"])
        pairs[item["pairId"]] += 1
        conditionals[item["pairId"]].add(item["conditional"])
        context = item["targetContext"]
        assert required_context <= set(context)
        assert context["series"] == item["series"]
        assert context["period"] == item["period"]
        assert context["conditional"] == item["conditional"]
        assert context["resolutionSource"] == "Canary synthetic (not a real target)"
        assert context["resolutionPolicy"] == "first_print"
        assert context["dataPointId"].startswith("canary.")
        assert context["catalogSlug"].startswith("canary-")
        assert SAFE_SLUG.fullmatch(context["catalogSlug"])
        assert context["catalogSlug"] not in slugs
        assert context["dataPointId"] not in data_points
        slugs.add(context["catalogSlug"])
        data_points.add(context["dataPointId"])
        assert len(context["anchors"]) >= 3
        assert all(
            type(value) in (int, float) and math.isfinite(value)
            for value in context["anchors"].values()
        )
        binding = context["sourceBinding"]
        assert {
            "adapter",
            "allowedHosts",
            "expectedReleaseWindow",
            "sourceUrl",
            "sourceSeriesId",
            "field",
            "table",
            "transform",
            "releasePolicy",
        } <= set(binding)
        assert binding["adapter"] in BASE_RATE_FETCH_COMMANDS
        assert binding["releasePolicy"] == "first_print"
        assert binding["sourceSeriesId"] == item["series"]
        assert binding["sourceUrl"] == context["resolutionSourceUrl"]
        parsed_source = urlparse(binding["sourceUrl"])
        assert parsed_source.scheme == "https"
        assert parsed_source.hostname in binding["allowedHosts"]
        release_window = binding["expectedReleaseWindow"]
        window_start = dt.date.fromisoformat(release_window["start"])
        window_end = dt.date.fromisoformat(release_window["end"])
        resolution_date = dt.date.fromisoformat(context["resolutionDate"])
        assert window_start <= window_end <= resolution_date
    assert pairs == {
        "canary.actc-threshold": 2,
        "canary.crp-acreage-ceiling": 2,
    }
    assert all(len(values) == 2 for values in conditionals.values())


def test_api_canary_workflow_is_read_only_and_keeps_failures_as_product() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    trigger = workflow.get("on", workflow.get(True))
    assert set(trigger) == {"workflow_dispatch", "schedule"}
    assert trigger["schedule"] == [{"cron": "17 9 * * 1"}]
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"canary"}
    job = workflow["jobs"]["canary"]
    assert job["permissions"] == {"contents": "read"}
    assert job["strategy"] == {
        "fail-fast": False,
        "max-parallel": 1,
        "matrix": {
            "include": [
                {"model": "gpt-5.6-terra", "effort": "high"},
                {"model": "gpt-5.6", "effort": "high"},
            ]
        },
    }

    source = WORKFLOW.read_text()
    assert "bun add -g @openai/codex@0.144.0" in source
    assert "printenv OPENAI_API_KEY | codex login --with-api-key" in source
    assert "scripts/run_thesis_analyst.py" in source
    assert "--target-context-json" in source
    assert "--codex-model" in source
    assert "--codex-reasoning-effort" in source
    assert "--codex-sandbox workspace-write" in source
    assert "--codex-network" in source
    assert "--pre-submit-review-codex-model gpt-5.6" in source
    assert '"${args[@]}"' in source
    assert ") >/dev/null 2>&1 || true" in source
    assert "git worktree add --detach" in source
    assert "git worktree remove --force" in source
    assert 'RUN_PARENT=$(mktemp -d "/tmp/thesis-api-canary-$ID.XXXXXX")' in source
    assert 'RUN_CHECKOUT="$RUN_PARENT/checkout"' in source
    assert 'OUT_DIR="$RUN_CHECKOUT/runs/$ID"' in source
    assert "from run_thesis_analyst import validate_cells" in source
    assert "from verify_custody import verify_run" in source
    assert "verify_from(checkout, out_dir)" in source
    assert "verify_from(candidate_root, candidate)" in source
    assert "verify_from(capture, destination)" in source
    assert "candidate.rename(destination)" in source
    assert "validate_cells(" in source
    assert "isinstance(cells, list) and len(cells) == 1" in source
    assert "Stage verified canary artifact" in source
    assert "verify_from(capture, run_dir)" in source
    assert 'capture_names != {"runs", "status"}' in source
    assert "shutil.copytree(run_dir, run_destination)" in source
    assert "verify_from(candidate, run_destination)" in source
    assert "shutil.rmtree(run_destination)" in source
    assert 'staged_reports / f"{item_id}.validation.json"' in source
    assert "shutil.copy2(" not in source
    assert ".runner.log" not in source
    assert ".exception.txt" not in source
    assert "${{ runner.temp }}/thesis-api-canary-stage/" in source
    assert "${{ runner.temp }}/thesis-api-canary-capture/" in source
    assert "path: ${{ runner.temp }}/thesis-api-canary-stage/" in source
    assert "CANARY_ROOT" not in source
    assert "GITHUB_STEP_SUMMARY" in source
    assert "actions/upload-artifact@v7" in source
    assert "${{ github.run_id }}-${{ github.run_attempt }}" in source
    assert "/tmp/thesis-api-canary-$ID.XXXXXX" in source
    assert "records/" not in source
    assert "site/src" not in source
    assert "attest-records-push" not in source
    assert "THESIS_ALLOW_RECORDS_PUSH" not in source
    assert ".github/workflows/api-canary.yml" not in ALLOWED_WORKFLOWS

    runner_step = next(
        step
        for step in job["steps"]
        if step.get("name") == "Run fixed canary battery"
    )
    assert runner_step["run"].index("verify_from(capture, destination)") < runner_step[
        "run"
    ].index("done <")


def test_api_canary_multiline_steps_are_valid_bash() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    names = {
        "Run fixed canary battery",
        "Stage verified canary artifact",
        "Write canary summary",
    }
    steps = {
        step.get("name"): step
        for step in workflow["jobs"]["canary"]["steps"]
        if step.get("name") in names
    }
    assert set(steps) == names
    for name, step in steps.items():
        result = subprocess.run(
            ["bash", "-n"],
            input=step["run"],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f"{name}: {result.stderr}"

        python_blocks = re.findall(
            r"python3 - <<'PY'\n(.*?)\nPY(?:\n|$)",
            step["run"],
            flags=re.DOTALL,
        )
        for block in python_blocks:
            compile(block, f"api-canary.yml:{name}", "exec")
