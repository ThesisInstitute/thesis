import functools
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import chronicle_receipt_pin  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_records: verifies the real records tree under the committed "
        "armed producer-signing pins (no dormancy simulation)",
    )


@functools.cache
def _thesis_receipt_lock() -> tuple[bytes, str]:
    lock = (ROOT / "uv.lock").read_bytes()
    pin = chronicle_receipt_pin.locked_pin(lock, label="thesis's uv.lock")
    assert pin is not None, "thesis's uv.lock must lock receipt"
    return lock, pin.version


@pytest.fixture(autouse=True)
def _chronicle_locks_thesis_receipt(monkeypatch):
    """Give resolver tests a Chronicle that locks thesis's own receipt.

    ``resolve_pending.main`` reads Chronicle's ``uv.lock`` over the network
    before any capture work, and every append proposal compares the staged
    base's lock with this interpreter's receipt. Tests that drive either path
    for other reasons see a Chronicle that locks exactly thesis's receipt and
    an interpreter that has it; the comparison itself still runs. The
    receipt-pin tests override both stubs.
    """

    resolver = sys.modules.get("resolve_pending")
    if resolver is None:
        return
    lock, version = _thesis_receipt_lock()
    monkeypatch.setattr(resolver, "chronicle_receipt_lock", lambda *_args: lock)
    monkeypatch.setattr(resolver, "installed_receipt_version", lambda: version)
