import { describe, expect, it } from "vitest";
import type { ReasoningStep } from "@/data/forecast-cells";
import { prepareReportContent } from "@/lib/report-content";

const billingError =
  "AI Gateway call failed: Free tier users do not have access to this model. Upgrade to paid credits at https://vercel.com/d?to=%2F%5Bteam%5D%2F%7E%2Fai%3Fmodal%3Dtop-up for unrestricted access.";
const credentialsError = "AI Gateway credentials are not configured.";

describe("report diagnostic presentation", () => {
  it("moves the standalone free-tier denial out of the narrative and preserves its full text", () => {
    expect(
      prepareReportContent([{ kind: "text", text: billingError }]),
    ).toEqual({
      steps: [],
      diagnostics: [billingError],
      modelUnavailable: true,
    });
  });

  it("preserves the methodology before and after an embedded billing failure", () => {
    const before =
      "The calibration fallback blends current law with history because ";
    const after = " The interval includes sampling uncertainty.";
    const original = before + billingError + after;
    const steps: ReasoningStep[] = [{ kind: "text", text: original }];
    const report = prepareReportContent(steps);

    expect(report.steps).toEqual([
      { kind: "text", text: before + "the model request failed." + after },
    ]);
    expect(report.diagnostics).toEqual([original]);
    expect(report.modelUnavailable).toBe(true);
    expect(steps).toEqual([{ kind: "text", text: original }]);
  });

  it("keeps complete embedded and standalone paragraphs in diagnostics without repeating identical entries", () => {
    const embedded = `This calibration carries the run because ${billingError}`;
    const report = prepareReportContent([
      { kind: "text", text: embedded },
      { kind: "text", text: billingError },
      { kind: "text", text: billingError },
    ]);
    expect(report.steps).toEqual([
      {
        kind: "text",
        text: "This calibration carries the run because the model request failed.",
      },
    ]);
    expect(report.diagnostics).toEqual([embedded, billingError]);
  });

  it("moves missing credentials into diagnostics while retaining surrounding caveats", () => {
    const original = `${credentialsError} The stored prior remains an assumption.`;
    const report = prepareReportContent([
      { kind: "text", text: credentialsError },
      { kind: "text", text: original },
    ]);
    expect(report.steps).toEqual([
      {
        kind: "text",
        text: "The model request failed. The stored prior remains an assumption.",
      },
    ]);
    expect(report.diagnostics).toEqual([credentialsError, original]);
    expect(report.modelUnavailable).toBe(true);
  });

  it("leaves ordinary caveats, formulas, headings, forecasts, and all tool code untouched", () => {
    const steps: ReasoningStep[] = [
      { kind: "heading", text: "Evidence" },
      {
        kind: "text",
        text: "Sampling error may move the outcome beyond the interval.\nThe source data are provisional.",
      },
      {
        kind: "math",
        text: "point = 0.55 × 13 + 0.35 × 13.1667 + 0.1 × 13.4 - 0.05",
      },
      {
        kind: "tool",
        tool: "model.request",
        call: "model.request({})",
        result: billingError,
      },
      { kind: "forecast", point: 13, ciLow: 11.9, ciHigh: 14.3 },
    ];
    expect(prepareReportContent(steps)).toEqual({
      steps,
      diagnostics: [],
      modelUnavailable: false,
    });
  });

  it("does not strip unfamiliar errors or their surrounding explanation", () => {
    const steps: ReasoningStep[] = [
      {
        kind: "text",
        text: "AI Gateway call failed: Upstream returned an unfamiliar response. This is useful diagnostic context.",
      },
      { kind: "text", text: "Census lookup failed: response was empty." },
    ];
    expect(prepareReportContent(steps)).toEqual({
      steps,
      diagnostics: [],
      modelUnavailable: false,
    });
  });

  it("handles an empty report without inventing diagnostics", () => {
    expect(prepareReportContent([])).toEqual({
      steps: [],
      diagnostics: [],
      modelUnavailable: false,
    });
  });
});
