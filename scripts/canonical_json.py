"""Compatibility entry point for the shared canonical serializer."""

import importlib.util
import sys
from pathlib import Path

if importlib.util.find_spec("thesis_core") is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from thesis_core import canonical as _implementation  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(_implementation.main())
sys.modules[__name__] = _implementation
