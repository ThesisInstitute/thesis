import type { BillCompute } from "@/data/bills";

/**
 * POLICYENGINE.md §0.2: a run whose certification is not certified is
 * inadmissible for a published number. This is the one gate a page applies
 * before rendering any figure from a compute row (stats, summary, note).
 * Beyond the flag it requires the certification to agree with the row it
 * certifies — the measured running versions are the row's versions and equal
 * the certified ones, the reform was validated against that running model, and
 * the build is the row's dataset — so a hand-set `certified: true` over
 * mismatched provenance still withholds. Fail-closed: anything missing
 * withholds. Every provenance field it compares must be a JSON string: numbers
 * and booleans compare and format differently here and in Python (1.0 vs 1,
 * True == 1), so admitting them would let the two gates disagree. Mirrors
 * `publishable_compute_row` in scripts/tools/attach_compute.py; both are pinned
 * to tests/fixtures/compute_publishability_cases.json.
 */
export function isPublishableCompute(row: BillCompute): boolean {
  const c = row.certification;
  if (!c || c.certified !== true) return false;
  if (row.status !== "ok") return false;
  if (!isNonEmptyString(row.dataset) || c.build !== row.dataset) return false;
  const running = c.running_model_version;
  if (!isNonEmptyString(running) || running !== row.pe_us_version) return false;
  if (c.certified_model_version !== running) return false;
  if (c.validated_against !== `policyengine-us@${running}`) return false;
  if (row.param_source != null && row.param_source !== c.validated_against) return false;
  const certifiedCore = c.certified_core_version;
  if (certifiedCore != null) {
    if (!isNonEmptyString(certifiedCore)) return false;
    if (c.running_core_version !== certifiedCore) return false;
    if (row.pe_core_version !== certifiedCore) return false;
  }
  return c.warning == null;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value !== "";
}

/**
 * The reason line a withheld card shows. certification_note writes warnings
 * without figures; a warning that carries a dollar sign or is not a string is
 * not shown, so a withheld card never displays a dollar figure.
 */
export function withheldReason(row: BillCompute): string {
  const warning = row.certification?.warning;
  if (typeof warning === "string" && warning !== "" && !warning.includes("$")) return warning;
  if (warning != null) return "This run's certification warning is withheld with its figures.";
  return row.certification
    ? "The certification record does not match this run's provenance."
    : "This run carries no certification.";
}
