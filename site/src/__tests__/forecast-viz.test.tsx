import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ForecastTrend, ForecastViz } from "@/components/ForecastViz";
import {
  buildNumericCdfFromInterval,
  buildNumericCdfFromQuantiles,
} from "@/data/prediction-distribution";

const forecast = {
  point: 13,
  ciLow: 11.9,
  ciHigh: 14.3,
  unit: "percent" as const,
};

afterEach(cleanup);

describe("ForecastTrend", () => {
  it("can show a point projection without claiming an uncertainty interval", () => {
    const props = {
      ...forecast,
      history: [{ label: "2024", value: 13.4 }],
      targetLabel: "2025",
    };
    const { container, rerender } = render(<ForecastTrend {...props} />);
    expect(screen.getByText("80% interval")).toBeVisible();
    const intervalLines = () =>
      container.querySelectorAll('line[stroke="var(--color-accent)"]');
    expect(intervalLines()).toHaveLength(2);
    const originalPaths = [...container.querySelectorAll("path")].map((path) =>
      path.getAttribute("d"),
    );

    rerender(<ForecastTrend {...props} showInterval={false} />);
    expect(screen.queryByText("80% interval")).toBeNull();
    expect(intervalLines()).toHaveLength(0);
    expect(screen.getByRole("img")).toHaveAccessibleName(
      "Historical trend ending with forecast 13.0%",
    );
    expect(
      [...container.querySelectorAll("path")].map((path) =>
        path.getAttribute("d"),
      ),
    ).toEqual(originalPaths);
    expect(screen.getByText("13.0%")).toBeVisible();
    expect(container.querySelectorAll("circle")).toHaveLength(2);
  });
});

describe("ForecastViz", () => {
  it("shows only the point and interval when no distribution was recorded", () => {
    const { container } = render(<ForecastViz {...forecast} />);

    expect(screen.getByRole("img")).toHaveAccessibleName(
      "Forecast 13.0%; 80% interval 11.9% to 14.3%",
    );
    expect(container.querySelector("path")).toBeNull();
    expect(
      screen.getByText(/full probability distribution is not available/),
    ).toBeVisible();
  });

  it("plots every stored CDF point without inventing a symmetric density", () => {
    const distribution = buildNumericCdfFromQuantiles({
      pointEstimate: 13,
      quantiles: [
        { probability: 0.1, value: 11.9 },
        { probability: 0.25, value: 12.8 },
        { probability: 0.5, value: 13 },
        { probability: 0.75, value: 13.2 },
        { probability: 0.9, value: 14.3 },
      ],
    });
    const { container } = render(
      <ForecastViz {...forecast} distribution={distribution} />,
    );
    const path = container.querySelector("path")!;
    const coordinates = path.getAttribute("d")!.match(/[ML] [\d.]+ [\d.]+/g)!;
    expect(coordinates).toHaveLength(distribution.points.length);
    expect(coordinates[0]).toBe("M 60.00 215.00");
    expect(coordinates.at(-1)).toBe("L 615.00 20.00");
    // A point well away from the median checks that the stored asymmetric
    // probabilities, rather than a Gaussian approximation, set the height.
    const stored = distribution.points[50];
    const expectedX =
      60 +
      ((stored.value - distribution.support.lower) /
        (distribution.support.upper - distribution.support.lower)) *
        555;
    expect(coordinates[50]).toBe(
      `L ${expectedX.toFixed(2)} ${(20 + (1 - stored.probability) * 195).toFixed(2)}`,
    );
    expect(path).toHaveAttribute("fill", "none");
    expect(screen.getByText("Cumulative probability")).toBeVisible();
    expect(
      screen.getByText("Chance that the outcome is at or below each value."),
    ).toBeVisible();
    expect(screen.getByRole("img")).toHaveAccessibleName(
      /Cumulative probability distribution/,
    );
    expect(
      screen.getByText(
        "Based on probabilities reported by the forecasting agent.",
      ),
    ).toBeVisible();
    expect(screen.getByText(/Shaded band: 80% interval/)).toHaveTextContent(
      "11.9%–14.3%",
    );
  });

  it("discloses when the CDF was derived from an interval", () => {
    const distribution = buildNumericCdfFromInterval({
      pointEstimate: forecast.point,
      ciLow: forecast.ciLow,
      ciHigh: forecast.ciHigh,
    });
    render(<ForecastViz {...forecast} distribution={distribution} />);

    expect(
      screen.getByText(/Derived from the point estimate and 80% interval/),
    ).toBeVisible();
    expect(screen.getByRole("img")).toHaveAccessibleName(
      /the agent did not report a full distribution/,
    );
  });

  it("keeps compact cards as interval bars even when a CDF is available", () => {
    const distribution = buildNumericCdfFromInterval({
      pointEstimate: forecast.point,
      ciLow: forecast.ciLow,
      ciHigh: forecast.ciHigh,
    });
    const { container } = render(
      <ForecastViz {...forecast} distribution={distribution} size="compact" />,
    );

    expect(container.querySelector("svg")).toBeNull();
    expect(screen.getByText("13.0%")).toBeVisible();
    expect(screen.queryByText("Cumulative probability")).toBeNull();
  });

  it("retains historical anchors in the interval-only chart", () => {
    render(
      <ForecastViz {...forecast} history={[{ label: "2024", value: 13.4 }]} />,
    );

    expect(screen.getByTitle("2024: 13.4%")).toBeInTheDocument();
    expect(screen.getByText("13.4%")).toBeVisible();
  });
});
