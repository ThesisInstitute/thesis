import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { CdfChart } from "@/app/lab/CdfChart";
import {
  cdfAt,
  densityBinAt,
  inspectionLabels,
} from "@/app/lab/chart-inspection";
import { comparison } from "./lab-fixtures";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("forecast inspection", () => {
  it("preserves distinct labels for narrow ranges at large offsets", () => {
    expect(inspectionLabels([1e6, 1e6 + 0.25])).toEqual([
      "1e+6",
      "1.00000025e+6",
    ]);
    const offset = {
      ...comparison,
      distribution: {
        ...comparison.distribution!,
        points: comparison.distribution!.points.map((p) => ({
          ...p,
          value: p.value + 1e6,
        })),
        support: { lower: 1e6, upper: 1e6 + 10 },
      },
    };
    render(
      <CdfChart comparisons={[offset]} outcome={null} unitName="percent" />,
    );
    fireEvent.click(screen.getByRole("button", { name: "PDF", exact: true }));
    fireEvent.change(
      screen.getByRole("slider", { name: "Inspect forecast value" }),
      { target: { value: "1000002.5" } },
    );
    expect(
      within(screen.getByRole("tooltip")).getByText(
        /1.0000025e\+6–1.00000275e\+6/,
      ),
    ).toBeVisible();
  });
  it("interpolates the original CDF and handles knots, plateaus and tails", () => {
    const points = [
      { value: 0, probability: 0 },
      { value: 2, probability: 0.5 },
      { value: 3, probability: 0.5 },
      { value: 5, probability: 1 },
    ];
    expect(cdfAt(points, 1)).toBe(0.25);
    expect(cdfAt(points, 2)).toBe(0.5);
    expect(cdfAt(points, 2.5)).toBe(0.5);
    expect(cdfAt(points, -1)).toBe(0);
    expect(cdfAt(points, 6)).toBe(1);
  });

  it("uses the right-hand bin at internal boundaries and includes the final endpoint", () => {
    const bins = [
      { lower: 0, upper: 2, density: 0.25 },
      { lower: 2, upper: 3, density: 0.5 },
    ];
    expect(densityBinAt(bins, 2)).toBe(bins[1]);
    expect(densityBinAt(bins, 3)).toBe(bins[1]);
    expect(densityBinAt(bins, -1)).toBeNull();
    expect(densityBinAt(bins, 4)).toBeNull();
  });

  it("maps a scaled plot rectangle to probability and dismisses on mouse leave", () => {
    const { container } = render(
      <CdfChart comparisons={[comparison]} outcome={null} unitName="percent" />,
    );
    const plot = screen.getByTestId("chart-inspection-area");
    vi.spyOn(plot, "getBoundingClientRect").mockReturnValue({
      left: 100,
      width: 400,
    } as DOMRect);
    fireEvent.pointerMove(plot, { clientX: 300, pointerType: "mouse" });
    expect(within(screen.getByRole("tooltip")).getByText("50%")).toBeVisible();
    expect(container.querySelector(".lab-chart-crosshair")).toBeInTheDocument();
    fireEvent.pointerLeave(container.querySelector(".lab-chart-interactive")!, {
      pointerType: "mouse",
    });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("supports touch inspection, native keyboard changes, Escape and view resets", () => {
    const { rerender, container } = render(
      <CdfChart comparisons={[comparison]} outcome={null} unitName="percent" />,
    );
    const plot = screen.getByTestId("chart-inspection-area");
    vi.spyOn(plot, "getBoundingClientRect").mockReturnValue({
      left: 100,
      width: 400,
    } as DOMRect);
    fireEvent.pointerDown(plot, { clientX: 200, pointerType: "touch" });
    fireEvent.pointerUp(plot, { pointerType: "touch" });
    fireEvent.pointerLeave(container.querySelector(".lab-chart-interactive")!, {
      pointerType: "touch",
    });
    expect(within(screen.getByRole("tooltip")).getByText("25%")).toBeVisible();
    const control = screen.getByRole("slider", {
      name: "Inspect forecast value",
    });
    fireEvent.focus(control);
    fireEvent.change(control, { target: { value: "7.5" } });
    expect(within(screen.getByRole("tooltip")).getByText("75%")).toBeVisible();
    fireEvent.keyDown(control, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent.focus(control);
    fireEvent.click(screen.getByRole("button", { name: "PDF", exact: true }));
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent.focus(
      screen.getByRole("slider", { name: "Inspect forecast value" }),
    );
    expect(screen.getByRole("tooltip")).toBeVisible();
    expect(screen.getByRole("tooltip")).toHaveAttribute("aria-live", "polite");
    expect(
      screen.getByRole("button", { name: "Close chart tooltip" }),
    ).toHaveAttribute("tabindex", "-1");
    rerender(
      <CdfChart
        comparisons={[
          { ...comparison, task: { ...comparison.task, id: "new-task" } },
        ]}
        outcome={null}
        unitName="percent"
      />,
    );
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("reports each method's bin at the same x and distinguishes outside support", () => {
    const shifted = {
      ...comparison,
      task: { ...comparison.task, id: "shifted" },
      agent: { ...comparison.agent, label: "Shifted method" },
      distribution: {
        ...comparison.distribution!,
        points: comparison.distribution!.points.map((p) => ({
          ...p,
          value: p.value + 5,
        })),
        support: { lower: 5, upper: 15 },
      },
    };
    render(
      <CdfChart
        comparisons={[comparison, shifted]}
        outcome={null}
        unitName="percent"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "PDF", exact: true }));
    fireEvent.change(
      screen.getByRole("slider", { name: "Inspect forecast value" }),
      { target: { value: "2.5" } },
    );
    const tooltip = within(screen.getByRole("tooltip"));
    expect(tooltip.getByText("0.1 per percentage point")).toBeVisible();
    expect(tooltip.getByText("2.5–2.75 % · 2.5% probability")).toBeVisible();
    expect(
      tooltip.getByText("0 per percentage point · outside forecast support"),
    ).toBeVisible();
  });
});
