"""The receipt Chronicle's staged generator needs versus the one thesis runs."""

from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

tomllib = pytest.importorskip("tomllib")
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import chronicle_receipt_pin as pin  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "chronicle_receipt_pin"
# Chronicle's lock at the merge that pinned 0.6.1 and at the one that pinned
# 0.6.2 (chronicle#299, the change resolver run 36503673388 met).
CHRONICLE_061 = FIXTURES / "uv-lock-3dd95a0.toml"
CHRONICLE_062 = FIXTURES / "uv-lock-4b4395b.toml"
THESIS_LOCK = (ROOT / "uv.lock").read_bytes()
LABEL = "PolicyEngine/chronicle@4b4395b07dcf (codex/thesis-ledger-facts)"
RESOLVER_WORKFLOW = ROOT / ".github" / "workflows" / "resolve-and-rebuild.yml"
DRIFT_WORKFLOW = ROOT / ".github" / "workflows" / "receipt-pin-drift.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
INSTALL_ACTION = ROOT / ".github" / "actions" / "install-resolver-python" / "action.yml"


def _thesis() -> pin.LockedPin:
    locked = pin.locked_pin(THESIS_LOCK, label="thesis")
    assert locked is not None
    return locked


def _chronicle_fixture_not_matching_thesis() -> tuple[bytes, str]:
    for path in (CHRONICLE_061, CHRONICLE_062):
        locked = pin.locked_pin(path.read_bytes(), label=path.name)
        assert locked is not None
        if locked.version != _thesis().version:
            return path.read_bytes(), locked.version
    raise AssertionError("both Chronicle fixtures lock thesis's receipt")


def _lock(*packages: str) -> bytes:
    return ("version = 1\nrevision = 3\n\n" + "\n".join(packages)).encode()


def _package(name: str, version: str, *hashes: str) -> str:
    wheels = "".join(
        f'    {{ url = "https://files.example/{name}-{index}.whl", '
        f'hash = "{value}" }},\n'
        for index, value in enumerate(hashes)
    )
    return (
        f'[[package]]\nname = "{name}"\nversion = "{version}"\n'
        f'source = {{ registry = "https://pypi.org/simple" }}\n'
        f"wheels = [\n{wheels}]\n"
    )


# --- reading a lock -----------------------------------------------------------


def test_the_chronicle_fixtures_are_the_real_lock_entries() -> None:
    assert pin.locked_pin(CHRONICLE_061.read_bytes(), label="061") == pin.LockedPin(
        version="0.6.1",
        artifacts=frozenset(
            {
                "sha256:7ad8f4b5f4ee609235c3d4d2c026aaad4c9043f763efd109e8be8dbda9cf9148",
                "sha256:ef846067c5b3da958969607c63af17a49dbe6d9fb10edfe704b638101499626e",
            }
        ),
    )
    # The digests PyPI publishes for receipt 0.6.2 (ThesisInstitute/thesis#302).
    assert pin.locked_pin(CHRONICLE_062.read_bytes(), label="062") == pin.LockedPin(
        version="0.6.2",
        artifacts=frozenset(
            {
                "sha256:699a9d870e27b8a61a825103177f49991f977f4c0d58605d17b8966fc0da4a9f",
                "sha256:4320a894f2c4a340583e31e2dc63e338e79fa5a8167089583bd60f0c57de2f6f",
            }
        ),
    )


def test_thesis_locks_one_hash_pinned_receipt_matching_the_custody_extra() -> None:
    # CI syncs without --locked, so a pyproject edit the lock never saw would
    # otherwise pass here and fail only in the resolver's `uv export --locked`.
    thesis = _thesis()
    assert thesis.artifacts
    assert all(re.fullmatch(r"sha256:[0-9a-f]{64}", h) for h in thesis.artifacts)
    custody = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
        "optional-dependencies"
    ]["custody"]
    specs = [spec for spec in custody if spec.startswith("receipt")]
    assert len(specs) == 1
    assert specs[0].split(";", 1)[0].strip() == f"receipt=={thesis.version}"


def test_a_lock_without_receipt_locks_none() -> None:
    assert (
        pin.locked_pin(
            _lock(_package("xlrd", "2.0.1", "sha256:" + "a" * 64)), label="x"
        )
        is None
    )


