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
 * withholds. Mirrors `publishable_compute_row` in scripts/tools/attach_compute.py;
 * both are pinned to tests/fixtures/compute_publishability_cases.json.
 */
export function isPublishableCompute(row: BillCompute): boolean {
  const c = row.certification;
  if (!c || c.certified !== true) return false;
  if (row.status !== "ok") return false;
  if (!row.dataset || c.build !== row.dataset) return false;
  const running = c.running_model_version;
  if (!running || running !== row.pe_us_version) return false;
  if (c.certified_model_version !== running) return false;
  if (c.validated_against !== `policyengine-us@${running}`) return false;
  if (row.param_source != null && row.param_source !== c.validated_against) return false;
  if (c.certified_core_version != null) {
    if (c.running_core_version !== c.certified_core_version) return false;
    if (row.pe_core_version !== c.running_core_version) return false;
  }
  return c.warning == null;
}
