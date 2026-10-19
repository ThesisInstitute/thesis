"""Published Thesis forecasts: runs, registration witness times, and CDFs.

Runs come from the attested published-log projection committed under
``records/<day>/bodies-*/log`` at a git ref. Registration times come from the
RFC 3161 witnessed timeline committed at the same ref. Distributions come from
the published target-architecture table ``forecastDistributions`` on the live
site, verified chunk by chunk against its manifest.
"""

from __future__ import annotations

import bisect
import dataclasses
import gzip
import hashlib
import json
import pathlib
import re
import subprocess
import sys
from typing import Any

from .fetch import FetchCache

SCRIPTS = pathlib.Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from canonical_json import canonical_bytes  # noqa: E402

SITE = "https://app.thesisinstitute.org"
BODY_LOG = re.compile(
    r"^records/(?P<day>\d{4}-\d{2}-\d{2})/bodies-(?P<run>\d+)-(?P<attempt>\d+)/log\.json\.gz$"
)
SCOPE_START = "2026-07-01T00:00:00Z"


class ThesisDataError(ValueError):
    pass


def git(repo: pathlib.Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True
    ).stdout


def resolve_ref(repo: pathlib.Path, ref: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()


def show(repo: pathlib.Path, commit: str, path: str) -> bytes:
    return git(repo, "show", f"{commit}:{path}")


def latest_log_body(repo: pathlib.Path, commit: str) -> str:
    """The newest attested log body directory at ``commit``."""
    names = git(repo, "ls-tree", "-r", "--name-only", commit, "records/").decode()
    bodies = []
    for name in names.splitlines():
        match = BODY_LOG.match(name)
        if match:
            bodies.append(
                (
                    match["day"],
                    int(match["run"]),
                    int(match["attempt"]),
                    name.rsplit("/", 1)[0],
                )
            )
    if not bodies:
        raise ThesisDataError(f"no published log body under records/ at {commit}")
    return max(bodies)[3]


def load_log_collection(
    repo: pathlib.Path, commit: str, body_dir: str, collection: str
) -> list[dict]:
    """Rows of one log collection, each chunk checked against its manifest."""
    manifest = json.loads(
        gzip.decompress(show(repo, commit, f"{body_dir}/log.json.gz"))
    )
    rows: list[dict] = []
    for chunk in manifest["collections"][collection]["chunks"]:
        path = f"{body_dir}/log/{collection}/{chunk['index']}.json.gz"
        payload = json.loads(gzip.decompress(show(repo, commit, path)))
        digest = hashlib.sha256(canonical_bytes(payload)).hexdigest()
        if digest != chunk["sha256"]:
            raise ThesisDataError(f"{path} does not match its manifest hash")
        rows.extend(payload["rows"])
    expected = manifest["collections"][collection]["count"]
    if len(rows) != expected:
        raise ThesisDataError(
            f"{collection}: {len(rows)} rows, manifest says {expected}"
        )
    return rows


@dataclasses.dataclass(frozen=True)
class Registration:
    at: str
    coverage: str  # custody_root | run_directory | claimed_only
    witness_digest: str | None
    headline_eligible: bool | None


def registration_for(entry: dict, timeline: dict) -> Registration:
    root = entry.get("custodyRootSha256")
    proof = timeline.get("custodyRoots", {}).get(root) if root else None
    if proof:
        return Registration(
            proof["earliestWitnessedAt"],
            "custody_root",
            proof.get("witnessDigest"),
            proof.get("headlineEligible"),
        )
    run_dir = run_directory(entry)
    proof = timeline.get("runs", {}).get(run_dir) if run_dir else None
    if proof:
        return Registration(
            proof["earliestWitnessedAt"],
            "run_directory",
            proof.get("witnessDigest"),
            None,
        )
    return Registration(entry["recordedAt"], "claimed_only", None, None)


def run_directory(entry: dict) -> str | None:
    for artifact in entry.get("activityLog") or []:
        parts = artifact.get("path", "").split("/")
        if len(parts) >= 4 and parts[0] == "records":
            return "/".join(parts[:4])
    return None


@dataclasses.dataclass
class ThesisRun:
    run_id: str
    slug: str
    data_point_id: str
    label: str
    agent: str
    model: str | None
    recorded_at: str
    registration: Registration
    unit: str
    point: float
    ci_low: float
    ci_high: float
    provenance: str
    transform_version: str
    resolution_date: str | None
    cdf: list[tuple[float, float]] | None = None
    cdf_check: str | None = None

    @property
    def forecaster(self) -> str:
        """Primary/secondary role label used in the outputs."""
        if self.agent == "brier.time_series_prior":
            return "persistence_baseline"
        if self.agent == "thesis.analyst" and self.label == "Headline":
            return "thesis_headline"
        return f"thesis_variant:{self.agent}:{self.label}"


def published_runs(entries: list[dict], timeline: dict) -> list[ThesisRun]:
    runs = []
    for entry in entries:
        if entry.get("kind") != "prediction_recorded":
            continue
        distribution = entry.get("distribution") or {}
        interval = entry.get("interval80") or {}
        runs.append(
            ThesisRun(
                run_id=entry["runId"],
                slug=entry["forecastSlug"],
                data_point_id=entry.get("dataPointId") or "",
                label=entry.get("runLabel") or "",
                agent=entry.get("agent") or "",
                model=entry.get("model"),
                recorded_at=entry["recordedAt"],
                registration=registration_for(entry, timeline),
                unit=entry.get("unit") or "",
                point=float(entry["pointEstimate"]),
                ci_low=float(interval["lower"]),
                ci_high=float(interval["upper"]),
                provenance=distribution.get("provenance") or "",
                transform_version=distribution.get("transformVersion") or "",
                resolution_date=entry.get("resolutionDate"),
            )
        )
    return runs


def load_distributions(
    cache: FetchCache, run_ids: set[str], *, site: str = SITE
) -> tuple[dict[str, list[tuple[float, float]]], dict]:
    """Published 201-point CDFs for ``run_ids``, verified against the manifest."""
    manifest = cache.get_json(f"{site}/targets/forecastDistributions/manifest.json")
    found: dict[str, list[tuple[int, float, float]]] = {}
    for chunk in manifest["chunks"]:
        url = f"{site}/targets/forecastDistributions/{chunk['index']}.json"
        payload = cache.get_json(url)
        unrooted = {k: v for k, v in payload.items() if k != "projectionRootSha256"}
        digest = hashlib.sha256(canonical_bytes(unrooted)).hexdigest()
        if digest != chunk["sha256"]:
            raise ThesisDataError(f"{url} does not match its manifest hash")
        for row in payload["rows"]:
            if row["runId"] in run_ids:
                found.setdefault(row["runId"], []).append(
                    (row["pointIndex"], float(row["value"]), float(row["probability"]))
                )
    cdfs = {}
    for run_id, rows in found.items():
        rows.sort()
        if [r[0] for r in rows] != list(range(len(rows))) or len(rows) != 201:
            raise ThesisDataError(f"{run_id}: published CDF is not 201 indexed points")
        points = [(value, probability) for _, value, probability in rows]
        validate_cdf(run_id, points)
        cdfs[run_id] = points
    meta = {
        "manifestUrl": f"{site}/targets/forecastDistributions/manifest.json",
        "manifestSha256": cache.sha256_of(
            f"{site}/targets/forecastDistributions/manifest.json"
        ),
        "projectionRootSha256": manifest.get("projectionRootSha256"),
        "tableSha256": manifest.get("sha256"),
    }
    return cdfs, meta


def validate_cdf(run_id: str, points: list[tuple[float, float]]) -> None:
    values = [v for v, _ in points]
    probabilities = [p for _, p in points]
    if any(b <= a for a, b in zip(values, values[1:])):
        raise ThesisDataError(f"{run_id}: CDF values are not strictly increasing")
    if any(b < a for a, b in zip(probabilities, probabilities[1:])):
        raise ThesisDataError(f"{run_id}: CDF probabilities decrease")
    if probabilities[0] != 0.0 or probabilities[-1] != 1.0:
        raise ThesisDataError(f"{run_id}: CDF does not run from 0 to 1")


def cdf_at(points: list[tuple[float, float]], x: float) -> float:
    """Linear interpolation between published points; 0 below, 1 above."""
    values = [v for v, _ in points]
    if x <= values[0]:
        return points[0][1]
    if x >= values[-1]:
        return points[-1][1]
    index = bisect.bisect_right(values, x)
    (v0, p0), (v1, p1) = points[index - 1], points[index]
    return p0 + (x - v0) / (v1 - v0) * (p1 - p0)


def rebuild_check(run: ThesisRun) -> str:
    """Differential check of a published CDF against the documented transform."""
    if run.cdf is None:
        return "missing"
    if run.provenance != "interval_seeded":
        # Agent-reported (ladder) CDFs are rebuilt from quantiles the log does
        # not carry; check the knots the summary does carry instead.
        lo, mid, hi = (cdf_at(run.cdf, x) for x in (run.ci_low, run.point, run.ci_high))
        ok = abs(lo - 0.1) < 0.02 and abs(mid - 0.5) < 0.02 and abs(hi - 0.9) < 0.02
        return (
            "summary_knots_match"
            if ok
            else f"summary_knots_differ:{lo:.3f},{mid:.3f},{hi:.3f}"
        )
    from run_thesis_analyst import interval_distribution

    rebuilt = interval_distribution(
        {"pointEstimate": run.point, "ciLow": run.ci_low, "ciHigh": run.ci_high}
    )["points"]
    pairs = [(p["value"], p["probability"]) for p in rebuilt]
    if pairs == run.cdf:
        return "rebuilt_exact"
    worst = max(max(abs(a[0] - b[0]), abs(a[1] - b[1])) for a, b in zip(pairs, run.cdf))
    return "rebuilt_within_1e-9" if worst < 1e-9 else f"rebuilt_differs:{worst:.3g}"


def resolution_status(repo: pathlib.Path, commit: str) -> dict[str, dict]:
    payload = json.loads(show(repo, commit, "site/src/data/resolution-status.json"))
    return {
        "asOf": payload.get("asOf"),
        "generatedAtUtc": payload.get("generatedAtUtc"),
        "targets": payload.get("targets", {}),
    }


def resolution_events(entries: list[dict]) -> dict[str, dict]:
    """dataPointId -> the published resolution entry, if Thesis resolved it."""
    out = {}
    for entry in entries:
        if entry.get("kind") == "prediction_resolved":
            data_point = entry.get("dataPointId") or entry.get("ledgerFactRef")
            if data_point:
                out[data_point] = entry
    return out


SLUG_FIELD = re.compile(r'"slug":\s*"([^"]+)"')
DATA_POINT_FIELD = re.compile(r'"dataPointId":\s*"([^"]+)"')
RUN_AT_FIELD = re.compile(r'"runAt":\s*"([^"]+)"')


def catalog_cells(repo: pathlib.Path, commit: str) -> list[dict[str, Any]]:
    """(slug, dataPointId, runAt) triples scanned from generated catalog modules.

    A text scan, used only to list catalog cells the publication gate keeps
    off the site; it never feeds a score.
    """
    names = git(
        repo, "ls-tree", "-r", "--name-only", commit, "site/src/data/forecast-examples/"
    ).decode()
    cells = []
    for name in names.splitlines():
        if not name.endswith(".ts"):
            continue
        text = show(repo, commit, name).decode("utf-8", "replace")
        starts = [m.start() for m in SLUG_FIELD.finditer(text)] + [len(text)]
        for begin, end in zip(starts, starts[1:]):
            block = text[begin:end]
            slug = SLUG_FIELD.match(block)
            data_point = DATA_POINT_FIELD.search(block)
            run_ats = RUN_AT_FIELD.findall(block)
            if slug and data_point:
                cells.append(
                    {
                        "file": name,
                        "slug": slug.group(1),
                        "dataPointId": data_point.group(1),
                        "runAts": sorted(set(run_ats)),
                    }
                )
    return cells
