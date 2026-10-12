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
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

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
        r"uv pip install --python \"\$venv/bin/python\" --require-hashes \\\n"
        r"\s+--no-cache --no-build --requirements",
        action,
    )
    assert 'echo "$venv/bin" >> "$GITHUB_PATH"' in action
    # A restored cache could hand uv an artifact it does not re-hash; a
    # floating uv could change what --require-hashes means.
    setup = yaml.safe_load(action)["runs"]["steps"][0]
    assert setup["uses"].startswith("astral-sh/setup-uv@")
    assert setup["with"]["enable-cache"] is False
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", setup["with"]["version"])
    # The exported hash list stays out of the log.
    assert '--output-file "$requirements" > /dev/null' in action


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
    smoke = re.search(r'python3 -c "import ([^"]+)"', job)
    assert smoke is not None
    imported = {name.strip() for name in smoke.group(1).split(",")}
    # Every script the resolution run starts, and the attest action, is
    # imported in the smoke, so an undeclared import fails a pull request.
    started = set(
        re.findall(
            r"python3 (?:-u )?scripts/([a-z_]+)\.py",
            RESOLVER_WORKFLOW.read_text()
            + (ROOT / ".github/actions/attest-records-push/action.yml").read_text(),
        )
    )
    assert started and started <= imported, started - imported
    assert {"receipt.release_chain", "receipt.sign", "cryptography"} <= imported


def test_a_receipt_refusal_is_published_then_failed_like_refused_rows() -> None:
    # Exit 4 stops capture, not publishing: the ledger may have moved
    # upstream, and the pin/witness/deploy steps never run Chronicle's code.
    workflow = RESOLVER_WORKFLOW.read_text()
    resolve = _step(workflow, "Resolve pending cells against official prints")
    assert '[ "$resolver_rc" -ne 3 ]' in resolve
    assert '[ "$resolver_rc" -ne 4 ]' in resolve
    assert 'echo "resolver_rc=$resolver_rc" >> "$GITHUB_OUTPUT"' in resolve
    gate = yaml.safe_load(workflow)["jobs"]["resolve"]["steps"]
    gate = next(
        step for step in gate if step.get("name") == "Fail the run on refused rows"
    )
    assert gate["if"] == (
        "steps.resolve.outputs.resolver_rc == '3' || "
        "steps.resolve.outputs.resolver_rc == '4'"
    )
    assert "exit 1" in gate["run"]


def test_ci_alerts_when_the_resolver_runtime_job_fails_on_main() -> None:
    needs = yaml.safe_load(CI_WORKFLOW.read_text())["jobs"]["alert-on-main-failure"][
        "needs"
    ]
    assert "resolver-runtime" in needs


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
    assert 'echo "rc=${PIPESTATUS[0]}" >> "$GITHUB_OUTPUT"' in compare
    assert "set -e" not in compare.replace("set -uo pipefail", "")
    assert "GH_TOKEN: ${{ github.token }}" in compare
    opener = _step(workflow, "Open a drift issue")
    # Only a real disagreement (exit 1) opens an issue; an unreadable
    # Chronicle (exit 2) just fails the run.
    assert (
        "if: steps.compare.outputs.rc == '1' && github.event_name != 'pull_request'"
        in opener
    )
    # The comparison's words reach the issue only inside a code block.
    assert "echo '```text'" in opener
    assert opener.index("echo '```text'") < opener.index(
        'cat "$RUNNER_TEMP/receipt-pin.txt"'
    )
    closer = _step(workflow, "Close a drift issue once the locks agree")
    assert (
        "if: steps.compare.outputs.rc == '0' && github.event_name != 'pull_request'"
        in closer
    )
    failer = _step(workflow, "Fail unless the locks agree")
    assert "RC: ${{ steps.compare.outputs.rc }}" in failer
    assert 'if [ "$RC" != "0" ]; then' in failer
    names = re.findall(r"^      - name: (.+)$", workflow, flags=re.MULTILINE)
    assert names[-1] == "Fail unless the locks agree"
    assert "permissions:\n  contents: read\n  issues: write\n" in workflow


# --- review of #304: inputs that once raised or slipped through ----------------


def test_a_deeply_nested_lock_is_refused_not_raised() -> None:
    # A 997-byte lock of arrays nested 496 deep raised RecursionError inside
    # tomllib on Python 3.12 and 3.14 (review finding 2).
    nested = b"x = " + b"[" * 496 + b"]" * 496 + b"\n"
    refusal = pin.receipt_pin_refusal(
        nested, chronicle_label=LABEL, thesis_lock=THESIS_LOCK
    )
    assert refusal == f"{LABEL} uv.lock nests too deeply to read"


@pytest.mark.parametrize(
    "version",
    ["0.6.2\n::error::injected", "", "latest", "0.6.2 ; rm", "v0.6.2", "1" * 80],
)
def test_a_version_that_is_not_one_is_refused_without_echoing_it(version) -> None:
    lock = _lock(
        f'[[package]]\nname = "receipt"\nversion = {json.dumps(version)}\n'
        f'wheels = [{{ url = "u", hash = "sha256:{"a" * 64}" }}]\n'
    )
    refusal = pin.receipt_pin_refusal(
        lock, chronicle_label=LABEL, thesis_lock=THESIS_LOCK
    )
    assert refusal is not None and "\n" not in refusal
    if version:
        assert "injected" not in refusal and "rm" not in refusal.split(LABEL)[1]


