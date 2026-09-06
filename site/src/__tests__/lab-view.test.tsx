import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CdfChart } from "@/app/lab/CdfChart";
import { ExperimentView, ForecastsView, OperationsView } from "@/app/lab/LabViews";
import { Mode, Reasons, Release } from "@/app/lab/lab-ui";
import { fetchLab } from "@/app/lab/lab-client";
import { assessOrdering, readMode } from "@/app/core/core-contracts";
import { describeMode, describeOrdering } from "@/app/core/core-display";
import {
  comparison,
  experimentDetail,
  envelope,
  forecast,
  forecastPage,
  ids,
  operations,
  matrix,
  release,
} from "./lab-fixtures";

vi.mock("next/navigation", () => ({
  usePathname: () => "/lab/forecasts",
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
const response = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });

describe("forecast lab working surfaces", () => {
  it("renders real response values and visibly unranked mode membership", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response(forecastPage)),
    );
    render(<ForecastsView />);
    expect(
      await screen.findByRole("link", { name: forecast.title }),
    ).toHaveAttribute("href", `/lab/forecasts/${ids.target}`);
    expect(screen.getByText("Awaiting outcome")).toBeVisible();
    expect(screen.getByText(/live pilot unranked/)).toBeVisible();
    expect(screen.getByText("1 of 1 loaded")).toBeVisible();
  });
  it("keeps loaded rows visible when a later page fails and permits retry", async () => {
    const nextId = "8".repeat(64);
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        response({ ...forecastPage, total: 2, next_cursor: ids.target }),
      )
      .mockResolvedValueOnce(
        response(
          { error: { code: "upstream_status", upstream_status: 503 } },
          502,
        ),
      )
      .mockResolvedValueOnce(
        response({
          ...envelope,
          items: [
            { ...forecast, id: nextId, title: "Second registered target" },
          ],
          total: 2,
          next_cursor: null,
        }),
      );
    vi.stubGlobal("fetch", fetchImpl);
    render(<ForecastsView />);
    await screen.findByRole("link", { name: forecast.title });
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("503");
    expect(screen.getByRole("link", { name: forecast.title })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    expect(
      await screen.findByRole("link", { name: "Second registered target" }),
    ).toBeVisible();
    expect(screen.getByText("2 of 2 loaded")).toBeVisible();
    expect(fetchImpl.mock.calls[1][0]).toContain(`after=${ids.target}`);
  });
  it("distinguishes an unavailable service from an empty collection", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        response({ error: { code: "core_api_unconfigured" } }, 503),
      ),
    );
    render(<ForecastsView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("not connected");
    expect(screen.queryByText("No records yet")).not.toBeInTheDocument();
  });
  it("does not let a stale first request replace a refreshed collection", async () => {
    let finish: (response: Response) => void = () => {};
    const first = new Promise<Response>((resolve) => {
      finish = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockReturnValueOnce(first)
        .mockResolvedValueOnce(
          response({
            ...forecastPage,
            items: [{ ...forecast, title: "Fresh target" }],
          }),
        ),
    );
    render(<ForecastsView />);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByRole("link", { name: "Fresh target" });
    await act(async () => {
      finish(response(forecastPage));
    });
    expect(screen.getByRole("link", { name: "Fresh target" })).toBeVisible();
    expect(
      screen.queryByRole("link", { name: forecast.title }),
    ).not.toBeInTheDocument();
  });
  it("shows absent polling independently of completed jobs", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response(operations)),
    );
    render(<OperationsView />);
    expect(await screen.findByText(/not scheduled · 0 sources/)).toBeVisible();
    expect(screen.getByText("unknown", { selector: "dd" })).toBeVisible();
    expect(screen.getByText("never seen")).toBeVisible();
    expect(screen.getByText("10")).toBeVisible();
  });
  it("paginates matrix targets and methods independently, retaining both cursors", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async (input) => {
      const url = new URL(String(input), "http://localhost");
      if (url.pathname.endsWith("/results")) return response({ ...envelope, items: [], total: 0, next_cursor: null });
      if (!url.pathname.endsWith("/matrix")) return response(experimentDetail);
      const laterMethod = url.searchParams.has("method_after");
      const laterTarget = url.searchParams.has("after");
      const methodId = laterMethod ? "8".repeat(64) : ids.agent;
      const targetId = laterTarget ? "9".repeat(64) : ids.target;
      return response({
        ...matrix,
        columns: [{ ...matrix.columns[0], forecaster_id: methodId, agent: { ...matrix.columns[0].agent, id: methodId, label: laterMethod ? "Second method" : "First method" } }],
        rows: [{ ...matrix.rows[0], target_id: targetId, title: laterTarget ? "Second target" : "First target", forecast_path: `/lab/forecasts/${targetId}`, cells: [{ ...matrix.rows[0].cells[0], target_id: targetId, forecaster_id: methodId, comparison_path: `/lab/forecasts/${targetId}/comparisons?experiment_id=${ids.experiment}` }] }],
        total_targets: 2, total_methods: 2,
        next_cursor: laterTarget ? null : ids.target,
        next_method_cursor: laterMethod ? null : ids.agent,
      });
    });
    vi.stubGlobal("fetch", fetchImpl);
    render(<ExperimentView id={ids.experiment} />);
    await screen.findByRole("link", { name: "First method" });
    fireEvent.click(screen.getByRole("button", { name: "Next methods" }));
    expect(await screen.findByRole("link", { name: "Second method" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Next targets" }));
    expect(await screen.findByRole("link", { name: "Second target" })).toBeVisible();
    const calls = fetchImpl.mock.calls.map(([input]) => String(input));
    expect(calls.some((url) => url.includes(`after=${ids.target}`) && url.includes(`method_after=${ids.agent}`))).toBe(true);
    expect(screen.getByRole("button", { name: "Previous targets" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Previous methods" })).toBeEnabled();
  });
});

describe("truthful curves and timing", () => {
  it("renders round axis labels in both views and includes an outside outcome", () => {
    const shifted = {
      ...comparison,
      distribution: {
        ...comparison.distribution!,
        points: comparison.distribution!.points.map((p) => ({ ...p, value: 0.95 + p.value * 0.4 })),
        support: { lower: 0.95, upper: 4.95 },
      },
    };
    const { container, rerender } = render(<CdfChart comparisons={[shifted]} outcome={null} unitName="percent" />);
    const labels = (axis: string) => [...container.querySelectorAll(`[data-axis="${axis}"]`)].map((el) => el.textContent);
    expect(labels("x")).toEqual(["0", "1", "2", "3", "4", "5"]);
    expect(labels("y")).toEqual(["0%", "20%", "40%", "60%", "80%", "100%"]);
    fireEvent.click(screen.getByRole("button", { name: "PDF", exact: true }));
    expect(labels("y")).toEqual(["0", "0.05", "0.1", "0.15", "0.2", "0.25"]);
    rerender(<CdfChart comparisons={[shifted]} outcome={8.3} unitName="percent" />);
    expect(labels("x")).toEqual(["0", "2", "4", "6", "8", "10"]);
    const marker = container.querySelector(".lab-outcome-line")!;
    expect(Number(marker.getAttribute("x1"))).toBeLessThan(892);
    expect(Number(marker.getAttribute("x1"))).toBeGreaterThan(68);
  });
  it("switches to a derived step PDF and back without changing the sealed CDF", () => {
    const before = JSON.stringify(comparison.distribution);
    render(<CdfChart comparisons={[comparison]} outcome={4} unitName="percent" />);
    const originalPath = screen.getByTestId(`cdf-${ids.task}`).getAttribute("d");
    expect(screen.getByRole("button", { name: "CDF", exact: true })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "PDF", exact: true }));
    expect(screen.getByRole("button", { name: "PDF", exact: true })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Binned density · per percentage point")).toBeVisible();
    expect(screen.getByRole("img", { name: /Forecast probability densities/ })).toBeVisible();
    expect(screen.queryByText("100%")).not.toBeInTheDocument();
    expect(screen.getByText("0.1", { selector: "text" })).toBeVisible();
    const path = screen.getByTestId(`pdf-${ids.task}`);
    expect(path).toHaveAttribute("data-segment-count", "40");
    expect(path.getAttribute("d")?.match(/L/g)).toHaveLength(81);
    expect(path.getAttribute("d")).not.toMatch(/NaN|Infinity/);
    expect(screen.getByText("Observed 4")).toBeVisible();
    fireEvent.focus(screen.getByRole("button", { name: /Emphasize Recorded forecaster/ }));
    expect(path).toHaveAttribute("stroke-width", "3.5");
    fireEvent.click(screen.getByRole("button", { name: "CDF", exact: true }));
    expect(screen.getByTestId(`cdf-${ids.task}`)).toHaveAttribute("d", originalPath);
    expect(JSON.stringify(comparison.distribution)).toBe(before);
  });
  it("uses a shared density scale while preserving baseline styling", () => {
    const baseline = {
      ...comparison,
      task: { ...comparison.task, id: "8".repeat(64) },
      is_baseline: true,
      distribution: {
        ...comparison.distribution!,
        points: comparison.distribution!.points.map((p) => ({ ...p, value: p.value / 2 })),
        support: { lower: 0, upper: 5 },
      },
    };
    render(<CdfChart comparisons={[comparison, baseline]} outcome={null} unitName="percent" />);
    fireEvent.click(screen.getByRole("button", { name: "PDF", exact: true }));
    // Densities 0.1 and 0.2 must be half-height and full-height on the same axis.
    expect(screen.getByTestId(`pdf-${ids.task}`).getAttribute("d")).toContain(",172.0000");
    expect(screen.getByTestId(`pdf-${baseline.task.id}`).getAttribute("d")).toContain(",34.0000");
    expect(screen.getByTestId(`pdf-${baseline.task.id}`)).toHaveAttribute("stroke-dasharray", "5 5");
  });
  it("explains an unrepresentable density and keeps the CDF available", () => {
    const narrow = {
      ...comparison,
      distribution: {
        ...comparison.distribution!,
        points: comparison.distribution!.points.map((p, i) => ({ ...p, value: i * Number.MIN_VALUE })),
        support: { lower: 0, upper: 200 * Number.MIN_VALUE },
      },
    };
    render(<CdfChart comparisons={[narrow]} outcome={null} unitName="percent" />);
    fireEvent.click(screen.getByRole("button", { name: "PDF", exact: true }));
    expect(screen.getByText(/density is unavailable at this numeric scale/)).toBeVisible();
    expect(screen.queryByTestId(`pdf-${ids.task}`)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "CDF", exact: true }));
    expect(screen.getByTestId(`cdf-${ids.task}`).getAttribute("d")).not.toMatch(/NaN|Infinity/);
  });
  it("draws the original 201 CDF points and offers keyboard curve emphasis", () => {
    const before = JSON.stringify(comparison.distribution);
    render(
      <CdfChart comparisons={[comparison]} outcome={null} unitName="percent" />,
    );
    const path = screen.getByTestId(`cdf-${ids.task}`);
    expect(path).toHaveAttribute("data-point-count", "201");
    expect(path.getAttribute("d")?.match(/L/g)).toHaveLength(200);
    fireEvent.focus(
      screen.getByRole("button", { name: /Emphasize Recorded forecaster/ }),
    );
    expect(path).toHaveAttribute("stroke-width", "3.5");
    expect(JSON.stringify(comparison.distribution)).toBe(before);
  });
  it("preserves date-only release evidence as an interval", () => {
    render(<Release value={release} detail />);
    expect(screen.getByText("September 14, 2026")).toBeVisible();
    expect(
      screen.getByText(/2026-09-14 04:00:00 UTC – 2026-09-15 04:00:00 UTC/),
    ).toBeVisible();
    expect(screen.queryByText(/8:30/)).not.toBeInTheDocument();
  });
  it.each(["prospective", "replay", "live_pilot"] as const)(
    "handles %s explicitly",
    (mode) => {
      render(<Mode mode={mode} />);
      expect(
        screen.getByText(
          mode === "prospective"
            ? "Prospective"
            : mode === "replay"
              ? "Replay · unranked"
              : "Live pilot · unranked",
        ),
      ).toBeVisible();
    },
  );
  it("discloses late pilot execution instead of hiding it under unranked", () => {
    render(<Reasons codes={["late_pilot_execution"]} />);
    expect(
      screen.getByText("Pilot execution crossed its deadline"),
    ).toBeVisible();
  });
  it("keeps legacy core pilot timing distinct from prospective witness qualification", () => {
    const mode = readMode({ mode: "live_pilot" });
    const ordering = assessOrdering(
      mode,
      { state: "value", value: "2026-09-05T12:00:00Z", field: "cutoff" },
      { state: "value", value: "2026-09-05T11:59:00Z", field: "freeze" },
    );
    expect(describeMode(mode)).toBe("Live pilot · unranked");
    expect(describeOrdering(ordering)).toContain("not externally qualified");
  });
  it("refuses comparison rows returned for a different cohort", async () => {
    await expect(
      fetchLab(
        `/lab/forecasts/${ids.target}/comparisons?experiment_id=${ids.experiment}`,
        "ComparisonPage",
        undefined,
        async () =>
          response({
            ...envelope,
            items: [{ ...comparison, experiment_id: ids.source }],
            total: 1,
            next_cursor: null,
          }),
      ),
    ).rejects.toThrow("different record or experiment");
  });
});
