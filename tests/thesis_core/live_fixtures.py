"""Synthetic future notices for operational tests, never live source evidence."""

import json
from datetime import date
from pathlib import Path

from thesis_core.adapters import HttpResponse

FIXTURES = Path(__file__).parents[1] / "fixtures"
PORTAL = FIXTURES / "core/statcan_cpi_portal_20260905.html"


def future_period():
    return f"{date.today().year + 1}-08"


def future_portal():
    year = int(future_period()[:4])
    weekday = date(year, 9, 14).strftime("%A")
    return (
        PORTAL.read_bytes()
        .replace(b"2026", str(year).encode())
        .replace(b"Monday, September 14", f"{weekday}, September 14".encode())
    )


def future_fetch(request):
    raw = (
        future_portal()
        if request.role == "release"
        else (FIXTURES / "international/statcan_cpi_v41690973.json").read_bytes()
    )
    return HttpResponse(raw, request.url)


def future_outcome(request):
    """Synthetic exact vintage lets a test exercise resolution today."""
    payload = json.loads(future_fetch(request).body)
    rows = payload[0]["object"]["vectorDataPoint"]
    year = int(future_period()[:4])
    template = rows[0]
    for y, value in ((year - 1, 170.0), (year, 175.1)):
        rows.append(
            dict(
                template,
                refPer=f"{y}-08-01",
                value=value,
                releaseTime=f"{y}-09-14T08:30",
            )
        )
    return HttpResponse(json.dumps(payload).encode(), request.url)
