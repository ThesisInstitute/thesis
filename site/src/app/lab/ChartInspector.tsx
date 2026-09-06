"use client";

import {
  useEffect,
  useId,
  useRef,
  useState,
  type PointerEvent,
  type ReactNode,
  type RefObject,
} from "react";
import type { TaskComparison } from "@/data/generated/thesis-lab";
import { axisLabel } from "./chart-axis";
import { cdfAt, densityBinAt, inspectionLabels } from "./chart-inspection";
import type { DensityInterval } from "./density";
import { unit } from "./lab-ui";

const tooltipLabel = (value: number) => axisLabel(value, 5);

type Inspection = {
  share: number;
  left: number;
  source: "pointer" | "touch" | "keyboard";
};
type PlotInteraction = {
  value: number | null;
  plotRef: RefObject<SVGRectElement | null>;
  onPointerMove: (event: PointerEvent<SVGRectElement>) => void;
  onPointerDown: (event: PointerEvent<SVGRectElement>) => void;
};

export function ChartInspector({
  lower,
  upper,
  view,
  unitName,
  comparisons,
  densities,
  children,
}: {
  lower: number;
  upper: number;
  view: "cdf" | "pdf";
  unitName: string;
  comparisons: readonly TaskComparison[];
  densities: readonly (DensityInterval[] | null)[];
  children: (interaction: PlotInteraction) => ReactNode;
}) {
  const tooltipId = useId();
  const helpId = useId();
  const containerRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<SVGRectElement>(null);
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const share = inspection?.share ?? 0.5;
  const value = lower + share * (upper - lower);
  const step = (upper - lower) / 200;
  const valueLabel = inspectionLabels([
    Math.max(lower, value - step),
    value,
    Math.min(upper, value + step),
  ])[1];
  const densityUnit =
    unitName === "percent" ? "percentage point" : unit(unitName);

  useEffect(() => {
    const dismiss = (event: KeyboardEvent) => {
      if (event.key === "Escape") setInspection(null);
    };
    const resize = () => setInspection(null);
    document.addEventListener("keydown", dismiss);
    window.addEventListener("resize", resize);
    return () => {
      document.removeEventListener("keydown", dismiss);
      window.removeEventListener("resize", resize);
    };
  }, []);

  function inspect(nextShare: number, source: Inspection["source"]) {
    const container = containerRef.current?.getBoundingClientRect();
    const plot = plotRef.current?.getBoundingClientRect();
    const clamped = Math.max(0, Math.min(1, nextShare));
    const pointerX =
      container && plot ? plot.left + clamped * plot.width - container.left : 0;
    const width = container?.width ?? 300;
    const tooltipWidth = Math.min(300, width - 16);
    const preferred =
      pointerX > width / 2 ? pointerX - tooltipWidth - 16 : pointerX + 16;
    setInspection({
      share: clamped,
      source,
      left: Math.max(8, Math.min(preferred, width - tooltipWidth - 8)),
    });
  }

  function pointer(event: PointerEvent<SVGRectElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width > 0)
      inspect(
        (event.clientX - rect.left) / rect.width,
        event.pointerType === "touch" ? "touch" : "pointer",
      );
  }

  return (
    <div
      className="lab-chart-interactive"
      ref={containerRef}
      onPointerLeave={(event) => {
        if (event.pointerType !== "touch")
          setInspection((current) =>
            current?.source === "pointer" ? null : current,
          );
      }}
      onPointerCancel={() => setInspection(null)}
    >
      <input
        type="range"
        className="lab-chart-keyboard"
        aria-label="Inspect forecast value"
        aria-describedby={inspection ? `${helpId} ${tooltipId}` : helpId}
        aria-valuetext={`${valueLabel} ${unit(unitName)}`}
        min={lower}
        max={upper}
        step={step}
        value={value}
        onFocus={() => inspect(share, "keyboard")}
        onChange={(event) =>
          inspect(
            (Number(event.target.value) - lower) / (upper - lower),
            "keyboard",
          )
        }
        onBlur={() =>
          setInspection((current) =>
            current?.source === "keyboard" ? null : current,
          )
        }
      />
      <span id={helpId} className="lab-chart-sr-only">
        Use arrow keys to inspect values. Escape dismisses the tooltip.
      </span>
      <div className="lab-chart-scroll" onScroll={() => setInspection(null)}>
        {children({
          value: inspection ? value : null,
          plotRef,
          onPointerMove: pointer,
          onPointerDown: pointer,
        })}
      </div>
      {inspection && (
        <div className="lab-chart-tooltip" style={{ left: inspection.left }}>
          <button
            type="button"
            tabIndex={-1}
            className="lab-tooltip-close"
            aria-label="Close chart tooltip"
            onClick={() => setInspection(null)}
          >
            ×
          </button>
          <div
            id={tooltipId}
            role="tooltip"
            aria-live={inspection.source === "keyboard" ? "polite" : "off"}
            aria-atomic="true"
          >
            <strong>
              {valueLabel} {unit(unitName)}
            </strong>
            <span className="lab-tooltip-context">
              {view === "cdf"
                ? "Probability at or below this value"
                : "Displayed density bins"}
            </span>
            {comparisons.map((row, index) => {
              const bins = densities[index];
              const bin = bins ? densityBinAt(bins, value) : null;
              const bounds = bin
                ? inspectionLabels([bin.lower, bin.upper])
                : null;
              const mass = bin
                ? cdfAt(row.distribution!.points, bin.upper) -
                  cdfAt(row.distribution!.points, bin.lower)
                : 0;
              return (
                <div key={row.task.id} className="lab-tooltip-method">
                  <span className="lab-tooltip-name">
                    <i
                      className={
                        row.is_baseline
                          ? "lab-legend-line lab-baseline"
                          : "lab-legend-line"
                      }
                    />
                    {row.agent.label}
                  </span>
                  {view === "cdf" ? (
                    <b>
                      {tooltipLabel(
                        cdfAt(row.distribution!.points, value) * 100,
                      )}
                      %
                    </b>
                  ) : bins === null ? (
                    <span>Density unavailable</span>
                  ) : bin ? (
                    <>
                      <b>
                        {tooltipLabel(bin.density)} per {densityUnit}
                      </b>
                      <span>
                        {bounds![0]}–{bounds![1]} {unit(unitName)} ·{" "}
                        {tooltipLabel(mass * 100)}% probability
                      </span>
                    </>
                  ) : (
                    <span>0 per {densityUnit} · outside forecast support</span>
                  )}
                </div>
              );
            })}
            {view === "cdf" && (
              <span className="lab-tooltip-context">
                Interpolated from the original CDF points
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
