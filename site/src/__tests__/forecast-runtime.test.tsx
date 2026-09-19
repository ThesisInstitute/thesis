import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { renderToString } from "react-dom/server";
import {
  ForecastRuntime,
  STREAM_WATCHDOG_MS,
} from "@/components/ForecastRuntime";
import { LIVE_FORECAST_SLUGS, FORECAST_CELLS } from "@/data/forecast-cells";

type Listener = (event: MessageEvent) => void;

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  url: string;
  closed = false;
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  private listeners = new Map<string, Listener[]>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, data: unknown) {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ data: JSON.stringify(data) } as MessageEvent);
    }
  }
}

const liveForecast = FORECAST_CELLS.find((m) =>
  LIVE_FORECAST_SLUGS.has(m.slug),
)!;
const cpiForecast = FORECAST_CELLS.find(
  (forecast) => forecast.slug === "cpi-u-annual-2026",
)!;

describe("ForecastRuntime stream watchdog", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", FakeEventSource);
    FakeEventSource.instances = [];
  });

  afterEach(() => {
    cleanup();
    window.history.replaceState({}, "", "/");
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("does not present the static estimate while a live forecast is pending", () => {
    // The server render must also avoid flashing the catalog's 13.1% seed.
    expect(
      renderToString(<ForecastRuntime forecast={liveForecast} />),
    ).toContain("live forecast pending");
    render(<ForecastRuntime forecast={liveForecast} />);
    const estimate = screen.getByRole("region", { name: "Forecast estimate" });

    expect(estimate).toHaveAttribute("aria-busy", "true");
    expect(estimate).not.toHaveTextContent("13.1%");
    expect(within(estimate).queryByRole("img")).toBeNull();

    act(() => {
      FakeEventSource.instances[0].emit("step", {
        kind: "text",
        text: "Checking the Census inputs.",
      });
    });
    expect(within(estimate).getByText("live forecast pending")).toBeTruthy();
    expect(estimate).not.toHaveTextContent("13.1%");

    act(() => {
      FakeEventSource.instances[0].emit("forecast", {
        pointEstimate: 13.0,
        ciLow: 11.9,
        ciHigh: 14.3,
        confidence: 0.8,
        source: "census_calibration_fallback",
      });
      FakeEventSource.instances[0].emit("done", {});
    });

    expect(estimate).toHaveAttribute("aria-busy", "false");
    expect(estimate).toHaveTextContent("live forecast · 80% CI");
    expect(estimate).toHaveTextContent("13.0%");
    expect(estimate).toHaveTextContent("11.9%");
    expect(estimate).toHaveTextContent("14.3%");
    expect(estimate).not.toHaveTextContent("13.1%");
    expect(within(estimate).getByRole("img")).toHaveAttribute(
      "aria-label",
      expect.stringContaining("13.0%"),
    );
    expect(
      screen.getByText("calibrated forecast · 80% CI").parentElement,
    ).toHaveTextContent("13.0%");
  });

  it("does not substitute the static estimate for an empty live completion", () => {
    render(<ForecastRuntime forecast={liveForecast} />);
    act(() => {
      FakeEventSource.instances[0].emit("done", {});
    });

    const estimate = screen.getByRole("region", { name: "Forecast estimate" });
    expect(estimate).toHaveTextContent("live forecast unavailable");
    expect(estimate).not.toHaveTextContent("13.1%");
    expect(estimate).toHaveAttribute("aria-busy", "false");
  });

  it("does not pair a failed partial live trace with the static estimate", () => {
    render(<ForecastRuntime forecast={liveForecast} />);
    act(() => {
      FakeEventSource.instances[0].emit("step", {
        kind: "text",
        text: "Checking the Census inputs.",
      });
      FakeEventSource.instances[0].emit("failure", {
        message: "Lookup failed.",
      });
    });

    const estimate = screen.getByRole("region", { name: "Forecast estimate" });
    expect(estimate).toHaveTextContent("live forecast unavailable");
    expect(estimate).not.toHaveTextContent("13.1%");
    expect(screen.getByText("Checking the Census inputs.")).toBeTruthy();
  });

  it("shows the labeled static estimate for an explicit mock replay", () => {
    window.history.replaceState({}, "", "/?mock=1");
    render(<ForecastRuntime forecast={liveForecast} />);

    const estimate = screen.getByRole("region", { name: "Forecast estimate" });
    expect(estimate).toHaveTextContent("static prototype forecast · 80% CI");
    expect(estimate).toHaveTextContent("13.1%");
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("shows recorded estimates immediately for cells without a live stream", () => {
    const recorded = FORECAST_CELLS.find(
      (cell) => !LIVE_FORECAST_SLUGS.has(cell.slug) && cell.predictionRun,
    )!;
    render(<ForecastRuntime forecast={recorded} />);

    const estimate = screen.getByRole("region", { name: "Forecast estimate" });
    expect(estimate).toHaveTextContent("current forecast · 80% CI");
    expect(estimate).toHaveAttribute("aria-busy", "false");
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("falls back to the static trace when the stream stays silent", () => {
    render(<ForecastRuntime forecast={liveForecast} />);
    expect(FakeEventSource.instances).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(STREAM_WATCHDOG_MS + 50);
    });

    expect(FakeEventSource.instances[0].closed).toBe(true);
    expect(screen.getByText(/replaying the static mock trace/i)).toBeTruthy();
    const estimate = screen.getByRole("region", { name: "Forecast estimate" });
    expect(estimate).toHaveTextContent("static prototype forecast · 80% CI");
    expect(estimate).toHaveTextContent("13.1%");
  });

  it("keeps the live stream once events arrive", () => {
    render(<ForecastRuntime forecast={liveForecast} />);

    act(() => {
      FakeEventSource.instances[0].emit("step", {
        kind: "heading",
        text: "Identifying the question",
      });
    });
    act(() => {
      vi.advanceTimersByTime(STREAM_WATCHDOG_MS + 50);
    });

    expect(FakeEventSource.instances[0].closed).toBe(false);
    expect(screen.getByText("Identifying the question")).toBeTruthy();
  });

  it("still falls back immediately on connection errors", () => {
    render(<ForecastRuntime forecast={liveForecast} />);

    act(() => {
      FakeEventSource.instances[0].onerror?.();
    });

    expect(FakeEventSource.instances[0].closed).toBe(true);
    expect(screen.getByText(/replaying the static mock trace/i)).toBeTruthy();
    const estimate = screen.getByRole("region", { name: "Forecast estimate" });
    expect(estimate).toHaveTextContent("static prototype forecast · 80% CI");
    expect(estimate).toHaveTextContent("13.1%");
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
