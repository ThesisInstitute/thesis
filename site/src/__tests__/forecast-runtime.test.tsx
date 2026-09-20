import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { ForecastRuntime } from "@/components/ForecastRuntime";
import {
  FORECAST_CELLS,
  getForecastRunEntries,
  type ForecastCell,
} from "@/data/forecast-cells";
import type { ResolvedForecastScore } from "@/data/thesis-log";
import type { SavedForecastRun } from "@/lib/saved-forecast";

const spmForecast = FORECAST_CELLS.find(
  (cell) => cell.slug === "spm-child-poverty-2025",
)!;
const cpiForecast = FORECAST_CELLS.find(
  (cell) => cell.slug === "cpi-u-annual-2026",
)!;
const openStream = vi.fn();
const savedForecast: SavedForecastRun = {
  forecast: {
    pointEstimate: 13.0,
    ciLow: 11.9,
    ciHigh: 14.3,
    confidence: 0.8,
    source: "census_calibration_fallback",
    generatedAt: "2026-09-19T14:18:00Z",
    drivers: ["Archive driver"],
  },
  reasoning: [
    { kind: "heading", text: "Explanation" },
    { kind: "text", text: "This run uses a current-law calibration prior." },
    {
      kind: "tool",
      tool: "python",
      call: "estimate = 13.0\nprint(estimate)",
      result: "13.0",
    },
    { kind: "forecast", point: 13.0, ciLow: 11.9, ciHigh: 14.3 },
  ],
  recordedAt: "2026-09-19T14:20:00Z",
  artifactPath:
    "records/2026-09-19/bodies-example/live/spm-child-poverty-2025.json.gz",
};

function estimate() {
  return screen.getByRole("region", { name: "Forecast estimate" });
}
function analysis() {
  return screen.getByRole("region", { name: "Analysis" });
}
function chooseRun(variantId: string) {
  fireEvent.change(screen.getByRole("combobox", { name: "Forecast version" }), {
    target: { value: variantId },
  });
}
// The UI consumes only these score fields; scoring itself has separate ledger tests.
function displayScore(crps: number): ResolvedForecastScore {
  return {
    crps,
    signedError: 0.4,
    absoluteError: 0.4,
    probabilityIntegralTransform: 0.55,
  } as ResolvedForecastScore;
}