@pytest.mark.parametrize(
    ("lock", "message"),
    [
        (b"not = [toml", "is not a readable uv.lock"),
        (b"\xff\xfe", "is not a readable uv.lock"),
        (b"version = 1\n", "has no [[package]] entries"),
        (
            _lock(
                _package("receipt", "0.6.1", "sha256:" + "a" * 64),
                _package("receipt", "0.6.2", "sha256:" + "b" * 64),
            ),
            "locks 2 receipt entries (0.6.1, 0.6.2)",
        ),
        (
            _lock(_package("receipt", "0.6.2")),
            "locks receipt 0.6.2 without artifact hashes",
        ),
        (
            _lock('[[package]]\nname = "receipt"\nsource = { git = "https://x" }\n'),
            "locks receipt without a version",
        ),
    ],
)
def test_a_lock_that_does_not_name_one_hashed_receipt_is_refused(
    lock: bytes, message: str
) -> None:
    with pytest.raises(pin.ReceiptPinError, match=re.escape(message)):
        pin.locked_pin(lock, label="the lock")


def test_package_names_are_compared_normalized() -> None:
    locked = pin.locked_pin(
        _lock(_package("Receipt", "0.6.2", "sha256:" + "c" * 64)), label="x"
    )
    assert locked is not None and locked.version == "0.6.2"


# --- the comparison -------------------------------------------------------------


def test_a_chronicle_lock_on_another_receipt_is_refused() -> None:
    chronicle_lock, chronicle_version = _chronicle_fixture_not_matching_thesis()
    refusal = pin.receipt_pin_refusal(
        chronicle_lock, chronicle_label=LABEL, thesis_lock=THESIS_LOCK
    )
    assert refusal is not None
    assert refusal.startswith(
        f"thesis locks receipt {_thesis().version} but {LABEL} locks receipt "
        f"{chronicle_version}. "
    )
    assert f"receipt=={chronicle_version}" in refusal
    assert "uv lock --upgrade-package receipt" in refusal
    assert refusal.endswith(
        "(docs/receipt-pin.md has the checklist; "
        "https://github.com/ThesisInstitute/thesis/pull/302 is the last bump)"
    )
    assert (ROOT / "docs" / "receipt-pin.md").is_file()


@pytest.mark.parametrize(
    "fixture", [CHRONICLE_061, CHRONICLE_062], ids=["0.6.1", "0.6.2"]
)
def test_a_real_chronicle_lock_passes_exactly_when_it_names_thesiss_receipt(
    fixture: pathlib.Path,
) -> None:
    chronicle = pin.locked_pin(fixture.read_bytes(), label=fixture.name)
    assert chronicle is not None
    refusal = pin.receipt_pin_refusal(
        fixture.read_bytes(),
        chronicle_label=LABEL,
        thesis_lock=THESIS_LOCK,
        installed=_thesis().version,
    )
    # Same version means the two repositories' locks also name the same files.
    assert (refusal is None) == (chronicle.version == _thesis().version)


def test_the_same_version_with_different_files_is_refused() -> None:
    thesis = _thesis()
    chronicle_lock = _lock(_package("receipt", thesis.version, "sha256:" + "d" * 64))
    refusal = pin.receipt_pin_refusal(
        chronicle_lock, chronicle_label=LABEL, thesis_lock=THESIS_LOCK
    )
    assert refusal is not None
    assert f"both lock receipt {thesis.version} but name different files" in refusal
    assert "sha256:" + "d" * 64 in refusal


def test_a_chronicle_commit_without_a_lock_is_refused() -> None:
    assert pin.receipt_pin_refusal(
        None, chronicle_label=LABEL, thesis_lock=THESIS_LOCK
    ) == (
        f"{LABEL} has no uv.lock, so nothing says which receipt its "
        "series-catalog generator was tested with"
    )


def test_an_unreadable_chronicle_lock_is_refused_not_raised() -> None:
    refusal = pin.receipt_pin_refusal(
        b"[[package]", chronicle_label=LABEL, thesis_lock=THESIS_LOCK
    )
    assert (
        refusal is not None and f"{LABEL} uv.lock is not a readable uv.lock" in refusal
    )


def test_a_chronicle_lock_without_receipt_is_refused() -> None:
    # Thesis stages only named files, so a Chronicle that vendored receipt, or
    # dropped it, would still import thesis's receipt in the staged generator.
    chronicle_lock = _lock(_package("pyyaml", "6.0.2", "sha256:" + "e" * 64))
    assert pin.receipt_pin_refusal(
        chronicle_lock,
        chronicle_label=LABEL,
        thesis_lock=THESIS_LOCK,
        installed=_thesis().version,
    ) == (
        f"{LABEL} uv.lock locks no receipt, so nothing says which receipt its "
        "series-catalog generator was tested with"
    )


