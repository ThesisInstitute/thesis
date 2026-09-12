"""The moved verifier keeps its legacy module names, identity and CLI.

``scripts/verify_record_chain.py`` and ``scripts/producer_signing_pins.py``
now hold the implementation only by reference.  Every property the existing
callers depend on is asserted here, because breaking one of them breaks a
scheduled publisher or silently disables a test's monkeypatch rather than
failing loudly.
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from thesis_core import producer_signing_pins, record_chain, tsa

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def _clean_environment():
    """A child environment with no PYTHONPATH and no inherited import hooks."""

    return {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME"}
    }


def _run(arguments, *, cwd, isolated=False):
    command = [sys.executable]
    if isolated:
        # ``-S`` drops site-packages, so an installed distribution cannot
        # satisfy the import; the shim must bootstrap the checkout itself.
        command += ["-S", "-E"]
    command += [str(argument) for argument in arguments]
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=_clean_environment(),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


@pytest.fixture
def legacy_scripts_on_path(monkeypatch):
    """Import the shims the way every existing caller imports them."""

    monkeypatch.syspath_prepend(str(SCRIPTS))
    for name in ("verify_record_chain", "producer_signing_pins"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    yield


def test_legacy_names_alias_the_package_modules(legacy_scripts_on_path):
    import producer_signing_pins as legacy_pins
    import verify_record_chain as legacy_chain

    # Identity, not equality: the publisher scripts import private helpers
    # from these names and the suite patches module attributes on them.
    assert legacy_chain is record_chain
    assert legacy_pins is producer_signing_pins


def test_patching_a_legacy_attribute_is_visible_to_the_package(
    legacy_scripts_on_path, monkeypatch
):
    import producer_signing_pins as legacy_pins
    import verify_record_chain as legacy_chain

    monkeypatch.setattr(legacy_pins, "PRODUCER_SPKI_SHA256", None)
    monkeypatch.setattr(legacy_pins, "ACTIVATION_SNAPSHOT", None)
    assert producer_signing_pins.PRODUCER_SPKI_SHA256 is None
    assert producer_signing_pins.producer_signing_active() is False

    monkeypatch.setattr(legacy_chain, "CODE_PINNED_TRUST_BUNDLES", {})
    assert record_chain.CODE_PINNED_TRUST_BUNDLES == {}
    # The verifier reads the pin through the module global, so the patch
    # reaches the code path the tests actually exercise.
    with pytest.raises(record_chain.ChainError, match="not independently pinned"):
        record_chain._load_trust_bundle(
            ROOT / "records", {"path": tsa.TRUST_BUNDLE_LOGICAL_PATH}
        )


def test_the_legacy_surface_still_exports_every_imported_name(
    legacy_scripts_on_path,
):
    import verify_record_chain as legacy_chain

    # Exactly the names scripts/witness_snapshot.py, sign_record_snapshot.py,
    # record_forecast_snapshot.py, witnessed_timeline.py,
    # build_genesis_enumeration.py and tests/ import today.
    expected = {
        "ChainError",
        "ChainVerification",
        "TokenEvidence",
        "WitnessEvidence",
        "_certificate_identity",
        "_load_trust_bundle",
        "_run_openssl",
        "_select_anchor",
        "_supplemental_candidates",
        "_trust_bundle_updates",
        "CODE_PINNED_GENESIS_ENUMERATIONS",
        "CODE_PINNED_TRUST_BUNDLES",
        "CODE_PINNED_TSA_IDENTITIES",
        "load_json",
        "logical_path",
        "physical_path",
        "preferred_active_trust_bundle",
        "producer_signature_path",
        "sha256_file",
        "trust_bundle_updates_for_snapshot",
        "validate_token_time",
        "verify_chain",
        "verify_records",
        "verify_timestamp_token",
        "verify_witness",
        "main",
    }
    missing = sorted(name for name in expected if not hasattr(legacy_chain, name))
    assert missing == []


def test_direct_cli_invocation_from_the_checkout(tmp_path):
    completed = _run(
        [SCRIPTS / "verify_record_chain.py", tmp_path / "absent"], cwd=ROOT
    )
    assert completed.returncode == 1, completed.stderr
    assert "CHAIN BROKEN: missing chain genesis" in completed.stderr


def test_absolute_script_path_from_an_unrelated_directory(tmp_path):
    completed = _run([SCRIPTS / "verify_record_chain.py", "absent"], cwd=tmp_path)
    assert completed.returncode == 1, completed.stderr
    assert "CHAIN BROKEN: missing chain genesis" in completed.stderr
    assert str(tmp_path) in completed.stderr


def test_absolute_script_path_without_any_installation(tmp_path):
    """The shim bootstraps the checkout when nothing is installed."""

    completed = _run(
        [SCRIPTS / "verify_record_chain.py", "absent"], cwd=tmp_path, isolated=True
    )
    assert completed.returncode == 1, completed.stderr
    assert "CHAIN BROKEN: missing chain genesis" in completed.stderr


def test_scripts_directory_import_without_pythonpath(tmp_path):
    """The invocation the custody-only CI job performs, asserted here too."""

    program = (
        "import sys;"
        "sys.path.insert(0, sys.argv[1]);"
        "import producer_signing_pins, verify_record_chain;"
        "assert callable(verify_record_chain.verify_chain);"
        "assert callable(producer_signing_pins.producer_signing_active);"
        "import thesis_core.record_chain as core;"
        "assert verify_record_chain is core;"
        "print('ok')"
    )
    completed = _run(["-c", program, SCRIPTS], cwd=tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"


def test_canonical_shim_preserves_an_importable_installed_package(tmp_path):
    installed = tmp_path / "installed"
    package = installed / "thesis_core"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "canonical.py").write_text("SOURCE = 'installed'\n")
    program = (
        "import sys;"
        "sys.path[:0] = sys.argv[1:];"
        "import canonical_json;"
        "import thesis_core.canonical as core;"
        "assert canonical_json is core;"
        "assert core.SOURCE == 'installed'"
    )
    completed = _run(["-c", program, installed, SCRIPTS], cwd=tmp_path, isolated=True)
    assert completed.returncode == 0, completed.stderr


def test_shared_modules_import_no_optional_dependency(tmp_path):
    """The pure modules stay usable in a custody-only environment.

    ``receipt`` is imported lazily inside producer-signature verification and
    the core extra's packages must not be pulled in at import time, or the
    scheduled ``--extra custody`` publishers break.
    """

    program = (
        "import sys;"
        "import thesis_core.record_chain, thesis_core.tsa, "
        "thesis_core.producer_signing_pins;"
        "leaked = sorted(name for name in "
        "('pydantic', 'psycopg', 'fastapi', 'uvicorn', 'receipt') "
        "if name in sys.modules);"
        "print(leaked)"
    )
    completed = _run(["-c", program], cwd=tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "[]"


def test_moved_modules_are_not_duplicated_in_scripts():
    """The scripts hold a reference, not a second copy of the implementation."""

    for name in ("verify_record_chain.py", "producer_signing_pins.py"):
        source = (SCRIPTS / name).read_text()
        assert "sys.modules[__name__]" in source
        assert len(source.splitlines()) < 40, name
    assert "def verify_chain(" not in (SCRIPTS / "verify_record_chain.py").read_text()
    assert "SIGNATURE_DOMAIN" not in (SCRIPTS / "producer_signing_pins.py").read_text()


def test_packaged_trust_assets_are_byte_identical_to_the_records_tree():
    published = ROOT / "records" / "trust"
    packaged = sorted(
        path.name for path in tsa.TRUST_ASSET_DIR.iterdir() if path.suffix != ".md"
    )
    assert packaged, "the distribution must carry the public trust assets"
    for name in packaged:
        assert (packaged_bytes := (tsa.TRUST_ASSET_DIR / name).read_bytes()) == (
            published / name
        ).read_bytes(), name
        assert hashlib.sha256(packaged_bytes).hexdigest()


def test_packaged_bundle_matches_the_verifier_code_pin():
    reference = tsa.trust_bundle_reference()
    raw = (tsa.TRUST_ASSET_DIR / Path(reference["path"]).name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == reference["sha256"]
    assert len(raw) == reference["size"]
    assert reference == record_chain.CODE_PINNED_TRUST_BUNDLES[reference["path"]]


def test_shipped_trust_configuration_names_only_the_real_anchors():
    """No synthetic root ever ships as trusted configuration."""

    assert tsa.anchor_ids() == ("freetsa-root-2016", "digicert-trusted-root-g4")
    assert {
        candidate["endpoint"]: candidate["rootCertificate"]["path"]
        for candidate in (tsa.anchor(name) for name in tsa.anchor_ids())
    } == {
        "https://freetsa.org/tsr": "records/trust/freetsa-root-2016.pem",
        "http://timestamp.digicert.com": "records/trust/digicert-trusted-root-g4.pem",
    }
    packaged = {path.name for path in tsa.TRUST_ASSET_DIR.iterdir()}
    assert not {name for name in packaged if "synthetic" in name or "test" in name}
