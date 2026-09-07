"use client";

import { useId, useState } from "react";
import type { NumericCdf, TaskComparison } from "@/data/generated/thesis-lab";
import { axisLabels, niceAxis } from "./chart-axis";
import { ChartInspector } from "./ChartInspector";
import { deriveDensity } from "./density";
import { number, unit } from "./lab-ui";

/** Display-only data: a conditional curve does not imply an experiment or task. */
export interface DistributionCurve {
  id: string;
  label: string;
  distribution: NumericCdf;
  reference?: boolean;
  note?: string;
  version?: string;
}

/** Preserve the registered-task chart API while sharing only curve rendering. */
export function CdfChart({
  comparisons,
  outcome,
  unitName,
}: {
  comparisons: readonly TaskComparison[];
  outcome: number | null;
  unitName: string;
}) {
  return (
    <DistributionChart
      curves={comparisons.flatMap((row) =>
        row.distribution
          ? [
              {
                id: row.task.id,
                label: row.agent.label,
                distribution: row.distribution,
                reference: row.is_baseline,
                note: row.is_baseline ? "baseline" : undefined,
                version: row.selected_run?.id,
              },
            ]
          : [],
      )}
      outcome={outcome}
      unitName={unitName}
    />
  );
}

/** Draw original CDF points or probability-preserving binned density. */
export function DistributionChart({
  curves,
  outcome = null,
  unitName,
  seriesLabel = "loaded methods",
}: {
  curves: readonly DistributionCurve[];
  outcome?: number | null;
  unitName: string;
  seriesLabel?: string;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const [focused, setFocused] = useState<string | null>(null);
  const [view, setView] = useState<"cdf" | "pdf">("cdf");
  if (curves.length === 0)
    return (
      <div className="lab-notice">
        No selected distribution is available for the loaded methods.
      </div>
    );
  let min = outcome ?? Infinity;
  let max = outcome ?? -Infinity;
  for (const row of curves)
    for (const point of row.distribution.points) {
      min = Math.min(min, point.value);
      max = Math.max(max, point.value);
    }
  const xAxis = niceAxis(min, max);
  const { lower, upper } = xAxis;
  const x = (value: number) => 68 + ((value - lower) / (upper - lower)) * 824;
  const densities = curves.map((row) =>
    deriveDensity(row.distribution.points, 5),
  );
  const densityMax = densities.reduce(
    (peak, intervals) =>
      intervals?.reduce((max, p) => Math.max(max, p.density), peak) ?? peak,
    0,
  );
  const yAxis = niceAxis(0, view === "pdf" && densityMax > 0 ? densityMax : 1);
  const yMax = yAxis.upper;
  const xLabels = axisLabels(xAxis.ticks);
  const yLabels = axisLabels(
    yAxis.ticks.map((value) => (view === "cdf" ? value * 100 : value)),
  );
  const y = (value: number) => 310 - (value / yMax) * 276;
  const densityUnit =
    unitName === "percent" ? "percentage point" : unit(unitName);
  return (
    <figure className="lab-chart">
      <div className="lab-chart-toolbar">
        <span>
          {view === "cdf"
            ? "Cumulative probability"
            : `Binned density · per ${densityUnit}`}
        </span>
        <div
          className="lab-chart-toggle"
          role="group"
          aria-label="Distribution view"
        >
          {(["cdf", "pdf"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              aria-pressed={view === mode}
              onClick={() => setView(mode)}
              title={
                mode === "cdf"
                  ? "Cumulative distribution function"
                  : "Probability density function"
              }
            >
              {mode.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
      <ChartInspector
        key={`${view}:${lower}:${upper}:${curves.map((row) => `${row.id}:${row.version}`).join(":")}`}
        lower={lower}
        upper={upper}
        view={view}
        unitName={unitName}
        curves={curves}
        densities={densities}
      >
        {({ value: inspectedValue, plotRef, onPointerMove, onPointerDown }) => (
          <svg
            role="img"
            aria-labelledby={`${titleId} ${descriptionId}`}
            viewBox="0 0 940 366"
          >
            <title id={titleId}>
              {view === "cdf"
                ? "Forecast cumulative distributions"
                : "Forecast probability densities"}
            </title>
            <desc id={descriptionId}>
              {view === "cdf"
                ? "Each curve plots all 201 original CDF points. The vertical axis is the probability the outcome is at or below the horizontal value."
                : `An approximate density in 40 bins, each averaging five adjacent CDF intervals to reduce rounding noise. Every bin preserves the probability between its stored endpoints. The vertical axis is density per ${densityUnit}.`}{" "}
              {curves.length} {seriesLabel}.
              {outcome !== null && ` Official outcome: ${outcome} ${unitName}.`}
            </desc>
            {yAxis.ticks.map((value, index) => (
              <g key={value}>
                <line
                  x1="68"
                  x2="892"
                  y1={y(value)}
                  y2={y(value)}
                  className="lab-chart-grid"
                />
                <text data-axis="y" x="52" y={y(value) + 4} textAnchor="end">
                  {view === "cdf" ? `${yLabels[index]}%` : yLabels[index]}
                </text>
              </g>
            ))}
            {xAxis.ticks.map((value, index) => (
              <text
                data-axis="x"
                key={value}
                x={x(value)}
                y="338"
                textAnchor="middle"
              >
                {xLabels[index]}
              </text>
            ))}
            <text x="480" y="362" textAnchor="middle">
              {unit(unitName)}
            </text>
            {curves.map((row, i) => {
              const intervals = densities[i];
              if (view === "pdf" && !intervals) return null;
              const path =
                view === "cdf"
                  ? row
                      .distribution!.points.map(
                        (point, index) =>
                          `${index === 0 ? "M" : "L"}${x(point.value).toFixed(4)},${y(point.probability).toFixed(4)}`,
                      )
                      .join(" ")
                  : [
                      `M${x(intervals![0].lower).toFixed(4)},${y(0).toFixed(4)}`,
                      ...intervals!.flatMap((interval) => [
                        `L${x(interval.lower).toFixed(4)},${y(interval.density).toFixed(4)}`,
                        `L${x(interval.upper).toFixed(4)},${y(interval.density).toFixed(4)}`,
                      ]),
                      `L${x(intervals!.at(-1)!.upper).toFixed(4)},${y(0).toFixed(4)}`,
                    ].join(" ");
              return (
                <path
                  key={row.id}
                  data-testid={`${view}-${row.id}`}
                  data-point-count={row.distribution.points.length}
                  data-segment-count={
                    view === "pdf" ? intervals!.length : undefined
                  }
                  d={path}
                  fill={view === "pdf" && !row.reference ? "#783d68" : "none"}
                  fillOpacity={0.07}
                  stroke={row.reference ? "#797780" : "#783d68"}
                  strokeWidth={
                    focused === row.id ? 3.5 : view === "pdf" ? 1.6 : 2.4
                  }
                  strokeDasharray={
                    row.reference ? "5 5" : i > 1 ? `${4 + i * 2} 3` : undefined
                  }
                  opacity={focused !== null && focused !== row.id ? 0.23 : 1}
                  className="lab-curve"
                />
              );
            })}
            {outcome !== null && (
              <g>
                <line
                  x1={x(outcome)}
                  x2={x(outcome)}
                  y1="24"
                  y2="310"
                  className="lab-outcome-line"
                />
                <text x={x(outcome)} y="16" textAnchor="middle">
                  Observed {number(outcome)}
                </text>
              </g>
            )}
            {inspectedValue !== null && (
              <line
                x1={x(inspectedValue)}
                x2={x(inspectedValue)}
                y1="34"
                y2="310"
                className="lab-chart-crosshair"
              />
            )}
            <rect
              ref={plotRef}
              data-testid="chart-inspection-area"
              x="68"
              y="34"
              width="824"
              height="276"
              fill="transparent"
              onPointerMove={onPointerMove}
              onPointerDown={onPointerDown}
            />
          </svg>
        )}
      </ChartInspector>
      {view === "pdf" &&
        curves.map(
          (row, i) =>
            densities[i] === null && (
              <p className="lab-notice" key={row.id}>
                {row.label}: density is unavailable at this numeric scale. View
                the CDF.
              </p>
            ),
        )}
      <figcaption>
        <div className="lab-chart-legend">
          {curves.map((row, i) => (
            <button
              key={row.id}
              type="button"
              onMouseEnter={() => setFocused(row.id)}
              onMouseLeave={() => setFocused(null)}
              onFocus={() => setFocused(row.id)}
              onBlur={() => setFocused(null)}
              aria-label={`Emphasize ${row.label}`}
            >
              <span
                className={
                  row.reference
                    ? "lab-legend-line lab-baseline"
                    : "lab-legend-line"
                }
                style={i > 1 ? { borderTopStyle: "dashed" } : undefined}
              />
              {row.label}
              {row.note && <small>{row.note}</small>}
            </button>
          ))}
        </div>
        <p>
          {view === "cdf"
            ? "Original 201-point distributions"
            : "40 bins · approximate density · each bin preserves its probability"}{" "}
          · {curves.length} {seriesLabel}
        </p>
      </figcaption>
    </figure>
  );
}