# --- invariants -------------------------------------------------------------------
#
# The check lets Chronicle's generator run exactly when Chronicle's lock and
# thesis's lock each name one hash-pinned receipt, the same version with the
# same artifact hashes, and (when asked) this interpreter has that version.
# Every other combination is refused with a reason, and nothing raises.

_V = ("0.6.1", "0.6.2")
_A = (
    frozenset({"sha256:" + "1" * 64}),
    frozenset({"sha256:" + "2" * 64}),
    frozenset({"sha256:" + "1" * 64, "sha256:" + "2" * 64}),
)
# A lock shape: None (no lock), "bare" (a lock without receipt), or
# (version, artifacts).
_LOCK_SHAPES = (None, "bare", *((v, a) for v in _V for a in _A))
_INSTALLED = ("unchecked", None, *_V)


def _shape_bytes(shape) -> bytes | None:
    if shape is None:
        return None
    if shape == "bare":
        return _lock(_package("xlrd", "2.0.1", "sha256:" + "9" * 64))
    version, artifacts = shape
    return _lock(_package("receipt", version, *sorted(artifacts)))


def _may_run(chronicle, thesis, installed) -> bool:
    """The reference predicate, written independently of the module."""

    locked = isinstance(chronicle, tuple) and isinstance(thesis, tuple)
    if not locked or chronicle != thesis:
        return False
    return installed == "unchecked" or installed == thesis[0]


def test_the_check_allows_exactly_the_agreeing_combinations() -> None:
    cases = 0
    for chronicle in _LOCK_SHAPES:
        for thesis in _LOCK_SHAPES[1:]:  # thesis's own lock always exists
            for installed in _INSTALLED:
                kwargs = {} if installed == "unchecked" else {"installed": installed}
                refusal = pin.receipt_pin_refusal(
                    _shape_bytes(chronicle),
                    chronicle_label=LABEL,
                    thesis_lock=_shape_bytes(thesis),
                    **kwargs,
                )
                assert (refusal is None) == _may_run(chronicle, thesis, installed), (
                    chronicle,
                    thesis,
                    installed,
                    refusal,
                )
                assert refusal is None or (isinstance(refusal, str) and refusal)
                cases += 1
    assert cases == len(_LOCK_SHAPES) * (len(_LOCK_SHAPES) - 1) * len(_INSTALLED)


@pytest.mark.parametrize(
    "fixture", [CHRONICLE_061, CHRONICLE_062], ids=["0.6.1", "0.6.2"]
)
def test_no_truncation_of_a_real_lock_passes_unless_it_still_names_thesiss_receipt(
    fixture: pathlib.Path,
) -> None:
    thesis = _thesis()
    thesis_lock = _lock(_package("receipt", thesis.version, *sorted(thesis.artifacts)))
    raw = fixture.read_bytes()
    for end in range(len(raw) + 1):
        refusal = pin.receipt_pin_refusal(
            raw[:end], chronicle_label=LABEL, thesis_lock=thesis_lock
        )
        if refusal is None:
            assert pin.locked_pin(raw[:end], label="prefix") == thesis


def test_arbitrary_bytes_are_refused_never_raised() -> None:
    import random

    generator = random.Random(20260928)
    for _ in range(300):
        junk = bytes(generator.randrange(256) for _ in range(generator.randrange(64)))
        refusal = pin.receipt_pin_refusal(
            junk, chronicle_label=LABEL, thesis_lock=THESIS_LOCK
        )
        assert isinstance(refusal, str) and refusal


def test_thesis_must_lock_the_receipt_chronicle_locks() -> None:
    thesis_lock = _lock(_package("xlrd", "2.0.1", "sha256:" + "f" * 64))
    refusal = pin.receipt_pin_refusal(
        CHRONICLE_062.read_bytes(), chronicle_label=LABEL, thesis_lock=thesis_lock
    )
    assert refusal == (
        f"{LABEL} locks receipt 0.6.2, but thesis's uv.lock locks no receipt; "
        "add it to the custody extra at 0.6.2"
    )


