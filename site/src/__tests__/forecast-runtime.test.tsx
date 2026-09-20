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
import { FORECAST_CELLS, type ForecastCell } from "@/data/forecast-cells";
import type { ResolvedForecastScore } from "@/data/thesis-log";

const source = FORECAST_CELLS.find(
  (cell) => cell.slug === "spm-child-poverty-2025",
)!;
const metadata = source.comparisonRuns![0].predictionRun;
// Presentation fixtures. Separate unmocked publication/scoring tests verify
// actual archive evidence before forecast props reach the production UI.
const report: ForecastCell = {
  ...source,
  primaryVariantId: "recorded-a",
  pointEstimate: 13.4,
  ciLow: 12,
  ciHigh: 15,
  predictionDistribution: undefined,
  predictionRun: {
    ...metadata,
    runLabel: "Recorded version A",
    model: "test-model-a",
    runAt: "2026-06-27T12:00:00Z",
  },
  drivers: ["Driver A"],
  reasoning: [
    { kind: "heading", text: "Recorded analysis A" },
    { kind: "text", text: "Explanation from version A." },
    {
      kind: "tool",
      tool: "python",
      call: "estimate = 13.4\nprint(estimate)",
      result: "13.4",
    },
    { kind: "forecast", point: 13.4, ciLow: 12, ciHigh: 15 },
  ],
  comparisonRuns: [
    {
      variantId: "recorded-b",
      label: "Recorded version B",
      pointEstimate: 14.2,
      ciLow: 13,
      ciHigh: 16,
      drivers: ["Driver B"],
      historicalContext: [
        { label: "2001", value: 13.6 },
        { label: "2002", value: 13.8 },
      ],
      predictionRun: {
        ...metadata,
        model: "test-model-b",
        runAt: "2026-06-28T12:00:00Z",
      },
      reasoning: [{ kind: "text", text: "Explanation from version B." }],
    },
  ],
};
const openStream = vi.fn();
const estimate = () =>
  screen.getByRole("region", { name: "Forecast estimate" });
const analysis = () => screen.getByRole("region", { name: "Analysis" });
function chooseRun(value: string) {
  fireEvent.change(screen.getByRole("combobox", { name: "Forecast version" }), {
    target: { value },
  });
}
const displayScore = (crps: number) =>
  ({
    crps,
    signedError: 0.4,
    absoluteError: 0.4,
    probabilityIntegralTransform: 0.55,
  }) as ResolvedForecastScore;