@pytest.mark.parametrize(
    "digest",
    ["md5:" + "a" * 32, "sha256:" + "A" * 64, "sha256:zz", "sha256:" + "a" * 63],
)
def test_an_artifact_hash_that_is_not_a_hex_digest_is_refused(digest) -> None:
    lock = _lock(_package("receipt", "0.6.2", digest))
    refusal = pin.receipt_pin_refusal(
        lock, chronicle_label=LABEL, thesis_lock=THESIS_LOCK
    )
    assert refusal == (
        f"{LABEL} uv.lock locks receipt 0.6.2 with an artifact hash that is not "
        "a hex digest"
    )


def test_installed_refusal_names_a_thesis_lock_without_receipt() -> None:
    bare = _lock(_package("xlrd", "2.0.1", "sha256:" + "f" * 64))
    assert pin.installed_refusal(bare, "0.6.2") == "thesis's uv.lock locks no receipt"


def test_installed_version_reads_a_distribution_other_than_the_locked_one(
    tmp_path: pathlib.Path, monkeypatch
) -> None:
    # A real distribution on the path, at a version no lock names: the check
    # must report it, not the locked version (review finding 3, mutant W2).
    dist = tmp_path / "receipt-0.0.1.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: receipt\nVersion: 0.0.1\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    assert pin.installed_version() == "0.0.1"
    refusal = pin.receipt_pin_refusal(
        THESIS_LOCK,
        chronicle_label=LABEL,
        thesis_lock=THESIS_LOCK,
        installed=pin.installed_version(),
    )
    assert refusal is not None and f"has receipt 0.0.1, but thesis and {LABEL}" in (
        refusal
    )


def test_fetch_lock_refuses_a_truncated_tree_listing() -> None:
    gh = FakeGitHub({"uv.lock": CHRONICLE_062.read_bytes()})
    listing = gh

    def truncated(*args: str) -> str:
        out = listing(*args)
        if "/git/trees/" in args[0]:
            body = json.loads(out)
            body["truncated"] = True
            return json.dumps(body)
        return out

    with pytest.raises(pin.ReceiptPinError, match="no complete root tree"):
        pin.fetch_lock("PolicyEngine/chronicle", "c" * 40, gh=truncated)


def test_fetch_lock_refuses_a_different_commit_than_it_asked_for() -> None:
    gh = FakeGitHub({"uv.lock": CHRONICLE_062.read_bytes()})

    def other_commit(*args: str) -> str:
        out = gh(*args)
        if "/git/commits/" in args[0]:
            body = json.loads(out)
            body["sha"] = "d" * 40
            return json.dumps(body)
        return out

    with pytest.raises(pin.ReceiptPinError, match=f"did not return commit {'c' * 40}"):
        pin.fetch_lock("PolicyEngine/chronicle", "c" * 40, gh=other_commit)


def test_cli_exits_2_not_1_when_the_comparison_itself_crashes(
    monkeypatch, capsys
) -> None:
    # Exit 1 opens a drift issue; a crash says nothing about drift.
    def boom(*args, **kwargs):
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(pin, "receipt_pin_refusal", boom)
    assert pin.main([], gh=FakeGitHub({"uv.lock": THESIS_LOCK})) == 2
    out = capsys.readouterr().out
    assert out == "cannot compare the receipt pins: RecursionError\n"


def test_one_line_removes_every_line_break() -> None:
    assert pin.one_line("a\r\nb\nc\rd") == "a  b c d"


def test_one_line_leaves_no_workflow_command_marker() -> None:
    # The runner reads ``::name::`` at a line's start and the legacy
    # ``##[name]`` anywhere in a line (round 2, finding 2).
    line = pin.one_line("x ##[warning]y ::error::z\n::notice::w")
    assert "##[" not in line and "::" not in line
    assert line == "x # #[warning]y : :error: :z : :notice: :w"


# --- review of #304, round 2 -----------------------------------------------------


def test_an_integer_past_pythons_digit_limit_is_refused_not_raised() -> None:
    # tomllib raises a plain ValueError (not TOMLDecodeError) for an integer
    # over 4300 digits; it escaped the parser's handler (round 2, finding 1).
    huge = b"x = " + b"1" * 5000 + b"\n"
    assert (
        pin.receipt_pin_refusal(huge, chronicle_label=LABEL, thesis_lock=THESIS_LOCK)
        == f"{LABEL} uv.lock is not a readable uv.lock (ValueError)"
    )