def test_the_interpreter_must_have_the_locked_receipt_when_asked() -> None:
    thesis = _thesis()
    agreeing = THESIS_LOCK
    assert (
        pin.receipt_pin_refusal(
            agreeing,
            chronicle_label=LABEL,
            thesis_lock=THESIS_LOCK,
            installed=thesis.version,
        )
        is None
    )
    missing = pin.receipt_pin_refusal(
        agreeing, chronicle_label=LABEL, thesis_lock=THESIS_LOCK, installed=None
    )
    assert missing is not None
    assert missing.startswith(f"receipt is not installed for {sys.executable}; ")
    other = pin.receipt_pin_refusal(
        agreeing, chronicle_label=LABEL, thesis_lock=THESIS_LOCK, installed="0.0.1"
    )
    assert other == (
        f"{sys.executable} has receipt 0.0.1, but thesis and {LABEL} both lock "
        f"receipt {thesis.version}. Reinstall the resolver runtime from thesis's "
        "uv.lock (.github/actions/install-resolver-python)"
    )
    # Leaving `installed` out compares the locks only (the drift monitor).
    assert (
        pin.receipt_pin_refusal(
            agreeing, chronicle_label=LABEL, thesis_lock=THESIS_LOCK
        )
        is None
    )


def test_installed_refusal_compares_this_interpreter_with_thesiss_lock() -> None:
    thesis = _thesis()
    assert pin.installed_refusal(THESIS_LOCK, thesis.version) is None
    assert pin.installed_refusal(THESIS_LOCK, None) == (
        f"{sys.executable} has no receipt, but thesis's uv.lock locks receipt "
        f"{thesis.version}"
    )


def test_installed_version_reads_this_interpreters_metadata() -> None:
    pytest.importorskip("receipt")
    import importlib.metadata

    assert pin.installed_version() == importlib.metadata.version("receipt")
    assert pin.installed_version("no-such-distribution-for-thesis") is None


def test_the_test_interpreter_runs_thesiss_locked_receipt() -> None:
    # The suite exercises thesis's receipt-signing code under this version.
    pytest.importorskip("receipt")
    assert pin.installed_version() == _thesis().version


# --- reading Chronicle's lock from GitHub -----------------------------------------


def _blob_sha(raw: bytes) -> str:
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


class FakeGitHub:
    def __init__(self, files: dict[str, bytes], *, commit: str = "c" * 40) -> None:
        self.commit = commit
        self.files = files
        self.calls: list[tuple[str, ...]] = []
        self.blobs = {_blob_sha(raw): raw for raw in files.values()}

    def __call__(self, *args: str) -> str:
        self.calls.append(args)
        path = args[0]
        if path == "repos/PolicyEngine/chronicle/commits/codex/thesis-ledger-facts":
            assert args[1:] == ("--jq", ".sha")
            return self.commit + "\n"
        if path == f"repos/PolicyEngine/chronicle/git/commits/{self.commit}":
            return json.dumps({"sha": self.commit, "tree": {"sha": "7" * 40}})
        if path == f"repos/PolicyEngine/chronicle/git/trees/{'7' * 40}":
            return json.dumps(
                {
                    "sha": "7" * 40,
                    "truncated": False,
                    "tree": [
                        {
                            "path": name,
                            "mode": "100644",
                            "type": "blob",
                            "sha": _blob_sha(raw),
                        }
                        for name, raw in self.files.items()
                    ],
                }
            )
        blob = path.rsplit("/", 1)[-1]
        if (
            path.startswith("repos/PolicyEngine/chronicle/git/blobs/")
            and blob in self.blobs
        ):
            raw = self.blobs[blob]
            return json.dumps(
                {
                    "sha": blob,
                    "encoding": "base64",
                    "content": base64.b64encode(raw).decode(),
                }
            )
        raise AssertionError(f"unexpected gh api call {args}")


def test_fetch_lock_returns_the_blob_bytes_at_that_commit() -> None:
    raw = CHRONICLE_062.read_bytes()
    gh = FakeGitHub({"uv.lock": raw, "pyproject.toml": b"[project]\n"})
    assert pin.fetch_lock("PolicyEngine/chronicle", "c" * 40, gh=gh) == raw


def test_fetch_lock_returns_none_when_the_commit_has_no_lock() -> None:
    gh = FakeGitHub({"pyproject.toml": b"[project]\n"})
    assert pin.fetch_lock("PolicyEngine/chronicle", "c" * 40, gh=gh) is None


