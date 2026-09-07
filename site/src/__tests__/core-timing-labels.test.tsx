// The two timing disclosures on an experiment or run row are separate facts:
// the declared scheduling cutoff is a preregistration commitment, and the
// effective information boundary is the bundle freeze acknowledgement actually
// recorded. This file pins that they are labelled distinctly, that neither
// stands in for the other when one is missing, and that the prospective
// ordering rule is applied only to prospective rows.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { CoreExperimentView } from "@/app/core/CoreExperimentView";
import {
  DECLARED_CUTOFF_LABEL,
  EFFECTIVE_BOUNDARY_LABEL,
  NOT_REPORTED,
} from "@/app/core/core-display";

const EXPERIMENT_ID = "4d".repeat(32);

const DECLARED = "2026-09-04T12:00:00Z";
const FROZEN_EARLIER = "2026-09-02T09:30:00Z";
const HISTORICAL_CUTOFF = "2024-01-31T12:00:00Z";
const ASSEMBLED_LATER = "2026-09-03T08:00:00Z";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

/**
 * Renders one experiment row. `thesis_core/api.py` projects mode and the two
 * timing fields as siblings of `payload`, so `summary` is the primary source
 * and `payload` the fallback.
 */
function renderWithExperimentRow({
  summary = {},
  payload = {},
}: {
  summary?: Record<string, unknown>;
  payload?: Record<string, unknown>;
}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("/api/core/health")) {
        return jsonResponse({ status: "ok", schema_version: 1 });
      }
      if (url.startsWith("/api/core/experiments")) {
        return jsonResponse({
          items: [
            { id: EXPERIMENT_ID, kind: "experiment", payload, ...summary },
          ],
          next_cursor: null,
        });
      }
      if (url.startsWith("/api/core/leaderboard")) return jsonResponse({ items: [] });
      return jsonResponse({ items: [], next_cursor: null });
    }),
  );
  render(<CoreExperimentView />);
}

