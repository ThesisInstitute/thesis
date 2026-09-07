// Browser behaviour of the /core experiment view: every state it can be in,
// and the guarantees it makes while in them (no invented metrics, no hidden
// exclusions, no credentials on the wire).

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { CoreExperimentView } from "@/app/core/CoreExperimentView";
import CorePage from "@/app/core/page";

const EXPERIMENT_ID = "1a".repeat(32);
const RUN_ID = "2b".repeat(32);
const FORECASTER_ID = "3c".repeat(32);
const ATTEMPT_ID = "4e".repeat(32);

type RouteResponder = () => Response | Promise<Response>;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function proxyError(
  code: string,
  status: number,
  extra: Record<string, unknown> = {},
) {
  return jsonResponse(
    { error: { code, message: `stub ${code}`, ...extra } },
    status,
  );
}

function stubFetch(routes: Record<string, RouteResponder>) {
  const impl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    void init;
    const url = String(typeof input === "string" ? input : input.toString());
    const match = Object.keys(routes).find((key) =>
      url.startsWith(`/api/core/${key}`),
    );
    if (!match) throw new Error(`unstubbed core endpoint: ${url}`);
    return routes[match]();
  });
  vi.stubGlobal("fetch", impl);
  return impl;
}

const EMPTY_ROUTES: Record<string, RouteResponder> = {
  health: () => jsonResponse({ status: "ok", schema_version: 1 }),
  experiments: () => jsonResponse({ items: [], next_cursor: null }),
  runs: () => jsonResponse({ items: [], next_cursor: null }),
  leaderboard: () => jsonResponse({ items: [] }),
};

