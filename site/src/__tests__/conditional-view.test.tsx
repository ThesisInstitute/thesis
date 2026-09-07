import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
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
  reviewedOriginal,
  reviewedRevision,
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

  it("shows model attribution and unresolved review findings before the unchanged native chart", async () => {
    respond(reviewedRevision);
    const { container } = render(<ConditionalView id={reviewedRevision.id} />);
    const review = await screen.findByRole("heading", {
      name: "Review findings remain",
    });
    expect(
      screen.getByText(
        "This recorded revision still has a synthetic reasoning gap.",
      ),
    ).toBeVisible();
    expect(
      review.compareDocumentPosition(
        screen.getByRole("heading", { name: "Paired distributions" }),
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const identity = container.querySelector(
      ".lab-conditional-identity",
    ) as HTMLElement;
    expect(within(identity).getByText("test/requested-model")).toBeVisible();
    expect(
      within(identity).getByText("synthetic-returned-model"),
    ).toBeVisible();
    expect(
      within(identity).getByText(/Model authorship is unverified/),
    ).toBeVisible();
    expect(container.querySelectorAll('[data-point-count="201"]')).toHaveLength(
      3,
    );
    expect(
      screen.queryByText(/source.clean|approved estimate/i),
    ).not.toBeInTheDocument();
  });

  it("keeps original and revised numbers, links and full recorded feedback inspectable", async () => {
    const feedback =
      "Exact synthetic feedback.\n<em>This stays plain text.</em>";
    const report =
      "Exact synthetic review report, including its original limitations.";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string) => {
        if (
          path ===
          `/api/core${reviewedRevision.revision_history[1].feedback!.download_path}`
        )
          return new Response(feedback);
        if (
          path ===
          `/api/core${reviewedRevision.reviews[0].report.download_path}`
        )
          return new Response(report);
        return new Response(JSON.stringify(reviewedRevision));
      }),
    );
    const { container } = render(<ConditionalView id={reviewedRevision.id} />);
    await screen.findByRole("heading", { name: "Revision history" });
    const table = container.querySelector(
      ".lab-conditional-revisions",
    ) as HTMLElement;
    const rows = within(table).getAllByRole("row");
    expect(
      within(rows[1]).getByRole("link", { name: "Original attempt" }),
    ).toHaveAttribute("href", `/lab/conditionals/${reviewedOriginal.id}`);
    expect(within(rows[1]).getByText("7")).toBeVisible();
    expect(within(rows[1]).getByText("3–11")).toBeVisible();
    expect(within(rows[1]).getByText("4")).toBeVisible();
    expect(within(rows[2]).getByText("8")).toBeVisible();
    expect(within(rows[2]).getByText("6")).toBeVisible();
    expect(rows[2]).toHaveAttribute("aria-current", "true");
    expect(
      screen.getByText(/Revision relationship recorded retrospectively/),
    ).toBeVisible();
    fireEvent.click(
      screen.getByText(
        `Revision feedback · ${reviewedRevision.id.slice(0, 12)}`,
      ),
    );
    expect(
      await screen.findByText(/Exact synthetic feedback/),
    ).toHaveTextContent("<em>This stays plain text.</em>");
    expect(
      container.querySelector(".lab-conditional-artifact-text em"),
    ).toBeNull();
    fireEvent.click(screen.getByText("Full review report"));
    expect(await screen.findByText(report)).toBeVisible();
    expect(
      screen.getByRole("link", {
        name: "Review that prompted this revision →",
      }),
    ).toHaveAttribute(
      "href",
      `/lab/conditionals/${reviewedOriginal.id}#conditional-review-${reviewedOriginal.reviews[0].id}`,
    );
  });

  it("filters on the server and cancels a stale unfiltered next page", async () => {
    const other = {
      ...conditionalSummary,
      id: ids.agent,
      title: "Another synthetic model",
      requested_model: "models/other-version",
    };
    const options = [conditionalSummary.requested_model, other.requested_model];
    let finishOldPage!: (value: Response) => void;
    const fetcher = vi.fn((path: string) => {
      if (path.includes("after="))
        return new Promise<Response>((resolve) => {
          finishOldPage = resolve;
        });
      if (path.includes("requested_model="))
        return Promise.resolve(
          new Response(
            JSON.stringify({
              ...conditionalPage,
              requested_models: options,
              items: [other],
              total: 1,
            }),
          ),
        );
      return Promise.resolve(
        new Response(
          JSON.stringify({
            ...conditionalPage,
            requested_models: options,
            total: 2,
            next_cursor: ids.run,
          }),
        ),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    render(<ConditionalsView />);
    await screen.findByRole("link", { name: conditionalSummary.title });
    fireEvent.click(screen.getByRole("button", { name: /load more/i }));
    fireEvent.change(
      screen.getByRole("combobox", { name: "Requested model" }),
      { target: { value: other.requested_model } },
    );
    expect(
      await screen.findByRole("link", { name: other.title }),
    ).toBeVisible();
    expect(fetcher).toHaveBeenCalledWith(
      "/api/core/lab/conditionals?limit=20&requested_model=models%2Fother-version",
      expect.anything(),
    );
    expect(
      screen.getByRole("option", { name: conditionalSummary.requested_model }),
    ).toBeInTheDocument();
    finishOldPage(
      new Response(
        JSON.stringify({
          ...conditionalPage,
          requested_models: options,
          items: [conditionalSummary],
        }),
      ),
    );
    await waitFor(() =>
      expect(screen.getByText("1 of 1 loaded")).toBeVisible(),
    );
    expect(
      screen.queryByRole("link", { name: conditionalSummary.title }),
    ).not.toBeInTheDocument();
  });

  it("copies the actual current page URL, with an accessible fallback if clipboard access fails", async () => {
    respond(conditional);
    const copy = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: copy },
    });
    render(<ConditionalView id={conditional.id} />);
    const share = await screen.findByRole("button", { name: "Share" });
    fireEvent.click(share);
    await screen.findByText("Link copied");
    expect(copy).toHaveBeenCalledWith(window.location.href);
    copy.mockRejectedValueOnce(new Error("No clipboard"));
    fireEvent.click(share);
    expect(
      await screen.findByRole("textbox", { name: "Copy this link" }),
    ).toHaveValue(window.location.href);
  });
});
