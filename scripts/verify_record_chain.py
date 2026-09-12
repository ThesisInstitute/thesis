#!/usr/bin/env python3
"""Compatibility shim for the moved record-chain verifier.

The implementation now lives in :mod:`thesis_core.record_chain`.  This module
rebinds itself in :data:`sys.modules` to that module object rather than
re-exporting its names: the publisher scripts import private helpers from it
and the test suite patches module *attributes* (``CODE_PINNED_TRUST_BUNDLES``,
``CODE_PINNED_TSA_IDENTITIES``, ``CODE_PINNED_GENESIS_ENUMERATIONS``), so
there must be exactly one module object behind both names.

The scheduled publishers invoke this file directly
(``python scripts/verify_record_chain.py records``), including by absolute
path from an unrelated working directory, so it bootstraps the checkout root
when ``thesis_core`` is not already importable.  An installed distribution
keeps winning, so packaged resources resolve normally.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

if importlib.util.find_spec("thesis_core") is None:  # bare checkout, no install
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from thesis_core import record_chain as _record_chain  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_record_chain.main())

sys.modules[__name__] = _record_chain