describe("ForecastRuntime published report", () => {
  beforeEach(() => {
    openStream.mockClear();
    vi.stubGlobal("EventSource", openStream);
  });
  afterEach(() => {
    cleanup();
    document.body.innerHTML = "";
    vi.unstubAllGlobals();
  });

  it("server-renders complete recorded content and hydrates without replay or API calls", () => {
    const element = <ForecastRuntime forecast={report} />;
    const container = document.createElement("div");
    container.innerHTML = renderToString(element);
    document.body.appendChild(container);
    const region = within(container).getByRole("region", {
      name: "Forecast estimate",
    });
    expect(region).toHaveTextContent("13.4%");
    const content = within(container).getByRole("region", { name: "Analysis" });
    expect(content).toHaveTextContent("Explanation from version A.");
    expect(content.querySelector("pre code")?.textContent).toBe(
      "estimate = 13.4\nprint(estimate)",
    );
    const chart = within(region).getByRole("img", { name: /Historical trend/ });
    expect(chart).toHaveTextContent("2025");
    expect(chart).not.toHaveTextContent("Sep 2026");
    render(element, { container, hydrate: true });
    expect(region).toHaveTextContent("13.4%");
    expect(content).toHaveTextContent("Driver A");
    expect(
      screen.queryByRole("button", { name: /^(pause|resume|skip|replay)$/i }),
    ).toBeNull();
    expect(openStream).not.toHaveBeenCalled();
  });

  it("switches captured evidence with the selected forecast version", () => {
    render(
      <ForecastRuntime
        forecast={report}
        toolEvidence={{
          "recorded-a": {
            status: "available",
            artifacts: [
              {
                stage: "forecast",
                artifactPath: "records/thesis-analyst/a/tool_evidence.json",
                artifactSha256: "a".repeat(64),
                verificationPath:
                  "records/thesis-analyst/a/tool_evidence_verification.json",
                calls: [],
              },
            ],
          },
          "recorded-b": { status: "missing" },
        }}
      />,
    );
    const evidence = () =>
      screen.getByRole("region", { name: "Tool evidence" });
    expect(evidence()).toHaveTextContent("Archive integrity checked");
    expect(analysis()).toHaveTextContent("Reported tool use");
    chooseRun("recorded-b");
    expect(evidence()).toHaveTextContent("no captured tool responses");
    expect(
      within(evidence()).queryByRole("link", { name: "Raw evidence ↗" }),
    ).toBeNull();
    chooseRun("recorded-a");
    expect(
      within(evidence()).getByRole("link", { name: "Raw evidence ↗" }),
    ).toHaveAttribute("href", expect.stringContaining("/a/tool_evidence.json"));
  });

  it("keeps visible data aligned with the selected immutable run identity", () => {
    render(<ForecastRuntime forecast={report} />);
    chooseRun("recorded-b");
    expect(estimate()).toHaveTextContent("14.2%");
    expect(estimate()).toHaveTextContent("test-model-b");
    expect(estimate().querySelector("time")).toHaveAttribute(
      "dateTime",
      "2026-06-28T12:00:00Z",
    );
    expect(analysis()).toHaveTextContent("Explanation from version B.");
    expect(analysis()).toHaveTextContent("Driver B");
    expect(analysis()).not.toHaveTextContent("Driver A");
    expect(
      within(estimate()).getByRole("img", { name: /Historical trend/ }),
    ).toHaveAttribute("aria-label", expect.stringContaining("14.2%"));
    expect(estimate()).toHaveTextContent("2001");
    fireEvent.click(screen.getByRole("button", { name: "Recorded version A" }));
    expect(
      screen.getByRole("combobox", { name: "Forecast version" }),
    ).toHaveValue("recorded-a");
    expect(estimate()).toHaveTextContent("13.4%");
    expect(estimate()).not.toHaveTextContent("2001");
  });

  it("shows the distribution instead of joining ambiguous background facts into a trend", () => {
    render(
      <ForecastRuntime
        forecast={{
          ...report,
          historicalContext: [
            { label: "latest_sa_thousands", value: 215 },
            { label: "latest_nsa_persons", value: 224583 },
          ],
        }}
      />,
    );
    expect(
      within(estimate()).queryByRole("img", { name: /Historical trend/ }),
    ).toBeNull();
    expect(
      within(estimate()).getByRole("img", {
        name: /Cumulative probability distribution/,
      }),
    ).toBeTruthy();
    expect(estimate()).not.toHaveTextContent(
      "A full probability distribution is not available",
    );
  });

  it("keeps outcome scores and interval coverage attached to each run", () => {
    render(
      <ForecastRuntime
        forecast={{
          ...report,
          resolvedOutcome: {
            value: 15.5,
            resolvedAt: "2026-09-15",
            source: "Test release",
          },
        }}
        runScores={{
          "recorded-a": displayScore(0.11),
          "recorded-b": displayScore(0.22),
        }}
      />,
    );
    expect(estimate()).toHaveTextContent("CRPS 0.11");
    expect(estimate()).toHaveTextContent("outside 80% interval");
    chooseRun("recorded-b");
    expect(estimate()).toHaveTextContent("CRPS 0.22");
    expect(estimate()).not.toHaveTextContent("CRPS 0.11");
    expect(estimate()).toHaveTextContent("inside 80% interval");
  });

  it("does not render illustrative estimates or offer them in history", () => {
    render(
      <ForecastRuntime forecast={{ ...source, comparisonRuns: undefined }} />,
    );
    expect(screen.getByText("No forecast available.")).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Forecast estimate" }),
    ).toBeNull();
    expect(screen.queryByText(/policyengine.simulate/)).toBeNull();
  });

  it("preserves reading order and complete activity details", () => {
    render(<ForecastRuntime forecast={report} />);
    const evidence = screen.getByRole("region", {
      name: "Sources and resolution",
    });
    const history = screen.getByRole("region", { name: "Forecast history" });
    expect(
      analysis().compareDocumentPosition(evidence) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      evidence.compareDocumentPosition(history) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    fireEvent.click(screen.getByText("Run details"));
    expect(
      screen.getByRole("heading", { name: "Activity artifacts" }),
    ).toBeVisible();
    fireEvent.click(screen.getByText("Complete original trace"));
    expect(screen.getAllByText("Explanation from version A.")).toHaveLength(2);
  });

  it("does not claim uncertainty for a point projection", () => {
    render(
      <ForecastRuntime
        forecast={{
          ...report,
          ciLow: 13.4,
          ciHigh: 13.4,
          resolvedOutcome: {
            value: 15.5,
            resolvedAt: "2026-09-15",
            source: "Test release",
          },
        }}
      />,
    );
    expect(estimate()).toHaveTextContent("Point projection");
    expect(estimate()).not.toHaveTextContent("80% prediction interval");
    expect(estimate()).not.toHaveTextContent("inside 80% interval");
    expect(estimate()).not.toHaveTextContent("outside 80% interval");
    expect(estimate()).not.toHaveTextContent("Probability distribution");
  });

  it("resets the selection when the target changes", () => {
    const { rerender } = render(<ForecastRuntime forecast={report} />);
    chooseRun("recorded-b");
    rerender(
      <ForecastRuntime forecast={{ ...report, slug: "another-target" }} />,
    );
    expect(
      screen.getByRole("combobox", { name: "Forecast version" }),
    ).toHaveValue("recorded-a");
    expect(analysis()).toHaveTextContent("Explanation from version A.");
  });
});
