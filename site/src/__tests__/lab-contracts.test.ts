import { describe, expect, it } from "vitest";
import { isUtcInstant, parseLab } from "@/lib/lab-schema";
import { isLabApiPath, labProxyPath } from "@/lib/lab-paths";
import {
  comparison,
  envelope,
  forecastDetail,
  forecastPage,
  ids,
  matrix,
  operations,
} from "./lab-fixtures";

describe("lab runtime contract", () => {
  it("preserves all native points and the separately reported summary", () => {
    const value = {
      ...envelope,
      items: [comparison],
      total: 1,
      next_cursor: null,
    };
    const result = parseLab("ComparisonPage", value);
    expect(result).toBe(value);
    expect(result.items[0].distribution?.summary.median).toBe(7);
    expect(result.items[0].quantiles?.q50).toBe(5);
  });
  it("accepts all required forecast detail fields and its comparison template", () => {
    expect(parseLab("ForecastDetail", forecastDetail)).toBe(forecastDetail);
  });
  it("rejects missing nullable fields instead of defaulting them", () => {
    const value = structuredClone(comparison) as unknown as Record<
      string,
      unknown
    >;
    delete value.quantiles;
    expect(() =>
      parseLab("ComparisonPage", {
        ...envelope,
        items: [value],
        total: 1,
        next_cursor: null,
      }),
    ).toThrow();
  });
  it.each([
    { ...forecastPage, items: [], total: -1 },
    { ...forecastPage, total: "1" },
    { ...forecastPage, surprise: true },
    { ...forecastPage, generated_at: "2026-02-30T12:00:00Z" },
    { ...forecastPage, generated_at: "2026-09-05T12:00:00" },
    { ...forecastPage, next_cursor: "//private" },
  ])("refuses malformed wire response %#", (value) => {
    expect(() => parseLab("ForecastPage", value)).toThrow();
  });
  it("rejects fabricated mode counts and execution coverage", () => {
    const value = structuredClone(forecastPage);
    expect(() =>
      parseLab("ForecastPage", {
        ...value,
        items: [
          {
            ...value.items[0],
            mode_counts: { prospective: 0, replay: 0, live_pilot: 2 },
          },
        ],
      }),
    ).toThrow();
    expect(() =>
      parseLab("ForecastPage", {
        ...value,
        items: [
          {
            ...value.items[0],
            coverage: { ...value.items[0].coverage, failed_tasks: 1 },
          },
        ],
      }),
    ).toThrow();
  });
  it("does not present an invalidated resolution as an authoritative value", () => {
    const invalid = {
      ...forecastPage.items[0].resolution,
      state: "invalid",
      value: 3,
      reason_code: "invalid_resolution",
    };
    expect(() =>
      parseLab("ForecastPage", {
        ...forecastPage,
        items: [{ ...forecastPage.items[0], resolution: invalid }],
      }),
    ).toThrow();
  });
  it("checks matrix row and column identities", () => {
    expect(parseLab("MatrixPage", matrix)).toBe(matrix);
    const row = matrix.rows[0];
    const bad = {
      ...matrix,
      rows: [
        { ...row, cells: [{ ...row.cells[0], forecaster_id: ids.source }] },
      ],
    };
    expect(() => parseLab("MatrixPage", bad)).toThrow();
    expect(() =>
      parseLab("MatrixPage", { ...matrix, rows: [{ ...row, cells: [] }] }),
    ).toThrow();
  });
  it("keeps a missing declared task visibly invalid", () => {
    const row = matrix.rows[0];
    const cell = row.cells[0];
    const absent = {
      ...cell,
      task: null,
      selected_run: null,
      quantiles: null,
      execution: {
        ...cell.execution,
        state: "invalid",
        attempts_path: null,
        attempt_counts: {
          total: 0,
          succeeded: 0,
          failed: 0,
          unknown: 0,
          pending: 0,
          reconciled: 0,
          unknown_history: 0,
        },
      },
      score: {
        ...cell.score,
        eligibility: {
          state: "ineligible",
          reason_codes: ["invalid_contract"],
          ranking_allowed: false,
          reward: null,
        },
      },
    };
    expect(
      parseLab("MatrixPage", { ...matrix, rows: [{ ...row, cells: [absent] }] })
        .rows[0].cells[0].execution.state,
    ).toBe("invalid");
  });
  it("rejects a reward on a live pilot even when its numeric score exists", () => {
    const row = {
      ...comparison,
      score: {
        ...comparison.score,
        crps: 0.25,
        eligibility: {
          state: "eligible",
          reason_codes: ["eligible"],
          ranking_allowed: true,
          reward: -0.25,
        },
      },
    };
    expect(() =>
      parseLab("ComparisonPage", {
        ...envelope,
        items: [row],
        total: 1,
        next_cursor: null,
      }),
    ).toThrow();
  });
  it("accepts late pilot exclusions without relabeling them as replay", () => {
    const row = {
      ...comparison,
      score: {
        ...comparison.score,
        eligibility: {
          ...comparison.score.eligibility,
          reason_codes: ["late_pilot_execution"],
        },
      },
    };
    expect(
      parseLab("ComparisonPage", {
        ...envelope,
        items: [row],
        total: 1,
        next_cursor: null,
      }).items[0].score.eligibility.reason_codes,
    ).toEqual(["late_pilot_execution"]);
  });
  it("distinguishes no polling from an active database and completed jobs", () => {
    const result = parseLab("OperationsSummary", operations);
    expect(result.database.state).toBe("available");
    expect(result.jobs.complete).toBe(10);
    expect(result.polling.state).toBe("not_scheduled");
    expect(result.worker.state).toBe("unknown");
  });
  it.each([
    "2026-13-01T00:00:00Z",
    "2026-01-01T24:00:00Z",
    "2026-01-01T00:00:60Z",
    "2026-02-29T00:00:00Z",
  ])("rejects invalid UTC time %s", (value) =>
    expect(isUtcInstant(value)).toBe(false),
  );
});

describe("lab link boundary", () => {
  it("translates only fixed relative API paths", () =>
    expect(labProxyPath(`/records/${ids.task}`)).toBe(
      `/api/core/records/${ids.task}`,
    ));
  it.each([
    "https://private.example/records",
    "//private.example/lab/forecasts",
    "/lab/forecasts/../agents",
    "/lab/forecasts?limit=0",
    "/lab/forecasts?limit=1&limit=2",
    `/lab/forecasts/${ids.target}/comparisons`,
    `/artifacts/${ids.artifact}?download=1`,
    `/records/${ids.task}#fragment`,
    "/lab/unknown",
  ])("refuses unsafe or incomplete link %s", (path) =>
    expect(isLabApiPath(path)).toBe(false),
  );
});
