import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConditionalView, ConditionalsView } from "@/app/lab/ConditionalViews";
import {
  conditional,
  conditionalPage,
  conditionalSummary,
  expiredConditional,
  expiredSummary,
  unsuccessful,
} from "./conditional-fixtures";
import { ids } from "./lab-fixtures";
vi.mock("next/navigation", () => ({ usePathname: () => "/lab/conditionals" }));
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function respond(value: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify(value), {
          headers: { "content-type": "application/json" },
        }),
    ),
  );
}

describe("paired conditional working surfaces", () => {
  it("draws all three native curves, exposes CDF/PDF inspection and reports only a median difference", async () => {
    respond(conditional);
    const { container } = render(<ConditionalView id={ids.task} />);
    await screen.findByRole("heading", { name: conditional.title });
    const curves = container.querySelectorAll('[data-testid^="cdf-"]');
    expect(curves).toHaveLength(3);
    for (const curve of curves)
      expect(curve).toHaveAttribute("data-point-count", "201");
    expect(screen.getByText("+3 index points")).toBeVisible();
    expect(screen.getByText(/do not establish a causal effect/)).toBeVisible();
    expect(
      screen.getByText("Exploratory · local operator · scoring not registered"),
    ).toBeVisible();
    expect(screen.getAllByText("2024")).toHaveLength(1);
    expect(
      screen.getByText("Synthetic condition A is met before the deadline."),
    ).toBeVisible();
    expect(screen.getByText("Synthetic assumption B.")).toBeVisible();
    fireEvent.focus(screen.getByRole("slider"));
    fireEvent.change(screen.getByRole("slider"), { target: { value: "5" } });
    expect(within(screen.getByRole("tooltip")).getByText("50%")).toBeVisible();
    expect(within(screen.getByRole("tooltip")).getByText("30%")).toBeVisible();
    expect(within(screen.getByRole("tooltip")).getByText("60%")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "PDF" }));
    expect(container.querySelectorAll('[data-testid^="pdf-"]')).toHaveLength(3);
    expect(
      container.querySelectorAll('[data-segment-count="40"]'),
    ).toHaveLength(3);
    expect(
      screen.getByRole("link", { name: "Archived source ↓" }),
    ).toHaveAttribute("href", `/api/core/artifacts/${ids.artifact}`);
    fireEvent.click(
      screen.getByText("Prompt, response and execution artifacts"),
    );
    expect(screen.getByRole("link", { name: "validation ↓" })).toHaveAttribute(
      "href",
      `/api/core/artifacts/${ids.artifact}`,
    );
  });
  it.each(["failed", "unknown"] as const)(
    "keeps %s attempts visible without drawing distributions",
    async (state) => {
      respond(unsuccessful(state));
      render(<ConditionalView id={ids.task} />);
      await screen.findByRole("heading", { name: conditional.title });
      expect(screen.getByText("No validated paired forecast")).toBeVisible();
      expect(screen.getAllByText(state).length).toBeGreaterThan(0);
      expect(
        screen.queryByRole("button", { name: "CDF" }),
      ).not.toBeInTheDocument();
      expect(
        screen.getByText("Prompt, response and execution artifacts"),
      ).toBeVisible();
      expect(
        screen.getByRole("heading", { name: "Shared history" }),
      ).toBeVisible();
    },
  );
  it("keeps expired unrecovered attempts visible in the list and detail", async () => {
    respond({
      ...conditionalPage,
      generated_at: expiredConditional.generated_at,
      items: [conditionalSummary, expiredSummary],
      total: 2,
    });
    const list = render(<ConditionalsView />);
    expect(
      await screen.findByRole("link", { name: expiredSummary.title }),
    ).toBeVisible();
    expect(screen.getByText("unknown")).toBeVisible();
    expect(screen.getByText("2 of 2 loaded")).toBeVisible();
    list.unmount();
    respond(expiredConditional);
    render(<ConditionalView id={expiredSummary.id} />);
    await screen.findByRole("heading", { name: expiredSummary.title });
    expect(screen.getByText("No validated paired forecast")).toBeVisible();
    expect(
      screen.getByText(/No confirmed result was recorded before the deadline/),
    ).toBeVisible();
    expect(screen.getByText("2026-09-05 12:05:00 UTC")).toBeVisible();
    const finished = screen.getByText("Finished").closest("div")!;
    expect(within(finished).getByText("Not reported")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "CDF" }),
    ).not.toBeInTheDocument();
  });
  it("lists successful, failed and unknown attempts without manufacturing experiment membership", async () => {
    respond({
      ...conditionalPage,
      items: [
        conditionalSummary,
        {
          ...conditionalSummary,
          id: ids.agent,
          title: "Failed synthetic attempt",
          execution_state: "failed",
          error_code: "invalid_response",
        },
        {
          ...conditionalSummary,
          id: ids.run,
          title: "Unknown synthetic attempt",
          execution_state: "unknown",
          error_code: "attempt_expired",
        },
      ],
      total: 3,
    });
    render(<ConditionalsView />);
    expect(
      await screen.findByRole("link", { name: "Failed synthetic attempt" }),
    ).toHaveAttribute("href", `/lab/conditionals/${ids.agent}`);
    expect(
      screen.getByRole("link", { name: "Unknown synthetic attempt" }),
    ).toBeVisible();
    expect(screen.getByText("3 of 3 loaded")).toBeVisible();
    expect(
      screen.queryByRole("link", { name: /experiment/i }),
    ).not.toBeInTheDocument();
  });
  it("uses an honest empty state for this unregistered lane", async () => {
    respond({ ...conditionalPage, items: [], total: 0 });
    render(<ConditionalsView />);
    expect(
      await screen.findByText("No conditional attempts yet"),
    ).toBeVisible();
    expect(
      screen.queryByText(/Registered records will appear/),
    ).not.toBeInTheDocument();
  });
});
