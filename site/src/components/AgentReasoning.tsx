import type { ReasoningStep, Unit } from "@/data/forecast-cells";
import { formatValue } from "@/data/forecast-cells";
import type { TraceProvenance } from "@/data/trace-provenance";

interface AgentReasoningProps {
  steps: ReasoningStep[];
  unit: Unit;
  provenance?: TraceProvenance;
}

export function AgentReasoning({
  steps,
  unit,
  provenance = "activity_backed",
}: AgentReasoningProps) {
  return (
    <article
      aria-label="Forecast report content"
      className="rounded-xl border bg-[var(--theme-bg-elevated)] px-5 py-5"
      style={{ borderColor: "var(--theme-border)" }}
    >
      {provenance === "illustrative" && (
        <div
          className="mb-4 rounded-md border px-4 py-3 text-[0.78rem] leading-[1.55]"
          style={{
            borderColor: "var(--theme-border-strong)",
            color: "var(--theme-text-muted)",
            backgroundColor: "var(--theme-bg-surface)",
          }}
        >
          <span
            className="mr-2 rounded-full border px-2 py-[1px] [font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em]"
            style={{ borderColor: "var(--theme-border-strong)" }}
          >
            illustrative trace
          </span>
          This trace was authored from source context when the cell was created;
          the tool calls shown were not executed. Runs from June 28, 2026 onward
          include archived activity from the public records.
        </div>
      )}
      {provenance === "recorded_run" && (
        <div
          className="mb-4 text-[0.72rem] leading-[1.5]"
          style={{ color: "var(--theme-text-dim)" }}
        >
          Recorded research run from before on-repo activity archives (June 28,
          2026); steps reflect real activity without archived receipts.
        </div>
      )}
      {steps.map((step, index) => (
        <RenderedStep
          key={index}
          step={step}
          unit={unit}
          provenance={provenance}
        />
      ))}
    </article>
  );
}

function RenderedStep({
  step,
  unit,
  provenance,
}: {
  step: ReasoningStep;
  unit: Unit;
  provenance: TraceProvenance;
}) {
  switch (step.kind) {
    case "heading":
      return (
        <h3 className="mt-6 first:mt-0 mb-2 [font-family:var(--font-display)] text-[0.95rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
          <span className="mr-2 text-[var(--color-accent)]">§</span>
          {step.text}
        </h3>
      );
    case "text":
      return (
        <p className="my-3 text-[0.93rem] leading-[1.65] text-[var(--theme-text)]">
          {step.text}
        </p>
      );
    case "math":
      return (
        <p
          className="my-3 whitespace-pre-wrap rounded-md border bg-[var(--theme-bg-surface)] px-4 py-2 [font-family:var(--font-mono)] text-[0.78rem] leading-[1.7] text-[var(--theme-text)]"
          style={{ borderColor: "var(--theme-border)" }}
        >
          {step.text}
        </p>
      );
    case "tool": {
      const tool = step.tool ?? "policyengine.simulate";
      const illustrative = provenance === "illustrative";
      const label = illustrative
        ? "illustrative step"
        : tool === "agent.run"
          ? "recorded agent run"
          : "recorded source check";
      return (
        <div className="my-3">
          <div
            className="flex items-center justify-between rounded-t-md border-x border-t bg-[#0F1A24] px-4 py-2 text-[#9FB6C6] [font-family:var(--font-mono)] text-[0.7rem]"
            style={{ borderColor: "var(--color-ink-border)" }}
          >
            <span className="text-[#5E97C8]">
              ▸ {label}: {tool}
            </span>
            <span className="text-[#9DB1BF]">
              {illustrative ? "authored, not executed" : "recorded"}
            </span>
          </div>
          <pre
            className="overflow-x-auto border-x bg-[#0F1A24] px-4 py-3 text-[#E8F0F5] [font-family:var(--font-mono)] text-[0.78rem] leading-[1.55]"
            style={{ borderColor: "var(--color-ink-border)" }}
          >
            <code>{step.call}</code>
          </pre>
          <pre
            className="overflow-x-auto rounded-b-md border-x border-b bg-[#172633] px-4 py-3 text-[#9FC4E6] [font-family:var(--font-mono)] text-[0.75rem] leading-[1.55]"
            style={{ borderColor: "var(--color-ink-border)" }}
          >
            <code>
              <span className="text-[#E7A6C8]">↳ </span>
              {step.result}
            </code>
          </pre>
        </div>
      );
    }
    case "forecast":
      return (
        <div className="mt-6 rounded-xl border border-[var(--color-accent)] bg-[var(--color-accent-subtle)] p-5">
          <div className="mb-2 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.12em] text-[var(--color-rose-700)]">
            calibrated forecast · 80% CI
          </div>
          <div className="flex items-baseline gap-4">
            <span className="[font-family:var(--font-display)] text-[2rem] font-semibold leading-none text-[var(--color-rose-700)]">
              {formatValue(step.point, unit)}
            </span>
            <span className="[font-family:var(--font-mono)] text-[0.85rem] text-[var(--color-rose-700)]">
              [{formatValue(step.ciLow, unit)} ·{" "}
              {formatValue(step.ciHigh, unit)}]
            </span>
          </div>
        </div>
      );
  }
}
