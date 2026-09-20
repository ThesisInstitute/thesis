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
import { LIVE_FORECAST_SLUGS, FORECAST_CELLS } from "@/data/forecast-cells";
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
    drivers: ["Saved run driver"],
  },
  reasoning: [
    { kind: "heading", text: "Saved explanation" },
    {
      kind: "text",
      text: "The saved run uses a current-law calibration prior.",
    },
    { kind: "forecast", point: 13.0, ciLow: 11.9, ciHigh: 14.3 },
  ],
  recordedAt: "2026-09-19T14:20:00Z",
  artifactPath:
    "records/2026-09-19/bodies-example/live/spm-child-poverty-2025.json.gz",
};

describe("ForecastRuntime saved report", () => {
  beforeEach(() => {
    openStream.mockClear();
    vi.stubGlobal("EventSource", openStream);
  });

  afterEach(() => {
    cleanup();
    window.history.replaceState({}, "", "/");
    vi.unstubAllGlobals();
  });

  it("server-renders the complete saved report and hydrates without starting a new forecast", () => {
    const element = (
      <ForecastRuntime forecast={spmForecast} savedForecast={savedForecast} />
    );
    const container = document.createElement("div");
    container.innerHTML = renderToString(element);
    document.body.appendChild(container);
    const estimate = within(container).getByRole("region", {
      name: "Forecast estimate",
    });
    expect(estimate).toHaveTextContent("forecast · 80% CI");
    expect(estimate).toHaveTextContent("13.0%");
    expect(estimate).toHaveTextContent("11.9%");
    expect(estimate).toHaveTextContent("14.3%");
    expect(estimate).not.toHaveTextContent("13.1%");
    expect(estimate).not.toHaveTextContent("pending");
    expect(within(estimate).getByRole("img")).toHaveAttribute(
      "aria-label",
      expect.stringContaining("13.0%"),
    );
    expect(
      within(container).getByRole("heading", { name: "Analysis" }),
    ).toBeTruthy();
    expect(
      within(container).getByText(
        "The saved run uses a current-law calibration prior.",
      ),
    ).toBeTruthy();
    expect(
      within(container).getByText("calibrated forecast · 80% CI").parentElement,
    ).toHaveTextContent("13.0%");
    expect(
      within(container).queryByRole("button", {
        name: /^(pause|resume|skip|replay)$/i,
      }),
    ).toBeNull();

    render(element, { container, hydrate: true });
    expect(estimate).toHaveTextContent("13.0%");
    expect(
      within(container).getByText(
        "The saved run uses a current-law calibration prior.",
      ),
    ).toBeTruthy();
    expect(
      within(container).getByText("calibrated forecast · 80% CI").parentElement,
    ).toHaveTextContent("13.0%");
    expect(
      within(container).queryByRole("button", {
        name: /^(pause|resume|skip|replay)$/i,
      }),
    ).toBeNull();
    expect(openStream).not.toHaveBeenCalled();
  });

  it("shows saved provenance, drivers, and an archive link without relabeling catalog runs", () => {
    render(
      <ForecastRuntime forecast={spmForecast} savedForecast={savedForecast} />,
    );
    expect(screen.getByText("Saved run driver")).toBeTruthy();
    expect(
      screen.getByText("Census + PolicyEngine inputs · calibration fallback"),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Source record →" }),
    ).toHaveAttribute(
      "href",
      `https://github.com/ThesisInstitute/thesis/blob/main/${savedForecast.artifactPath}`,
    );
    expect(screen.getByText("Catalog forecast")).toBeTruthy();
    expect(screen.queryByText("Headline")).toBeNull();
    expect(
      screen.getByText(/original streamed tool activity was not archived/),
    ).toBeTruthy();
  });

  it("shows the labeled catalog estimate immediately when no saved API result is available", () => {
    render(<ForecastRuntime forecast={spmForecast} savedForecast={null} />);
    const estimate = screen.getByRole("region", { name: "Forecast estimate" });
    expect(estimate).toHaveTextContent("static prototype forecast · 80% CI");
    expect(estimate).toHaveTextContent("13.1%");
    expect(
      screen.getByText(/No completed API result is available/),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: /Near-term Census target/ }),
    ).toBeTruthy();
    expect(
      screen.getByText("calibrated forecast · 80% CI").parentElement,
    ).toHaveTextContent("13.1%");
    expect(
      screen.queryByRole("button", { name: /^(pause|resume|skip|replay)$/i }),
    ).toBeNull();
    expect(openStream).not.toHaveBeenCalled();
  });

  it("shows recorded catalog estimates immediately for cells without an API archive", () => {
    const recorded = FORECAST_CELLS.find(
      (cell) => !LIVE_FORECAST_SLUGS.has(cell.slug) && cell.predictionRun,
    )!;
    render(<ForecastRuntime forecast={recorded} />);
    expect(
      screen.getByRole("region", { name: "Forecast estimate" }),
    ).toHaveTextContent("current forecast · 80% CI");
    expect(openStream).not.toHaveBeenCalled();
  });

  it("renders target-level runs across agents, packs, and updates", () => {
    render(<ForecastRuntime forecast={cpiForecast} />);

    expect(screen.getByText("Forecast runs")).toBeTruthy();
    expect(screen.getByText("Pack visualizer")).toBeTruthy();
    expect(screen.getByText("Control · no packs")).toBeTruthy();
    expect(screen.getByText("Brier-1 · CPI packs · Jun 12")).toBeTruthy();
    expect(screen.getByText("Brier-1 · CPI packs")).toBeTruthy();
    expect(screen.getByText("models")).toBeTruthy();
    expect(screen.getAllByText("gpt-5.4").length).toBeGreaterThan(1);
    expect(
      screen.getAllByText("CPI annual-average pack set").length,
    ).toBeGreaterThan(1);
    expect(screen.getByText("update 1/2")).toBeTruthy();
    expect(screen.getByText("update 2/2")).toBeTruthy();
    expect(screen.getAllByText("public trace").length).toBeGreaterThan(1);
  });

  it("lets users select packs and inspect their details", () => {
    render(<ForecastRuntime forecast={cpiForecast} />);

    expect(
      screen.getByText(
        "Forces the agent to anchor on a resolved reference class before applying inside-view adjustments.",
      ),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Open pack page →" })
        .getAttribute("href"),
    ).toBe("/briefings/base-rate-first");

    fireEvent.click(
      screen.getAllByRole("button", { name: /Tariff pass-through/i })[0],
    );

    expect(
      screen.getByText(
        "Applies a right-tail adjustment for goods-price pass-through when tariff risk is active.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("tariff-pass-through")).toBeTruthy();
    expect(screen.getByText("calibration")).toBeTruthy();
    expect(
      screen.getByText("Brier-1 · CPI packs · Jun 12, Brier-1 · CPI packs"),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Open pack page →" })
        .getAttribute("href"),
    ).toBe("/briefings/tariff-pass-through");
  });
});
