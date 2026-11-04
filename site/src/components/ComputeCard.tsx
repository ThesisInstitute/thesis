import type { BillCompute } from "@/data/bills";
import { isPublishableCompute } from "@/lib/compute-publishability";
import { renderInline } from "@/lib/render-inline";

const chipBase =
  "inline-block rounded-full border px-2 py-0.5 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.08em]";

/**
 * One audited model run attached to the provision it prices (issue #45).
 * Shows the mechanical number with its full provenance — model version,
 * dataset build, and whether the model↔data pairing is certified. An
 * uncertified row is inadmissible for a published number (POLICYENGINE.md
 * §0.2): it still renders, never silently — provenance, a warning chip, the
 * certification's reason and the reform — but every figure it carries (stats,
 * summary, note) is withheld.
 */
function fmtBillions(v: number, decimals = 2): string {
  const sign = v < 0 ? "−" : "+";
  return `${sign}$${(Math.abs(v) / 1e9).toFixed(decimals)}B`;
}

function fmtPct(v: number, decimals = 1): string {
  const sign = v < 0 ? "−" : "";
  return `${sign}${(Math.abs(v) * 100).toFixed(decimals)}%`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
        {label}
      </div>
      <div className="text-[1.05rem] font-semibold leading-[1.4] text-[var(--theme-text)]">
        {value}
      </div>
    </div>
  );
}

export function ComputeCard({ row }: { row: BillCompute }) {
  const certified = isPublishableCompute(row);
  const buildLabel = row.dataset
    ? (row.dataset.match(/build[a-z]+/i)?.[0] ?? row.dataset.slice(0, 24))
    : null;
  const hasStats = certified && row.budgetary_impact != null;
  return (
    <div className="rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg)] p-4">
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <span className={`${chipBase} border-[var(--theme-border)] text-[var(--theme-text-dim)]`}>
          {row.model}
          {row.pe_us_version ? `@${row.pe_us_version}` : ""}
        </span>
        {buildLabel && (
          <span
            className={`${chipBase} border-[var(--theme-border)] text-[var(--theme-text-dim)]`}
            title={row.dataset}
          >
            populace {buildLabel}
          </span>
        )}
        {row.engine && (
          <span className={`${chipBase} border-[var(--theme-border)] text-[var(--theme-text-dim)]`}>
            {row.engine}
          </span>
        )}
        <span className={`${chipBase} ${certified ? "border-[#BFE3D2] bg-[#EAF7F0] text-[#1C6B4A]" : "border-[#E5C8C0] bg-[#F9EFEC] text-[#93412A]"}`}>
          {certified ? "certified pairing" : "uncertified pairing"}
        </span>
      </div>
      {hasStats && (
        <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
          {row.budgetary_impact != null && row.year != null && (
            <Stat label={`${row.year} federal impact`} value={fmtBillions(row.budgetary_impact)} />
          )}
          {row.ten_year_budgetary_impact != null && (
            <Stat
              label={`Ten-year federal${row.ten_year_window ? ` (${row.ten_year_window})` : ""}`}
              value={fmtBillions(row.ten_year_budgetary_impact, 1)}
            />
          )}
          {row.poverty_child_pct_change != null && (
            <Stat label="Child poverty" value={fmtPct(row.poverty_child_pct_change)} />
          )}
          {row.beneficiaries_share != null && (
            <Stat label="People gaining" value={fmtPct(row.beneficiaries_share)} />
          )}
        </div>
      )}
      {certified ? (
        <p className="m-0 mb-2 text-[0.88rem] leading-[1.6] text-[var(--theme-text-muted)]">
          {renderInline(row.result_summary)}
        </p>
      ) : (
        <div className="mb-2 text-[0.88rem] leading-[1.6] text-[var(--theme-text-muted)]">
          <p className="m-0">
            Figures withheld: this run is not a certified model–data pairing,
            so its numbers are inadmissible for publication.
          </p>
          <p className="m-0 mt-1 [font-family:var(--font-mono)] text-[0.72rem] text-[var(--theme-text-dim)]">
            {row.certification?.warning ??
              (row.certification
                ? "The certification record does not match this run's provenance."
                : "This run carries no certification.")}
          </p>
        </div>
      )}
      <details className="mb-2">
        <summary className="cursor-pointer [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.08em] text-[var(--theme-text-dim)]">
          Reform parameters
        </summary>
        <pre className="m-0 mt-2 overflow-x-auto rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg)] p-3 [font-family:var(--font-mono)] text-[0.72rem] leading-[1.5] text-[var(--theme-text)]">
          {JSON.stringify(row.reform, null, 2)}
        </pre>
      </details>
      {certified && row.note && (
        <p className="m-0 text-[0.78rem] leading-[1.55] text-[var(--theme-text-muted)]">
          {renderInline(row.note)}
        </p>
      )}
    </div>
  );
}

