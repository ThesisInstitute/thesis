#!/usr/bin/env python3
"""Report TSA anchors that did not witness one recorded snapshot.

One available anchor is enough for a snapshot to count as witnessed, so a TSA
that stops verifying does not stop the recorder. DigiCert's responder
rotation halved the witnessing that way from 2026-09-04, and nobody saw it
until 2026-09-19. The recorder workflow runs this after every push and keeps
one issue open while any anchor is unavailable.

Two other states are reported the same way. A marker whose own status is
unavailable means no anchor witnessed, so the snapshot has no external time
proof at all. A failed supplemental outcome means a pending trust bundle's new
anchor was asked for a token and did not produce a verified one; that never
blocks activation, so it would otherwise go unseen until the next run.

Exit status: 0 when every anchor witnessed and no probe failed, 3 otherwise.
The report goes to stdout in both cases. It reads the marker the witness
writer already verified; it is a notice, not a trust decision.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEGRADED_EXIT_STATUS = 3
ROTATION_REASON = "token signer is not pinned"
ROTATION_RUNBOOK = "docs/tsa-trust-bundle-rotation.md"


def degraded_outcomes(marker: dict[str, Any]) -> list[dict[str, Any]]:
    outcomes = marker.get("anchorOutcomes")
    if not isinstance(outcomes, list) or not outcomes:
        raise ValueError("witness marker has no anchorOutcomes")
    return [outcome for outcome in outcomes if outcome.get("status") != "available"]


def failed_probes(marker: dict[str, Any]) -> list[dict[str, Any]]:
    """Supplemental outcomes (a pending bundle's new anchors) that failed."""

    outcomes = marker.get("supplementalOutcomes", [])
    if not isinstance(outcomes, list):
        raise ValueError("witness marker supplementalOutcomes is not a list")
    return [outcome for outcome in outcomes if outcome.get("status") != "available"]


def _outcome_line(outcome: dict[str, Any], *, bundle: bool = False) -> str:
    where = f" under `{outcome.get('trustBundleId')}`" if bundle else ""
    return (
        f"- `{outcome.get('tsaAnchorId')}` ({outcome.get('tsa')}){where}: "
        f"{outcome.get('reason', 'no reason recorded')}"
    )


def report(digest: Path, marker: dict[str, Any]) -> tuple[bool, str]:
    """Return (degraded, text) for one snapshot's witness marker."""

    degraded = degraded_outcomes(marker)
    probes = failed_probes(marker)
    total = len(marker["anchorOutcomes"])
    snapshot = digest.as_posix()
    if not degraded and not probes:
        return False, f"All {total} TSA anchors witnessed `{snapshot}`."
    bundle = marker.get("trustBundleId")
    if marker.get("status") != "available":
        lines = [
            f"No TSA anchor witnessed `{snapshot}` (bundle `{bundle}`). The "
            "snapshot is in the chain with no external time proof, and a "
            "pending trust bundle stays pending until a later snapshot is "
            "witnessed.",
            "",
        ]
    elif degraded:
        lines = [
            f"{len(degraded)} of {total} TSA anchors did not witness "
            f"`{snapshot}` (marker status `{marker.get('status')}`, bundle "
            f"`{bundle}`).",
            "",
        ]
    else:
        lines = [
            f"All {total} TSA anchors witnessed `{snapshot}` under `{bundle}`, "
            "but a pending trust bundle's new anchor did not produce a "
            "verified token.",
            "",
        ]
    lines.extend(_outcome_line(outcome) for outcome in degraded)
    if probes:
        if degraded:
            lines.append("")
        lines.append(
            "Probes of a pending trust bundle (these never authorize a "
            "snapshot, and a failed one does not stop the bundle activating):"
        )
        lines.extend(_outcome_line(outcome, bundle=True) for outcome in probes)
    lines.append("")
    reasons = [str(outcome.get("reason")) for outcome in (*degraded, *probes)]
    if any(ROTATION_REASON in reason for reason in reasons):
        lines.append(
            "A TSA has replaced its responder certificate. Restoring that "
            f"anchor needs a new trust bundle: follow `{ROTATION_RUNBOOK}`."
        )
    else:
        lines.append(
            "If this repeats, check the endpoint by hand before assuming an "
            f"outage; `{ROTATION_RUNBOOK}` lists the checks."
        )
    lines.append(
        "This issue closes itself on the first recorder run where every anchor "
        "witnesses and no probe fails."
    )
    return True, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--digest", type=Path, required=True)
    args = parser.parse_args()
    marker_path = args.digest.with_suffix(".witness.json")
    try:
        marker = json.loads(marker_path.read_text())
        degraded, text = report(args.digest, marker)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot read witness marker {marker_path}: {exc}") from exc
    print(text)
    return DEGRADED_EXIT_STATUS if degraded else 0


if __name__ == "__main__":
    raise SystemExit(main())