function renderWithExperimentPayload(summary: Record<string, unknown>) {
  renderWithExperimentRow({ summary });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("timing column labels", () => {
  it("labels the declared cutoff and the effective boundary with distinct wording", async () => {
    renderWithExperimentPayload({
      mode: "prospective",
      declared_scheduling_cutoff: DECLARED,
      effective_information_boundary: FROZEN_EARLIER,
    });
    await screen.findByTestId(`experiment-id:${EXPERIMENT_ID}`);

    expect(DECLARED_CUTOFF_LABEL).not.toBe(EFFECTIVE_BOUNDARY_LABEL);
    expect(screen.getAllByText(DECLARED_CUTOFF_LABEL).length).toBeGreaterThan(0);
    expect(screen.getAllByText(EFFECTIVE_BOUNDARY_LABEL).length).toBeGreaterThan(0);
    // The freeze column names the thing it actually is, not just "cutoff".
    expect(EFFECTIVE_BOUNDARY_LABEL.toLowerCase()).toContain("freeze");
    expect(DECLARED_CUTOFF_LABEL.toLowerCase()).toContain("declared");
  });

  it("shows each timestamp in its own column", async () => {
    renderWithExperimentPayload({
      mode: "prospective",
      declared_scheduling_cutoff: DECLARED,
      effective_information_boundary: FROZEN_EARLIER,
    });
    expect(
      await screen.findByTestId(`experiment-declared-cutoff:${EXPERIMENT_ID}`),
    ).toHaveTextContent(DECLARED);
    expect(
      screen.getByTestId(`experiment-effective-boundary:${EXPERIMENT_ID}`),
    ).toHaveTextContent(FROZEN_EARLIER);
  });

  it("names the field each timestamp was read from", async () => {
    renderWithExperimentPayload({
      mode: "prospective",
      declared_scheduling_cutoff: DECLARED,
      evidence_frozen_at: FROZEN_EARLIER,
    });
    expect(
      await screen.findByTestId(`experiment-effective-boundary:${EXPERIMENT_ID}`),
    ).toHaveAttribute("title", "read from `evidence_frozen_at`");
  });

  it("reads the API's own information_cutoff projection", async () => {
    renderWithExperimentRow({
      summary: {
        mode: "prospective",
        information_cutoff: DECLARED,
        effective_information_boundary: FROZEN_EARLIER,
      },
    });
    expect(
      await screen.findByTestId(`experiment-declared-cutoff:${EXPERIMENT_ID}`),
    ).toHaveTextContent(DECLARED);
    expect(
      screen.getByTestId(`experiment-declared-cutoff:${EXPERIMENT_ID}`),
    ).toHaveAttribute("title", "read from `information_cutoff`");
  });

  it("falls back to the record payload when the projection omits a field", async () => {
    // A publication manifest carries both timestamps in its own payload.
    renderWithExperimentRow({
      summary: { mode: "prospective" },
      payload: {
        declared_information_cutoff: DECLARED,
        effective_information_boundary: FROZEN_EARLIER,
      },
    });
    expect(
      await screen.findByTestId(`experiment-declared-cutoff:${EXPERIMENT_ID}`),
    ).toHaveTextContent(DECLARED);
    expect(
      screen.getByTestId(`experiment-effective-boundary:${EXPERIMENT_ID}`),
    ).toHaveTextContent(FROZEN_EARLIER);
    expect(
      screen.getByTestId(`experiment-timing-check:${EXPERIMENT_ID}`),
    ).toHaveTextContent("Bundle frozen before the declared cutoff.");
  });

  it("does not retry the payload when the projection sends an unreadable value", async () => {
    renderWithExperimentRow({
      summary: { mode: "prospective", effective_information_boundary: 17 },
      payload: { evidence_frozen_at: FROZEN_EARLIER },
    });
    const effective = await screen.findByTestId(
      `experiment-effective-boundary:${EXPERIMENT_ID}`,
    );
    expect(effective).toHaveTextContent("not reported (unrecognized value)");
    expect(effective).not.toHaveTextContent(FROZEN_EARLIER);
  });

  it("reports an explicitly null boundary as unavailable, not as corruption", async () => {
    // thesis_core/api.py returns null when a bundle freeze is not known, which
    // is the API answering the question, not the API breaking.
    renderWithExperimentRow({
      summary: {
        mode: "prospective",
        information_cutoff: DECLARED,
        effective_information_boundary: null,
      },
    });
    const effective = await screen.findByTestId(
      `experiment-effective-boundary:${EXPERIMENT_ID}`,
    );
    expect(effective).toHaveTextContent("not available");
    expect(effective).toHaveAttribute(
      "title",
      "`effective_information_boundary` was reported as null",
    );
    expect(
      screen.getByTestId(`experiment-timing-check:${EXPERIMENT_ID}`),
    ).toHaveTextContent("Not assessable: a timing field is not reported.");
  });
});

describe("no substitution between the two timing fields", () => {
  it("does not fill a missing effective boundary with the declared cutoff", async () => {
    renderWithExperimentPayload({
      mode: "prospective",
      declared_scheduling_cutoff: DECLARED,
    });
    const effective = await screen.findByTestId(
      `experiment-effective-boundary:${EXPERIMENT_ID}`,
    );
    expect(effective).toHaveTextContent(NOT_REPORTED);
    expect(effective).not.toHaveTextContent(DECLARED);
    expect(
      screen.getByTestId(`experiment-declared-cutoff:${EXPERIMENT_ID}`),
    ).toHaveTextContent(DECLARED);
    // Exactly one cell carries the declared value.
    expect(screen.getAllByText(DECLARED)).toHaveLength(1);
  });

  it("does not fill a missing declared cutoff with the effective boundary", async () => {
    renderWithExperimentPayload({
      mode: "prospective",
      effective_information_boundary: FROZEN_EARLIER,
    });
    const declared = await screen.findByTestId(
      `experiment-declared-cutoff:${EXPERIMENT_ID}`,
    );
    expect(declared).toHaveTextContent(NOT_REPORTED);
    expect(declared).not.toHaveTextContent(FROZEN_EARLIER);
    expect(screen.getAllByText(FROZEN_EARLIER)).toHaveLength(1);
  });

  it("declines to judge ordering when only one of the two is reported", async () => {
    renderWithExperimentPayload({
      mode: "prospective",
      declared_scheduling_cutoff: DECLARED,
    });
    expect(
      await screen.findByTestId(`experiment-timing-check:${EXPERIMENT_ID}`),
    ).toHaveTextContent("Not assessable: a timing field is not reported.");
  });
});

describe("prospective ordering", () => {
  it("confirms a freeze that precedes the declared cutoff", async () => {
    renderWithExperimentPayload({
      mode: "prospective",
      declared_scheduling_cutoff: DECLARED,
      effective_information_boundary: FROZEN_EARLIER,
    });
    expect(
      await screen.findByTestId(`experiment-timing-check:${EXPERIMENT_ID}`),
    ).toHaveTextContent("Bundle frozen before the declared cutoff.");
  });

  it("flags a prospective row whose freeze is not earlier than its cutoff", async () => {
    renderWithExperimentPayload({
      mode: "prospective",
      declared_scheduling_cutoff: DECLARED,
      effective_information_boundary: "2026-09-05T00:00:00Z",
    });
    const check = await screen.findByTestId(
      `experiment-timing-check:${EXPERIMENT_ID}`,
    );
    expect(check).toHaveTextContent("prospective ordering unmet");
    // The later freeze is still displayed rather than hidden behind the flag.
    expect(
      screen.getByTestId(`experiment-effective-boundary:${EXPERIMENT_ID}`),
    ).toHaveTextContent("2026-09-05T00:00:00Z");
  });
});

describe("replay disclosure", () => {
  it("shows a later bundle assembly honestly under the replay label", async () => {
    renderWithExperimentPayload({
      mode: "replay",
      declared_scheduling_cutoff: HISTORICAL_CUTOFF,
      effective_information_boundary: ASSEMBLED_LATER,
    });
    expect(await screen.findByTestId(`experiment-mode:${EXPERIMENT_ID}`)).toHaveTextContent(
      "Replay",
    );
    expect(
      screen.getByTestId(`experiment-declared-cutoff:${EXPERIMENT_ID}`),
    ).toHaveTextContent(HISTORICAL_CUTOFF);
    expect(
      screen.getByTestId(`experiment-effective-boundary:${EXPERIMENT_ID}`),
    ).toHaveTextContent(ASSEMBLED_LATER);
    const check = screen.getByTestId(`experiment-timing-check:${EXPERIMENT_ID}`);
    expect(check).toHaveTextContent(
      "Replay: bundle assembled after the historical cutoff.",
    );
    // The prospective rule is not applied to a replay row.
    expect(check).not.toHaveTextContent("unmet");
    expect(check).not.toHaveTextContent("Prospective");
  });

  it("never labels an unknown mode as prospective", async () => {
    renderWithExperimentPayload({
      declared_scheduling_cutoff: DECLARED,
      effective_information_boundary: FROZEN_EARLIER,
    });
    expect(await screen.findByTestId(`experiment-mode:${EXPERIMENT_ID}`)).toHaveTextContent(
      "Mode not reported",
    );
    expect(
      screen.getByTestId(`experiment-timing-check:${EXPERIMENT_ID}`),
    ).toHaveTextContent("Not assessable: mode not reported.");
    expect(screen.queryByText("Prospective")).not.toBeInTheDocument();
  });

  it("does not promote an unrecognized mode string to a known mode", async () => {
    renderWithExperimentPayload({
      mode: "prospective_v2",
      declared_scheduling_cutoff: DECLARED,
      effective_information_boundary: FROZEN_EARLIER,
    });
    expect(await screen.findByTestId(`experiment-mode:${EXPERIMENT_ID}`)).toHaveTextContent(
      "Mode unrecognized (prospective_v2)",
    );
    expect(
      screen.getByTestId(`experiment-timing-check:${EXPERIMENT_ID}`),
    ).toHaveTextContent("Not assessable: mode is not a recognized value.");
  });
});