def test_fetch_lock_refuses_bytes_that_do_not_hash_to_the_tree_entry() -> None:
    gh = FakeGitHub({"uv.lock": CHRONICLE_062.read_bytes()})
    blob = next(iter(gh.blobs))
    gh.blobs[blob] = CHRONICLE_061.read_bytes()
    with pytest.raises(pin.ReceiptPinError, match="GitHub blob bytes hash to"):
        pin.fetch_lock("PolicyEngine/chronicle", "c" * 40, gh=gh)


@pytest.mark.parametrize("value", ["main", "c" * 39, "C" * 40, ""])
def test_fetch_lock_takes_only_a_full_commit_sha(value: str) -> None:
    with pytest.raises(pin.ReceiptPinError, match="invalid commit SHA"):
        pin.fetch_lock("PolicyEngine/chronicle", value, gh=FakeGitHub({}))


# --- the command line -------------------------------------------------------------


def test_cli_refuses_when_chronicles_branch_locks_another_receipt(capsys) -> None:
    chronicle_lock, chronicle_version = _chronicle_fixture_not_matching_thesis()
    gh = FakeGitHub({"uv.lock": chronicle_lock})
    assert pin.main([], gh=gh) == 1
    out = capsys.readouterr().out
    assert out.startswith(
        f"RECEIPT PIN REFUSED: thesis locks receipt {_thesis().version} but "
        f"PolicyEngine/chronicle@cccccccccccc (codex/thesis-ledger-facts) locks "
        f"receipt {chronicle_version}."
    )


def test_cli_reports_agreement(capsys) -> None:
    gh = FakeGitHub({"uv.lock": THESIS_LOCK})
    assert pin.main([], gh=gh) == 0
    assert capsys.readouterr().out == (
        "thesis and PolicyEngine/chronicle@cccccccccccc (codex/thesis-ledger-facts) "
        f"both lock receipt {_thesis().version} ({len(_thesis().artifacts)} "
        "identical artifact hashes)\n"
    )


def test_cli_checks_an_exact_commit_without_resolving_a_branch(capsys) -> None:
    gh = FakeGitHub({"uv.lock": THESIS_LOCK}, commit="a" * 40)
    assert pin.main(["--ledger-sha", "a" * 40], gh=gh) == 0
    assert all("/commits/codex/" not in call[0] for call in gh.calls)
    assert "PolicyEngine/chronicle@aaaaaaaaaaaa both lock" in capsys.readouterr().out


def test_cli_exits_2_when_it_cannot_read_chronicle(capsys) -> None:
    def failing(*args: str) -> str:
        raise pin.ReceiptPinError("gh api failed: HTTP 502")

    assert pin.main([], gh=failing) == 2
    assert (
        capsys.readouterr().out
        == "cannot read Chronicle's lock: gh api failed: HTTP 502\n"
    )


def test_cli_check_installed_requires_the_locked_receipt(monkeypatch, capsys) -> None:
    monkeypatch.setattr(pin, "installed_version", lambda name="receipt": "0.0.1")
    assert pin.main(["--check-installed"], gh=FakeGitHub({"uv.lock": THESIS_LOCK})) == 1
    assert "has receipt 0.0.1, but thesis and" in capsys.readouterr().out


def test_cli_installed_only_makes_no_network_request(monkeypatch, capsys) -> None:
    def no_network(*args: str) -> str:
        raise AssertionError("--installed-only must not call GitHub")

    monkeypatch.setattr(
        pin, "installed_version", lambda name="receipt": _thesis().version
    )
    assert pin.main(["--installed-only"], gh=no_network) == 0
    monkeypatch.setattr(pin, "installed_version", lambda name="receipt": None)
    assert pin.main(["--installed-only"], gh=no_network) == 1
    assert "RECEIPT PIN REFUSED:" in capsys.readouterr().out


# --- the workflows that install and compare ---------------------------------------


def _step(workflow: str, name: str) -> str:
    return workflow.split(f"      - name: {name}\n", 1)[1].split("\n      - ", 1)[0]