def test_a_parser_error_never_quotes_chronicles_text() -> None:
    key = '"##[warning]injected ::warning:: by Chronicle"'
    lock = f"[{key}]\n[{key}]\n".encode()
    refusal = pin.receipt_pin_refusal(
        lock, chronicle_label=LABEL, thesis_lock=THESIS_LOCK
    )
    assert refusal is not None
    assert "injected" not in refusal and "##[" not in refusal and "::" not in refusal
    assert re.fullmatch(
        re.escape(f"{LABEL} uv.lock is not a readable uv.lock (TOMLDecodeError")
        + r"( at line \d+, column \d+)?\)",
        refusal,
    )


def test_anything_unexpected_in_the_comparison_is_a_refusal(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise KeyError("##[warning]from somewhere")

    monkeypatch.setattr(pin, "_receipt_pin_refusal", boom)
    assert (
        pin.receipt_pin_refusal(
            THESIS_LOCK, chronicle_label=LABEL, thesis_lock=THESIS_LOCK
        )
        == f"cannot compare the receipt pins for {LABEL} (KeyError)"
    )


@pytest.mark.parametrize(
    "digest",
    ["sha256:" + "a" * 65, "sha384:" + "a" * 64, "sha512:" + "a" * 96],
)
def test_a_digest_of_the_wrong_length_for_its_algorithm_is_refused(digest) -> None:
    # Round 2, nit 5: the length must match the algorithm, in both locks.
    lock = _lock(_package("receipt", "0.6.2", digest))
    assert pin.receipt_pin_refusal(lock, chronicle_label=LABEL, thesis_lock=lock) == (
        f"{LABEL} uv.lock locks receipt 0.6.2 with an artifact hash that is not "
        "a hex digest"
    )


def test_an_installed_version_that_is_not_one_is_refused_without_echoing_it() -> None:
    refusal = pin.receipt_pin_refusal(
        THESIS_LOCK,
        chronicle_label=LABEL,
        thesis_lock=THESIS_LOCK,
        installed="0.6.2\n##[warning]x",
    )
    assert refusal is not None and "##[" not in refusal and "\n" not in refusal


# --- properties (Hypothesis) ----------------------------------------------------

_VERSIONS = st.from_regex(r"[0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2}", fullmatch=True)
_DIGESTS = st.from_regex(r"sha256:[0-9a-f]{64}", fullmatch=True)
_ARTIFACTS = st.frozensets(_DIGESTS, min_size=1, max_size=3)


@settings(max_examples=300, deadline=None)
@given(
    chronicle=st.tuples(_VERSIONS, _ARTIFACTS),
    thesis=st.tuples(_VERSIONS, _ARTIFACTS),
    installed=st.one_of(st.none(), _VERSIONS, st.just("unchecked")),
    same=st.booleans(),
)
def test_property_the_check_allows_only_identical_pins_and_the_locked_install(
    chronicle, thesis, installed, same
) -> None:
    if same:
        chronicle = thesis
    kwargs = {} if installed == "unchecked" else {"installed": installed}
    refusal = pin.receipt_pin_refusal(
        _lock(_package("receipt", chronicle[0], *sorted(chronicle[1]))),
        chronicle_label=LABEL,
        thesis_lock=_lock(_package("receipt", thesis[0], *sorted(thesis[1]))),
        **kwargs,
    )
    allowed = chronicle == thesis and installed in ("unchecked", thesis[0])
    assert (refusal is None) == allowed
    assert refusal is None or ("\n" not in refusal and "\r" not in refusal)


@settings(max_examples=300, deadline=None)
@given(st.binary(max_size=2048))
def test_property_any_chronicle_bytes_give_a_one_line_refusal_or_a_pass(raw) -> None:
    refusal = pin.receipt_pin_refusal(
        raw, chronicle_label=LABEL, thesis_lock=THESIS_LOCK
    )
    if refusal is None:
        assert pin.locked_pin(raw, label="raw") == _thesis()
    else:
        assert refusal and "\n" not in refusal and "\r" not in refusal
        printed = pin.one_line(f"RECEIPT PIN REFUSED: {refusal}")
        assert "##[" not in printed and "::" not in printed


_TOML_TOKENS = st.sampled_from(
    [
        "[[package]]\n",
        'name = "receipt"\n',
        'name = "Receipt"\n',
        'version = "0.6.2"\n',
        'version = ["0.6.2"]\n',
        "wheels = [",
        'sdist = { hash = "sha256:' + "a" * 64 + '" }\n',
        '{ hash = "sha256:' + "b" * 64 + '" },',
        "{ hash = 1 },",
        "]\n",
        "[",
        "]",
        "{",
        "}",
        '"',
        "=",
        ",",
        "\n",
        "#",
        "package = 3\n",
        '["##[warning]x ::error::y"]\n',
        "x = " + "9" * 4400 + "\n",
    ]
)


@settings(max_examples=300, deadline=None)
@given(st.lists(_TOML_TOKENS, max_size=40).map("".join))
def test_property_toml_shaped_text_never_raises(text) -> None:
    refusal = pin.receipt_pin_refusal(
        text.encode(), chronicle_label=LABEL, thesis_lock=THESIS_LOCK
    )
    assert refusal is None or isinstance(refusal, str)
    if refusal is not None:
        assert "##[" not in refusal and "\n" not in refusal
