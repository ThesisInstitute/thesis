// Emit the registered targets with no forecast cell, by the rule the site
// suite enforces in "forecasts every registered ledger target". Each row says
// whether the target still sits inside its orphan grace at the given instant;
// the others fail that test. scripts/docket_health.py reads this rather than
// keeping a second copy of the rule.
//
// Run with: bun scripts/dump_unforecast_targets.ts 2026-11-02T12:00:00Z
import { EXPIRED_UNFORECAST_SET } from "../site/src/data/expired-unforecast-registrations";
import { FORECAST_CELLS } from "../site/src/data/forecast-cells";
import {
  THESIS_TARGET_LEDGER,
  isPreregisteredTargetWithinOrphanGrace,
} from "../site/src/data/ledger-targets";

const now = new Date(process.argv[2] ?? "");
if (Number.isNaN(now.getTime())) {
  throw new Error("pass the instant to check as an ISO timestamp");
}

const forecastDataPointIds = new Set(
  FORECAST_CELLS.flatMap((forecast) =>
    forecast.dataPointId ? [forecast.dataPointId] : [],
  ),
);

const rows = THESIS_TARGET_LEDGER.filter(
  (target) =>
    !forecastDataPointIds.has(target.dataPointId) &&
    !EXPIRED_UNFORECAST_SET.has(target.dataPointId),
).map((target) => ({
  dataPointId: target.dataPointId,
  registeredAt: target.registeredAt ?? null,
  withinGrace: isPreregisteredTargetWithinOrphanGrace(target, now),
}));

console.log(JSON.stringify(rows));