describe("ForecastRuntime report", () => {
  beforeEach(() => {
    openStream.mockClear();
    vi.stubGlobal("EventSource", openStream);
  });
  afterEach(() => {
    cleanup();
    document.body.innerHTML = "";
    vi.unstubAllGlobals();
  });

  it("server-renders complete analysis and code, then hydrates without a new forecast or animation", () => {
    const element = (
      <ForecastRuntime forecast={spmForecast} savedForecast={savedForecast} />
    );
    const container = document.createElement("div");
    container.innerHTML = renderToString(element);
    document.body.appendChild(container);
    const region = within(container).getByRole("region", {
      name: "Forecast estimate",
    });
    expect(region).toHaveTextContent("80% prediction interval");
    expect(region).toHaveTextContent("13.0%");
    expect(region).toHaveTextContent("11.9%");
    expect(region).toHaveTextContent("14.3%");
    expect(region).not.toHaveTextContent("13.1%");
    const chart = within(region).getByRole("img", { name: /Historical trend/ });
    expect(chart).toHaveTextContent("2025");
    expect(chart).not.toHaveTextContent("Sep 2026");
    expect(
      within(region).getByRole("img", { name: /Historical trend/ }),
    ).toHaveAttribute("aria-label", expect.stringContaining("13.0%"));
    const content = within(container).getByRole("region", { name: "Analysis" });
    expect(content).toHaveTextContent(
      "This run uses a current-law calibration prior.",
    );
    expect(content.querySelector("pre code")?.textContent).toBe(
      "estimate = 13.0\nprint(estimate)",
    );
    render(element, { container, hydrate: true });
    expect(region).toHaveTextContent("13.0%");
    expect(content).toHaveTextContent("Archive driver");
    expect(
      screen.queryByRole("button", { name: /^(pause|resume|skip|replay)$/i }),
    ).toBeNull();
    expect(openStream).not.toHaveBeenCalled();
  });

  it("includes the archive in history and keeps analysis before evidence and history", () => {
    render(
      <ForecastRuntime forecast={spmForecast} savedForecast={savedForecast} />,
    );
    expect(
      within(estimate()).getByRole("link", { name: "Source record ↗" }),
    ).toHaveAttribute(
      "href",
      `https://github.com/ThesisInstitute/thesis/blob/main/${savedForecast.artifactPath}`,
    );
    expect(analysis()).toHaveTextContent(
      "Original streamed tool activity was not archived.",
    );
    const history = screen.getByRole("region", { name: "Forecast history" });
    expect(
      within(history).getByRole("button", { name: "Calibration estimate" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(history).toHaveTextContent("13.0%");
    const evidence = screen.getByRole("region", {
      name: "Sources and resolution",
    });
    expect(
      analysis().compareDocumentPosition(evidence) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      evidence.compareDocumentPosition(history) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.queryByText("Headline")).toBeNull();
  });

  it("changes the estimate, chart, explanation, metadata, and drivers as one selected run", () => {
    render(
      <ForecastRuntime forecast={spmForecast} savedForecast={savedForecast} />,
    );
    chooseRun("primary");
    expect(estimate()).toHaveTextContent("13.1%");
    expect(estimate()).toHaveTextContent("This is an illustrative prototype");
    expect(analysis()).not.toHaveTextContent("Archive driver");
    expect(analysis()).not.toHaveTextContent(
      "This run uses a current-law calibration prior.",
    );
    expect(
      within(estimate()).queryByRole("link", { name: "Source record ↗" }),
    ).toBeNull();
    expect(
      within(estimate()).getByRole("img", { name: /Historical trend/ }),
    ).toHaveAttribute("aria-label", expect.stringContaining("13.1%"));
    const comparison = getForecastRunEntries(spmForecast)[1];
    chooseRun(comparison.variantId);
    expect(estimate()).toHaveTextContent("13.4%");
    expect(estimate()).toHaveTextContent(comparison.predictionRun!.model);
    expect(estimate().querySelector("time")).toHaveAttribute(
      "dateTime",
      comparison.predictionRun!.runAt,
    );
    expect(analysis()).not.toHaveTextContent(
      "This is an illustrative prototype",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Calibration estimate" }),
    );
    expect(
      screen.getByRole("combobox", { name: "Forecast version" }),
    ).toHaveValue(`archive:${savedForecast.artifactPath}`);
    expect(estimate()).toHaveTextContent("13.0%");
    expect(analysis()).toHaveTextContent("Archive driver");
    expect(openStream).not.toHaveBeenCalled();
  });

  it("keeps scores and outcome coverage attached to their own run, never an API archive", () => {
    const comparison = spmForecast.comparisonRuns![0];
    const forecast: ForecastCell = {
      ...spmForecast,
      ciLow: 12,
      ciHigh: 14,
      predictionDistribution: undefined,
      resolvedOutcome: {
        value: 14.5,
        resolvedAt: "2026-09-15",
        source: "Test release",
      },
      comparisonRuns: [
        {
          ...comparison,
          ciLow: 14,
          ciHigh: 15,
          predictionDistribution: undefined,
        },
      ],
    };
    render(
      <ForecastRuntime
        forecast={forecast}
        savedForecast={savedForecast}
        resolvedScore={displayScore(0.111)}
        runScores={{
          primary: displayScore(0.111),
          [comparison.variantId]: displayScore(0.222),
        }}
      />,
    );
    expect(estimate()).not.toHaveTextContent("CRPS");
    expect(estimate()).toHaveTextContent("outside 80% interval");
    chooseRun("primary");
    expect(estimate()).toHaveTextContent("CRPS 0.11");
    expect(estimate()).toHaveTextContent("outside 80% interval");
    chooseRun(comparison.variantId);
    expect(estimate()).toHaveTextContent("CRPS 0.22");
    expect(estimate()).not.toHaveTextContent("CRPS 0.11");
    expect(estimate()).toHaveTextContent("inside 80% interval");
    chooseRun(`archive:${savedForecast.artifactPath}`);
    expect(estimate()).not.toHaveTextContent("CRPS");
    expect(estimate()).toHaveTextContent(
      "This API result is not a scored catalog run.",
    );
  });

  it("puts known provider errors in expandable details while preserving the original diagnostic", () => {
    const diagnostic =
      "AI Gateway call failed: Free tier users do not have access to this model. Upgrade to paid credits at https://vercel.com/d?to=%2F%5Bteam%5D%2F%7E%2Fai%3Fmodal%3Dtop-up for unrestricted access.";
    render(
      <ForecastRuntime
        forecast={spmForecast}
        savedForecast={{
          ...savedForecast,
          reasoning: [
            ...savedForecast.reasoning,
            { kind: "text", text: diagnostic },
          ],
        }}
      />,
    );
    expect(estimate()).toHaveTextContent("The model was unavailable.");
    expect(analysis()).not.toHaveTextContent("Upgrade to paid credits");
    expect(analysis().querySelector("pre code")).toHaveTextContent(
      "estimate = 13.0",
    );
    const details = screen
      .getByText("Run details and diagnostics")
      .closest("details")!;
    expect(details).not.toHaveAttribute("open");
    fireEvent.click(within(details).getByText("Run details and diagnostics"));
    expect(
      within(details).getByText(diagnostic, { selector: "code" }),
    ).toBeVisible();
    const original = within(details)
      .getByText("Original explanation")
      .closest("details")!;
    fireEvent.click(within(original).getByText("Original explanation"));
    expect(original).toHaveTextContent(diagnostic);
  });

  it("shows the catalog immediately when there is no API archive, with honest prototype labeling", () => {
    render(<ForecastRuntime forecast={spmForecast} savedForecast={null} />);
    expect(estimate()).toHaveTextContent("13.1%");
    expect(estimate()).toHaveTextContent("This is an illustrative prototype");
    expect(
      within(analysis()).getByRole("heading", {
        name: /Near-term Census target/,
      }),
    ).toBeTruthy();
    expect(openStream).not.toHaveBeenCalled();
  });

  it("does not infer a probability curve from an archive without a distribution", () => {
    render(
      <ForecastRuntime forecast={spmForecast} savedForecast={savedForecast} />,
    );
    fireEvent.click(screen.getByText("Probability distribution"));
    expect(estimate()).not.toHaveTextContent("Cumulative probability");
    expect(estimate()).toHaveTextContent(
      "A full probability distribution is not available for this run.",
    );
    expect(
      screen.getByRole("region", { name: "Sources and resolution" }),
    ).toHaveTextContent("Resolution date");
  });

  it("identifies published point projections without inventing a displayed uncertainty interval", () => {
    const forecast = FORECAST_CELLS.find(
      (cell) => cell.slug === "bls-business-financial-employment-2034",
    )!;
    render(
      <ForecastRuntime
        forecast={{
          ...forecast,
          resolvedOutcome: {
            value: 11849,
            resolvedAt: "2035-09-01",
            source: "Test release",
          },
        }}
      />,
    );
    const projection = getForecastRunEntries(forecast).find(
      (run) => run.label === "BLS published projection",
    )!;
    chooseRun(projection.variantId);
    expect(estimate()).toHaveTextContent("Point projection");
    expect(estimate()).not.toHaveTextContent("80% prediction interval");
    expect(estimate()).not.toHaveTextContent("inside 80% interval");
    expect(estimate()).not.toHaveTextContent("outside 80% interval");
    expect(estimate()).not.toHaveTextContent("with 80% interval");
    expect(estimate()).not.toHaveTextContent("Probability distribution");
    const row = screen
      .getByRole("button", { name: "BLS published projection" })
      .closest("tr")!;
    expect(row).toHaveTextContent("Point projection");
  });

  it("resets the selected version when the forecast target changes", () => {
    const { rerender } = render(
      <ForecastRuntime forecast={spmForecast} savedForecast={savedForecast} />,
    );
    chooseRun("primary");
    rerender(<ForecastRuntime forecast={cpiForecast} />);
    expect(
      screen.getByRole("combobox", { name: "Forecast version" }),
    ).toHaveValue("primary");
    expect(estimate()).not.toHaveTextContent("13.1%");
    expect(analysis()).not.toHaveTextContent("Archive driver");
  });

  it("preserves pack selection and links in expandable technical details", () => {
    render(<ForecastRuntime forecast={cpiForecast} />);
    fireEvent.click(screen.getByText("Forecasting packs"));
    expect(
      screen.getByRole("link", { name: "Open pack page →" }),
    ).toHaveAttribute("href", "/briefings/base-rate-first");
    fireEvent.click(
      screen.getAllByRole("button", { name: /Tariff pass-through/i })[0],
    );
    expect(
      screen.getByText(
        "Applies a right-tail adjustment for goods-price pass-through when tariff risk is active.",
      ),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: "Open pack page →" }),
    ).toHaveAttribute("href", "/briefings/tariff-pass-through");
  });
});
