import { getPublishedForecasts } from "@/lib/forecast-publication";
import { buildForecastJudgeExport } from "@/data/forecast-judges";
import {
  loadPolicyEngineLedger,
  scoreResolvedForecasts,
  withResolvedOutcomes,
} from "@/data/thesis-log";

export const dynamic = "force-static";

export async function GET() {
  const ledger = await loadPolicyEngineLedger();
  const forecasts = withResolvedOutcomes(getPublishedForecasts(), ledger);
  const scores = scoreResolvedForecasts(forecasts, ledger);

  return Response.json(buildForecastJudgeExport({ forecasts, scores }));
}