def test_the_resolver_installs_its_python_only_from_the_lock() -> None:
    workflow = RESOLVER_WORKFLOW.read_text()
    install = _step(workflow, "Install the resolver's Python runtime from uv.lock")
    assert install.strip() == "uses: ./.github/actions/install-resolver-python"
    names = [
        line.strip()[len("- name: ") :]
        for line in workflow.splitlines()
        if line.strip().startswith("- name: ")
    ]
    assert names.index(
        "Install the resolver's Python runtime from uv.lock"
    ) < names.index("Resolve pending cells against official prints")
    # No literal pins left: every Python package comes through the lock.
    assert not re.search(r"pip install", workflow)
    assert not re.search(r"\b(receipt|xlrd|pypdf|playwright)==", workflow)


def test_the_install_action_exports_the_lock_and_requires_hashes() -> None:
    action = INSTALL_ACTION.read_text()
    assert "uses: astral-sh/setup-uv@" in action
    assert re.search(
        r"uv export --locked --no-dev --no-emit-project \\\n\s+--extra resolver "
        r"--extra custody \\\n\s+--format requirements-txt",
        action,
    )
    assert 'uv venv --python "$(command -v python3)" "$venv"' in action
    assert "--system-site-packages" not in action
    assert re.search(
        r"uv pip install --python \"\$venv/bin/python\" --require-hashes", action
    )
    assert 'echo "$venv/bin" >> "$GITHUB_PATH"' in action


def test_the_lock_export_pins_and_hashes_everything_the_resolver_imports(
    tmp_path: pathlib.Path,
) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not on PATH")
    command = re.search(
        r"uv export (.+?)--output-file", INSTALL_ACTION.read_text(), flags=re.DOTALL
    )
    assert command is not None
    arguments = command.group(1).replace("\\\n", " ").split()
    out = tmp_path / "resolver-requirements.txt"
    subprocess.run(
        [uv, "export", "--offline", *arguments, "--output-file", str(out)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    requirements: dict[str, tuple[str, int]] = {}
    for block in re.split(r"\n(?=\S)", out.read_text()):
        head = block.split("\n", 1)[0]
        if head.startswith("#") or not head.strip():
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)==([^ ;\\]+)", head)
        assert match, f"unpinned requirement in the export: {head}"
        requirements[match.group(1).lower()] = (
            match.group(2),
            len(re.findall(r"--hash=sha256:[0-9a-f]{64}", block)),
        )
    assert {"receipt", "cryptography", "xlrd", "pypdf", "playwright"} <= set(
        requirements
    )
    assert all(count > 0 for _version, count in requirements.values())
    assert requirements["receipt"][0] == _thesis().version


def test_ci_runs_the_same_install_on_every_pull_request() -> None:
    ci = CI_WORKFLOW.read_text()
    job = ci.split("\n  resolver-runtime:\n", 1)[1].split("\n  # ", 1)[0]
    assert "uses: ./.github/actions/install-resolver-python" in job
    assert "python3 scripts/chronicle_receipt_pin.py --installed-only" in job
    assert "import resolve_pending" in job and "receipt.release_chain" in job


def test_the_resolvers_failure_issue_carries_a_receipt_refusal() -> None:
    alert = _step(RESOLVER_WORKFLOW.read_text(), "Alert on failure")
    assert "grep -m1 '^RECEIPT PIN REFUSED: ' /tmp/resolve-out.log" in alert
    assert 'gh issue create --title "$title" --body "$body"' in alert
    assert 'title="Resolution loop failed $(date -u +%F)"' in alert


def test_the_drift_monitor_compares_on_a_schedule_and_on_lock_changes() -> None:
    workflow = DRIFT_WORKFLOW.read_text()
    assert re.search(r'- cron: "[^"]+"', workflow)
    for path in ("pyproject.toml", "uv.lock", "scripts/chronicle_receipt_pin.py"):
        assert f"      - {path}\n" in workflow
    compare = _step(workflow, "Compare thesis's receipt with Chronicle's ledger branch")
    assert (
        'python3 scripts/chronicle_receipt_pin.py | tee "$RUNNER_TEMP/receipt-pin.txt"'
        in compare
    )
    assert "GH_TOKEN: ${{ github.token }}" in compare
    opener = _step(workflow, "Open a drift issue")
    # Only a real disagreement (exit 1) opens an issue; an unreadable
    # Chronicle (exit 2) just fails the run.
    assert "steps.compare.outputs.rc == '1'" in opener
    assert "github.event_name != 'pull_request'" in opener
    closer = _step(workflow, "Close a drift issue once the locks agree")
    assert "if: success() && github.event_name != 'pull_request'" in closer
    assert "permissions:\n  contents: read\n  issues: write\n" in workflow
