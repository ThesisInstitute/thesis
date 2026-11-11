import { getPublishedForecasts } from "@/lib/forecast-publication";
import {
  buildPredictionSpecs,
  buildRecordedPredictionRunRecords,
} from "@/data/prediction-specs";
import { buildBrierRewardExport } from "@/data/brier-lab";
import {
  loadPolicyEngineLedger,
  withResolvedOutcomes,
} from "@/data/thesis-log";

export const dynamic = "force-static";

export async function GET() {
  const ledger = await loadPolicyEngineLedger();
  const forecasts = withResolvedOutcomes(getPublishedForecasts(), ledger);
  const specs = buildPredictionSpecs(forecasts);
  const runs = buildRecordedPredictionRunRecords(forecasts, specs);

  return Response.json(
    buildBrierRewardExport({
      forecasts,
      specs,
      runs,
      ledger,
    }),
  );
}
