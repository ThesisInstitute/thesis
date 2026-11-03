"""Tests for paper figure generation."""

import subprocess
import sys
from pathlib import Path

import pytest

# generate_figures rewrites paper/figures in place, so under xdist these tests
# share one worker: another worker's fixture could rewrite a PNG mid-read.
pytestmark = pytest.mark.xdist_group("paper_figures")

PAPER_DIR = Path(__file__).resolve().parent.parent / "paper"
FIG_DIR = PAPER_DIR / "figures"
GENERATE_SCRIPT = PAPER_DIR / "generate_figures.py"

EXPECTED_FIGURES = [
    "fig_protocol.png",
    "fig_update_magnitude.png",
    "fig_magnitude_distribution.png",
    "fig_probe_validation.png",
    "fig_forest_plot.png",
    "fig_convergence.png",
    "fig_sycophancy.png",
    "fig_sycophancy_direction.png",
]

MIN_FILE_SIZE = 10_000  # 10 KB


def _figures_are_stale() -> bool:
    """Check if any figure is missing or older than the generation script or data."""
    for filename in EXPECTED_FIGURES:
        fig_path = FIG_DIR / filename
        if not fig_path.exists():
            return True

    # Newest source: the generation script itself or any result JSON
    data_dirs = [
        PAPER_DIR.parent / "experiments" / "stability_results",
        PAPER_DIR.parent / "experiments" / "stability_validation" / "strongest",
    ]
    source_paths = [GENERATE_SCRIPT]
    for data_dir in data_dirs:
        if data_dir.exists():
            source_paths.extend(data_dir.rglob("*.json"))

    newest_source = max(p.stat().st_mtime for p in source_paths)
    oldest_figure = min(
        (FIG_DIR / f).stat().st_mtime for f in EXPECTED_FIGURES
    )
    return newest_source > oldest_figure


@pytest.fixture(scope="module", autouse=True)
def generate_figures():
    """Run generate_figures.py once before all tests in this module, if needed."""
    if not _figures_are_stale():
        return

    result = subprocess.run(
        [sys.executable, str(GENERATE_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"Figure generation failed:\n{result.stderr}"


@pytest.mark.parametrize("filename", EXPECTED_FIGURES)
def test_figure_exists(filename):
    path = FIG_DIR / filename
    assert path.exists(), f"Missing figure: {filename}"


@pytest.mark.parametrize("filename", EXPECTED_FIGURES)
def test_figure_min_size(filename):
    path = FIG_DIR / filename
    size = path.stat().st_size
    assert size > MIN_FILE_SIZE, (
        f"{filename} is only {size} bytes, expected >{MIN_FILE_SIZE}"
    )


def test_figure_is_valid_png():
    """Spot-check that files start with PNG magic bytes."""
    for filename in EXPECTED_FIGURES:
        path = FIG_DIR / filename
        with open(path, "rb") as f:
            header = f.read(8)
        assert header[:4] == b"\x89PNG", f"{filename} is not a valid PNG"
