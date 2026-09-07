#!/usr/bin/env python3
"""Compatibility shim for the moved producer-signing pins.

The implementation now lives in :mod:`thesis_core.producer_signing_pins`.
This module rebinds itself in :data:`sys.modules` to that module object
instead of re-exporting its names, because callers and tests patch module
*attributes* (``PRODUCER_SPKI_SHA256``, ``ACTIVATION_SNAPSHOT``) and expect
the patch to be visible to every other importer, including
``thesis_core.record_chain``.  Re-exported copies would silently break that.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

if importlib.util.find_spec("thesis_core") is None:  # bare checkout, no install
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from thesis_core import producer_signing_pins as _producer_signing_pins  # noqa: E402

sys.modules[__name__] = _producer_signing_pins