const POPULATED_ROUTES: Record<string, RouteResponder> = {
  health: () => jsonResponse({ status: "ok", schema_version: 1 }),
  experiments: () =>
    jsonResponse({
      items: [
        {
          id: EXPERIMENT_ID,
          kind: "experiment",
          payload: {
            kind: "experiment",
            schema_version: 1,
            task_ids: [ATTEMPT_ID],
            mode: "prospective",
          },
          committed_at: "2026-09-01T00:00:00+00:00",
          mode: "prospective",
          information_cutoff: "2026-09-04T12:00:00Z",
          effective_information_boundary: "2026-09-02T09:30:00Z",
        },
      ],
      next_cursor: null,
    }),
  runs: () =>
    jsonResponse({
      items: [
        {
          id: RUN_ID,
          kind: "forecast_run",
          payload: {
            kind: "forecast_run",
            schema_version: 1,
            attempt_id: ATTEMPT_ID,
          },
          committed_at: "2026-09-03T00:00:00+00:00",
          mode: "prospective",
          information_cutoff: "2026-09-04T12:00:00Z",
          effective_information_boundary: "2026-09-02T09:30:00Z",
        },
      ],
      next_cursor: null,
    }),
  leaderboard: () =>
    jsonResponse({
      items: [
        {
          experiment_id: EXPERIMENT_ID,
          forecaster_id: FORECASTER_ID,
          mode: "prospective",
          rank: 1,
          rank_eligible: true,
          targets: 4,
          paired_coverage: 4,
          coverage: { eligible: 4, total: 4 },
          mean_normalized_crps: 0.31415,
          attempt_counts: {
            total: 6,
            succeeded: 4,
            failed: 1,
            unknown: 1,
            pending: 0,
            reconciled: 1,
            unknown_history: 2,
          },
          mean_latency_seconds: 27.34259,
          exclusions: {},
          declared_information_cutoff: "2026-09-04T12:00:00+00:00",
          effective_information_boundary: "2026-09-02T09:30:00+00:00",
          evidence_frozen_at: "2026-09-02T09:30:00+00:00",
        },
        {
          experiment_id: EXPERIMENT_ID,
          forecaster_id: "baseline-persistence",
          mode: "prospective",
          rank: null,
          rank_eligible: false,
          targets: 4,
          paired_coverage: 3,
          coverage: { eligible: 3, total: 4 },
          mean_normalized_crps: null,
          exclusions: {
            missing_normalization_record: 1,
            unknown_attempt_outcome: 2,
          },
          declared_information_cutoff: "2026-09-04T12:00:00+00:00",
          effective_information_boundary: "2026-09-02T09:30:00+00:00",
          evidence_frozen_at: "2026-09-02T09:30:00+00:00",
        },
      ],
    }),
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("/core loading state", () => {
  it("says it is loading before any endpoint answers", async () => {
    stubFetch({
      health: () => new Promise<Response>(() => {}),
      experiments: () => new Promise<Response>(() => {}),
      runs: () => new Promise<Response>(() => {}),
      leaderboard: () => new Promise<Response>(() => {}),
    });
    render(<CoreExperimentView />);
    expect(screen.getByText("Core API status: loading…")).toBeInTheDocument();
    expect(screen.getByText("Loading experiments…")).toBeInTheDocument();
    expect(screen.getByText("Loading runs…")).toBeInTheDocument();
    expect(
      screen.getByText("Loading forecaster evaluations…"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refreshing…" })).toBeDisabled();
  });
});

describe("/core unconfigured state", () => {
  it("explains that no core API is configured instead of showing an error", async () => {
    stubFetch({
      health: () => proxyError("core_api_unconfigured", 503),
      experiments: () => proxyError("core_api_unconfigured", 503),
      runs: () => proxyError("core_api_unconfigured", 503),
      leaderboard: () => proxyError("core_api_unconfigured", 503),
    });
    render(<CoreExperimentView />);
    expect(
      await screen.findByText(/Core API status: not configured/),
    ).toBeInTheDocument();
    const notices = await screen.findAllByText(
      /This deployment has no core API configured/,
    );
    expect(notices.length).toBeGreaterThanOrEqual(3);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("reports a misconfigured base URL as a deployment problem", async () => {
    stubFetch({
      health: () => proxyError("core_api_misconfigured", 503),
      experiments: () => proxyError("core_api_misconfigured", 503),
      runs: () => proxyError("core_api_misconfigured", 503),
      leaderboard: () => proxyError("core_api_misconfigured", 503),
    });
    render(<CoreExperimentView />);
    expect(
      await screen.findByText(/Core API status: not configured/),
    ).toBeInTheDocument();
    expect(
      (await screen.findAllByText(/not usable; an operator has to fix/)).length,
    ).toBeGreaterThan(0);
  });
});

describe("/core error states", () => {
  it("surfaces an upstream failure per section without blanking the page", async () => {
    stubFetch({
      health: () => jsonResponse({ status: "ok", schema_version: 1 }),
      experiments: () =>
        proxyError("upstream_status", 502, { upstream_status: 500 }),
      runs: () => proxyError("upstream_timeout", 504),
      leaderboard: () => jsonResponse({ items: [] }),
    });
    render(<CoreExperimentView />);
    expect(
      await screen.findByText(
        /Experiments unavailable: The core API returned an error status\. Upstream status 500\./,
      ),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(
        /Runs unavailable: The core API did not answer within five seconds\./,
      ),
    ).toBeInTheDocument();
    // Health and the leaderboard still render their own state.
    expect(screen.getByText(/Core API status: ok/)).toBeInTheDocument();
    expect(
      screen.getByText(/No forecaster evaluations have been scored/),
    ).toBeInTheDocument();
  });

  it("refuses a response whose shape it does not recognize", async () => {
    stubFetch({
      ...EMPTY_ROUTES,
      experiments: () => jsonResponse({ rows: [] }),
    });
    render(<CoreExperimentView />);
    expect(
      await screen.findByText(
        /Experiments unavailable: The core API returned a response this page does not recognize/,
      ),
    ).toBeInTheDocument();
  });

  it("handles a proxy response that is not JSON at all", async () => {
    stubFetch({
      ...EMPTY_ROUTES,
      leaderboard: () =>
        new Response("<html>gateway</html>", {
          status: 200,
          headers: { "content-type": "text/html" },
        }),
    });
    render(<CoreExperimentView />);
    expect(
      await screen.findByText(
        /Forecaster evaluations unavailable: The core proxy returned a body that is not valid JSON\./,
      ),
    ).toBeInTheDocument();
  });

  it("handles the browser failing to reach the proxy", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    render(<CoreExperimentView />);
    expect(
      (await screen.findAllByText(/could not reach this site's core proxy/))
        .length,
    ).toBeGreaterThan(0);
    // The health line has its own wording; "unavailable" is not the same
    // statement as "not configured", and only this branch says it.
    expect(
      await screen.findByText(/Core API status: unavailable —/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Core API status: not configured/),
    ).not.toBeInTheDocument();
  });

  it("discloses leaderboard rows it could not read alongside the ones it could", async () => {
    stubFetch({
      ...POPULATED_ROUTES,
      leaderboard: () =>
        jsonResponse({
          items: [
            {
              experiment_id: EXPERIMENT_ID,
              forecaster_id: FORECASTER_ID,
              mode: "replay",
              rank: null,
              coverage: { eligible: 1, total: 2 },
              mean_normalized_crps: null,
              exclusions: [],
            },
            "not a row",
            null,
          ],
        }),
    });
    render(<CoreExperimentView />);
    expect(
      await screen.findByText(
        /2 leaderboard row\(s\) were returned in a shape this page does not recognize/,
      ),
    ).toBeInTheDocument();
    // ...and the readable row is still on screen.
    expect(
      screen.getByTestId(`leaderboard-mode:${EXPERIMENT_ID}:${FORECASTER_ID}`),
    ).toHaveTextContent("Replay");
  });
});

describe("/core empty state", () => {
  it("says the database is empty rather than rendering a bare table", async () => {
    stubFetch(EMPTY_ROUTES);
    render(<CoreExperimentView />);
    expect(
      await screen.findByText(
        "No experiments have been registered in the core database yet.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No runs have been recorded in the core database yet."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "No forecaster evaluations have been scored in the core database yet.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("/core populated state", () => {
  it("shortens displayed hashes while retaining full record links and titles", async () => {
    stubFetch(POPULATED_ROUTES);
    render(<CoreExperimentView />);
    const cell = await screen.findByTestId(`experiment-id:${EXPERIMENT_ID}`);
    const linkedCells = [
      [cell, EXPERIMENT_ID],
      [await screen.findByTestId(`run-id:${RUN_ID}`), RUN_ID],
      [screen.getByTestId(`run-reference:${RUN_ID}`), ATTEMPT_ID],
      [
        screen.getByTestId(
          `leaderboard-forecaster:${EXPERIMENT_ID}:${FORECASTER_ID}`,
        ),
        FORECASTER_ID,
      ],
    ] as const;
    for (const [element, identity] of linkedCells) {
      const link = within(element).getByRole("link");
      expect(link).toHaveTextContent(`${identity.slice(0, 12)}…`);
      expect(link).toHaveAttribute("title", identity);
      expect(link).toHaveAttribute("href", `/api/core/records/${identity}`);
    }
  });

  it("shows reported attempt outcomes and mean latency without inventing missing values", async () => {
    stubFetch(POPULATED_ROUTES);
    render(<CoreExperimentView />);
    const key = `${EXPERIMENT_ID}:${FORECASTER_ID}`;
    const attempts = await screen.findByTestId(`leaderboard-attempts:${key}`);
    expect(attempts).toHaveTextContent("6 total · 4 succeeded");
    expect(attempts).toHaveTextContent("1 failed · 1 unknown · 0 pending");
    expect(attempts).toHaveTextContent("1 reconciled · 2 unknown history");
    const latency = screen.getByTestId(`leaderboard-latency:${key}`);
    expect(latency).toHaveTextContent("27.34 s");
    expect(within(latency).getByTitle("27.34259 seconds")).toBeInTheDocument();
    const missingKey = `${EXPERIMENT_ID}:baseline-persistence`;
    expect(
      screen.getByTestId(`leaderboard-attempts:${missingKey}`),
    ).toHaveTextContent("not reported");
    expect(
      screen.getByTestId(`leaderboard-latency:${missingKey}`),
    ).toHaveTextContent("not reported");
  });

  it("shows the mode of every row", async () => {
    stubFetch(POPULATED_ROUTES);
    render(<CoreExperimentView />);
    expect(
      await screen.findByTestId(`experiment-mode:${EXPERIMENT_ID}`),
    ).toHaveTextContent("Prospective");
    expect(await screen.findByTestId(`run-mode:${RUN_ID}`)).toHaveTextContent(
      "Prospective",
    );
  });

  it("renders evaluation metrics without inventing values", async () => {
    stubFetch(POPULATED_ROUTES);
    render(<CoreExperimentView />);
    const rankedKey = `${EXPERIMENT_ID}:${FORECASTER_ID}`;
    expect(
      await screen.findByTestId(`leaderboard-rank:${rankedKey}`),
    ).toHaveTextContent("1");
    expect(
      screen.getByTestId(`leaderboard-coverage:${rankedKey}`),
    ).toHaveTextContent("4 / 4");
    expect(
      screen.getByTestId(`leaderboard-crps:${rankedKey}`),
    ).toHaveTextContent("0.31415");
    expect(
      screen.getByTestId(`leaderboard-exclusions:${rankedKey}`),
    ).toHaveTextContent("none recorded");

    const unrankedKey = `${EXPERIMENT_ID}:baseline-persistence`;
    expect(
      screen.getByTestId(`leaderboard-rank:${unrankedKey}`),
    ).toHaveTextContent("not ranked (not rank-eligible)");
    expect(
      screen.getByTestId(`leaderboard-crps:${unrankedKey}`),
    ).toHaveTextContent("not available");
    expect(
      screen.getByTestId(`leaderboard-crps:${unrankedKey}`),
    ).not.toHaveTextContent("0");
    expect(
      screen.getByTestId(`leaderboard-coverage:${unrankedKey}`),
    ).toHaveTextContent("3 / 4");
  });

  it("never hides an exclusion reason", async () => {
    stubFetch(POPULATED_ROUTES);
    render(<CoreExperimentView />);
    const cell = await screen.findByTestId(
      `leaderboard-exclusions:${EXPERIMENT_ID}:baseline-persistence`,
    );
    expect(cell).toHaveTextContent("missing_normalization_record × 1");
    expect(cell).toHaveTextContent("unknown_attempt_outcome × 2");
  });

  it("shows a row whose exclusions were never reported as unreported", async () => {
    stubFetch({
      ...POPULATED_ROUTES,
      leaderboard: () =>
        jsonResponse({
          items: [
            {
              experiment_id: EXPERIMENT_ID,
              forecaster_id: FORECASTER_ID,
              mode: "replay",
              rank: null,
              coverage: { eligible: 0, total: 2 },
            },
          ],
        }),
    });
    render(<CoreExperimentView />);
    const key = `${EXPERIMENT_ID}:${FORECASTER_ID}`;
    expect(
      await screen.findByTestId(`leaderboard-exclusions:${key}`),
    ).toHaveTextContent("not reported");
    expect(screen.getByTestId(`leaderboard-crps:${key}`)).toHaveTextContent(
      "not reported",
    );
    expect(screen.getByTestId(`leaderboard-mode:${key}`)).toHaveTextContent(
      "Replay",
    );
  });

  it("does not call a page of unreadable rows an empty database", async () => {
    stubFetch({
      ...EMPTY_ROUTES,
      experiments: () =>
        jsonResponse({
          items: [{ id: "x", kind: "experiment" }, { id: "y" }],
          next_cursor: null,
        }),
      leaderboard: () => jsonResponse({ items: ["nope", 7] }),
    });
    render(<CoreExperimentView />);
    expect(
      await screen.findByText(
        /returned 2 row\(s\) in a shape this page does not recognize, and no row it could read\. This is not an empty database\./,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/This is not an empty leaderboard\./),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "No experiments have been registered in the core database yet.",
      ),
    ).not.toBeInTheDocument();
  });

  it("keeps readable exclusions visible when one entry is malformed", async () => {
    stubFetch({
      ...POPULATED_ROUTES,
      leaderboard: () =>
        jsonResponse({
          items: [
            {
              experiment_id: EXPERIMENT_ID,
              forecaster_id: FORECASTER_ID,
              mode: "replay",
              rank: null,
              rank_eligible: false,
              coverage: { eligible: 1, total: 2 },
              mean_normalized_crps: null,
              exclusions: { late_witness: 2, broken: "?" },
            },
          ],
        }),
    });
    render(<CoreExperimentView />);
    const cell = await screen.findByTestId(
      `leaderboard-exclusions:${EXPERIMENT_ID}:${FORECASTER_ID}`,
    );
    expect(cell).toHaveTextContent("late_witness × 2");
    expect(cell).toHaveTextContent("1 unreadable entry");
  });

  it("discloses truncation and unreadable rows instead of implying completeness", async () => {
    stubFetch({
      ...POPULATED_ROUTES,
      experiments: () =>
        jsonResponse({
          items: [
            {
              id: EXPERIMENT_ID,
              kind: "experiment",
              payload: { mode: "replay" },
            },
            { id: "no-payload", kind: "experiment" },
          ],
          next_cursor: "cursor-token",
        }),
    });
    render(<CoreExperimentView />);
    expect(
      await screen.findByText(/the API reported more pages beyond this one/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /1 row\(s\) were returned in a shape this page does not recognize/,
      ),
    ).toBeInTheDocument();
  });

  it("labels a run with the attempt its payload references", async () => {
    stubFetch(POPULATED_ROUTES);
    render(<CoreExperimentView />);
    const runsTable = (await screen.findAllByRole("table"))[1];
    expect(within(runsTable).getByTitle(ATTEMPT_ID)).toHaveAttribute(
      "href",
      `/api/core/records/${ATTEMPT_ID}`,
    );
    expect(
      await screen.findByTestId(`run-reference:${RUN_ID}`),
    ).toHaveTextContent(`${ATTEMPT_ID.slice(0, 12)}…`);
  });

  it("reads timing from the API projection that carries it", async () => {
    stubFetch(POPULATED_ROUTES);
    render(<CoreExperimentView />);
    expect(
      await screen.findByTestId(`experiment-declared-cutoff:${EXPERIMENT_ID}`),
    ).toHaveAttribute("title", "read from `information_cutoff`");
    expect(
      screen.getByTestId(`experiment-effective-boundary:${EXPERIMENT_ID}`),
    ).toHaveTextContent("2026-09-02T09:30:00Z");
  });

  it("shows the leaderboard's own timing disclosure", async () => {
    stubFetch(POPULATED_ROUTES);
    render(<CoreExperimentView />);
    const key = `${EXPERIMENT_ID}:${FORECASTER_ID}`;
    expect(
      await screen.findByTestId(`leaderboard-declared-cutoff:${key}`),
    ).toHaveTextContent("2026-09-04T12:00:00+00:00");
    expect(
      screen.getByTestId(`leaderboard-effective-boundary:${key}`),
    ).toHaveTextContent("2026-09-02T09:30:00+00:00");
    expect(
      screen.getByTestId(`leaderboard-timing-check:${key}`),
    ).toHaveTextContent("Bundle frozen before the declared cutoff.");
  });
});

describe("/core requests", () => {
  it("asks the same-origin proxy for each endpoint and sends no credentials", async () => {
    const impl = stubFetch(EMPTY_ROUTES);
    render(<CoreExperimentView />);
    await screen.findByText(
      "No experiments have been registered in the core database yet.",
    );

    const urls = impl.mock.calls.map((call) => String(call[0]));
    expect(urls).toContain("/api/core/health");
    expect(urls).toContain("/api/core/experiments?limit=25");
    expect(urls).toContain("/api/core/runs?limit=25");
    expect(urls).toContain("/api/core/leaderboard");
    for (const call of impl.mock.calls) {
      const init = call[1] as RequestInit;
      expect(init.credentials).toBe("omit");
      expect(init.method).toBe("GET");
      expect(String(call[0]).startsWith("/api/core/")).toBe(true);
    }
  });

  it("re-reads every endpoint when the refresh button is used", async () => {
    let experimentCalls = 0;
    const impl = stubFetch({
      ...EMPTY_ROUTES,
      experiments: () => {
        experimentCalls += 1;
        return experimentCalls === 1
          ? jsonResponse({ items: [], next_cursor: null })
          : jsonResponse({
              items: [
                {
                  id: EXPERIMENT_ID,
                  kind: "experiment",
                  payload: { mode: "replay" },
                },
              ],
              next_cursor: null,
            });
      },
    });
    render(<CoreExperimentView />);
    await screen.findByText(
      "No experiments have been registered in the core database yet.",
    );
    expect(impl).toHaveBeenCalledTimes(4);

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(
      await screen.findByTestId(`experiment-id:${EXPERIMENT_ID}`),
    ).toBeInTheDocument();
    expect(impl).toHaveBeenCalledTimes(8);
  });

  it("offers no mutation or authentication control", async () => {
    stubFetch(POPULATED_ROUTES);
    render(<CoreExperimentView />);
    await screen.findByTestId(`experiment-id:${EXPERIMENT_ID}`);
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(1);
    expect(buttons[0]).toHaveAccessibleName("Refresh");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("form")).not.toBeInTheDocument();
  });
});

describe("/core page shell", () => {
  it("renders the site header and the experiment view without server data access", async () => {
    stubFetch(EMPTY_ROUTES);
    render(CorePage());
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Core experiments", level: 1 }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(
        "No experiments have been registered in the core database yet.",
      ),
    ).toBeInTheDocument();
  });

  it("prerenders without touching the network, so the site builds with no core API", () => {
    const forbidden = vi.fn(() => {
      throw new Error(
        "the /core page must not fetch while rendering on the server",
      );
    });
    vi.stubGlobal("fetch", forbidden);
    const html = renderToStaticMarkup(CorePage());
    expect(html).toContain("Core experiments");
    expect(html).toContain("Loading experiments…");
    expect(forbidden).not.toHaveBeenCalled();
  });

  it("keeps the footer concise and explains record inspection", async () => {
    stubFetch(EMPTY_ROUTES);
    render(<CoreExperimentView />);
    expect(
      screen.getByText(
        "This view is read-only. Select an ID to inspect the full record.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/same-origin server proxy/),
    ).not.toBeInTheDocument();
  });
});
