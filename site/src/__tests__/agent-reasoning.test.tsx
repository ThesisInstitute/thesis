import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, within } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { AgentReasoning } from "@/components/AgentReasoning";
import type { ReasoningStep } from "@/data/forecast-cells";

const call = 'census.lookup({ year: 2025, population: "children" })';
const result = '{\n  "point": 13.0,\n  "interval": [11.9, 14.3]\n}';
const steps: ReasoningStep[] = [
  { kind: "heading", text: "Evidence and estimate" },
  {
    kind: "text",
    text: "The complete saved explanation is available immediately.",
  },
  { kind: "math", text: "Prior/update/interval: 13.4 - 0.4 = 13.0" },
  { kind: "tool", tool: "census.lookup", call, result },
  { kind: "forecast", point: 13, ciLow: 11.9, ciHigh: 14.3 },
];

function serverRender(element: React.ReactNode) {
  const container = document.createElement("div");
  container.innerHTML = renderToString(element);
  return container;
}

describe("AgentReasoning static report", () => {
  afterEach(cleanup);

  it("includes every step and the full tool code blocks in initial server HTML", () => {
    const container = serverRender(
      <AgentReasoning steps={steps} unit="percent" />,
    );
    const report = within(container);

    expect(
      report.getByRole("heading", { name: /Evidence and estimate/ }),
    ).toBeTruthy();
    expect(
      report.getByText(
        "The complete saved explanation is available immediately.",
      ),
    ).toBeTruthy();
    expect(
      report.getByText("Prior/update/interval: 13.4 - 0.4 = 13.0"),
    ).toBeTruthy();
    const codeBlocks = [...container.querySelectorAll("pre code")];
    expect(codeBlocks).toHaveLength(2);
    expect(codeBlocks[0].textContent).toBe(call);
    expect(codeBlocks[1].textContent).toContain(result);
    expect(report.getByText("▸ Reported tool use: census.lookup")).toBeTruthy();
    expect(report.queryByText(/recorded source check/)).toBeNull();
    expect(report.getByText("13.0%")).toBeTruthy();
    expect(report.getByText("[11.9% · 14.3%]")).toBeTruthy();
    expect(
      report.queryByRole("button", { name: /^(pause|resume|skip|replay)$/i }),
    ).toBeNull();
  });

  it("preserves all report content when hydrated", () => {
    const element = <AgentReasoning steps={steps} unit="percent" />;
    const container = serverRender(element);
    document.body.appendChild(container);
    const serverText = container.textContent;
    render(element, { container, hydrate: true });

    expect(container.textContent).toBe(serverText);
    expect(
      within(container).getByText(
        "The complete saved explanation is available immediately.",
      ),
    ).toBeTruthy();
    expect(within(container).queryByRole("button")).toBeNull();
  });

  it.each([
    ["illustrative", /the tool calls shown were not executed/],
    ["recorded_run", /steps reflect real activity without archived receipts/],
  ] as const)(
    "keeps the %s provenance disclosure alongside complete results",
    (provenance, disclosure) => {
      const container = serverRender(
        <AgentReasoning steps={steps} unit="percent" provenance={provenance} />,
      );
      expect(within(container).getByText(disclosure)).toBeTruthy();
      expect(container.querySelectorAll("pre code")[1].textContent).toContain(
        result,
      );
      expect(within(container).getByText("13.0%")).toBeTruthy();
    },
  );
});
