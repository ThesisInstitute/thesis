import type { Metadata } from "next";
import Link from "next/link";
import { Header } from "@/components/Header";
import { FORECAST_CELLS } from "@/data/forecast-cells";
import { MODEL_LANE_STATS } from "@/data/model-lane-stats.generated";
import { modelLaneLabel, orderModelLanes } from "@/data/model-lanes";
import {
  hasVerifiedClaimedChronology,
  loadPolicyEngineLedger,
  scoreResolvedForecasts,
  withResolvedOutcomes,
} from "@/data/thesis-log";

export const metadata: Metadata = {
  title: "Models — Thesis Institute",
  description:
    "Model-by-model comparison under identical elicitation contracts: trace-rubric compliance by lane now, resolved accuracy as targets print.",
};

interface ModelAccuracyRow {
  model: string;
  resolved: number;
  witnessVerified: number;
  claimedOrBetter: number;
  covered: number;
}

function formatShare(passed: number, attempted: number): string {
  if (!attempted) return "—";
  return `${passed}/${attempted}`;
}

export default async function ModelsPage() {
  const ledger = await loadPolicyEngineLedger();
  const forecasts = withResolvedOutcomes(FORECAST_CELLS, ledger);
  const scores = scoreResolvedForecasts(forecasts, ledger);

  const models = Array.from(
    new Set(MODEL_LANE_STATS.map((row) => row.model)),
  ).sort();
  const lanes = orderModelLanes(MODEL_LANE_STATS.map((row) => row.lane));
  const statFor = (model: string, lane: string) =>
    MODEL_LANE_STATS.find((row) => row.model === model && row.lane === lane);

  const accuracyByModel = new Map<string, ModelAccuracyRow>();
  for (const score of scores) {
    if (!score.model) continue;
    const row = accuracyByModel.get(score.model) ?? {
      model: score.model,
      resolved: 0,
      witnessVerified: 0,
      claimedOrBetter: 0,
      covered: 0,
    };
    row.resolved += 1;
    if (score.chronology === "witness_verified") row.witnessVerified += 1;
    if (hasVerifiedClaimedChronology(score.chronology)) {
      row.claimedOrBetter += 1;
      if (
        score.observedValue >= score.interval80.lower &&
        score.observedValue <= score.interval80.upper
      ) {
        row.covered += 1;
      }
    }
    accuracyByModel.set(score.model, row);
  }
  const accuracyRows = Array.from(accuracyByModel.values()).sort((a, b) =>
    a.model.localeCompare(b.model),
  );

  return (
    <div
      className="min-h-screen"
      style={{ backgroundColor: "var(--theme-bg)" }}
    >
      <Header activePage="models" />
      <main className="mx-auto w-full max-w-[960px] px-6 pb-24 pt-12">
        <h1
          className="[font-family:var(--font-display)] text-[1.9rem] font-semibold"
          style={{ color: "var(--theme-text)" }}
        >
          Models
        </h1>
        <p
          className="mt-3 max-w-[680px] text-[0.92rem] leading-[1.65]"
          style={{ color: "var(--theme-text-muted)" }}
        >
          Every model runs the same registered targets under the same prompt
          contract, validator, and pipeline; every run is recorded whether it
          passes or fails. This page compares models on two separable axes:
          whether their traces satisfy the elicitation contract they were
          given, and — as targets resolve against official prints — how
          accurate their forecasts are. Compliance is not accuracy; read the
          tables separately.
        </p>

        <section className="mt-12">
          <h2
            className="[font-family:var(--font-display)] text-[1.3rem] font-semibold"
            style={{ color: "var(--theme-text)" }}
          >
            Contract compliance by lane
          </h2>
          <p
            className="mt-2 max-w-[680px] text-[0.88rem] leading-[1.6]"
            style={{ color: "var(--theme-text-muted)" }}
          >
            Runs passing the sealed trace rubric over runs attempted, from the
            recorded protocol-lane manifests (strategy lanes in the records
            until the identifier migration). Fast and Ladder demand the
            parametric width derivation (&ldquo;sigma = X&rdquo;, 1.28·sigma);
            Ladder v2 is the pre-registered quantile-native contract (rungs
            plus interpolated 10th/90th percentiles stated literally). System
            One is scored against its own sealed rubric instead: a strictly
            increasing ladder, a monotone CDF, and resolver fields equal to
            the registered target. Failed runs stay in the record as
            immutable run manifests.
          </p>
          <div
            className="mt-5 overflow-x-auto rounded-[14px] border"
            style={{ borderColor: "var(--theme-border)" }}
          >
            <table className="w-full border-collapse text-[0.84rem]">
              <thead>
                <tr
                  className="[font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.1em]"
                  style={{ color: "var(--theme-text-muted)" }}
                >
                  <th className="px-4 py-3 text-left font-normal">Model</th>
                  {lanes.map((lane) => (
                    <th
                      key={lane}
                      className="px-4 py-3 text-right font-normal"
                    >
                      {modelLaneLabel(lane)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {models.map((model) => (
                  <tr
                    key={model}
                    className="border-t"
                    style={{ borderColor: "var(--theme-border)" }}
                  >
                    <td
                      className="px-4 py-3 [font-family:var(--font-mono)] text-[0.78rem]"
                      style={{ color: "var(--theme-text)" }}
                    >
                      {model}
                    </td>
                    {lanes.map((lane) => {
                      const stat = statFor(model, lane);
                      return (
                        <td
                          key={lane}
                          className="px-4 py-3 text-right [font-family:var(--font-mono)]"
                          style={{
                            color:
                              stat && stat.passed < stat.attempted
                                ? "var(--theme-text)"
                                : "var(--theme-text-muted)",
                          }}
                        >
                          {stat
                            ? formatShare(stat.passed, stat.attempted)
                            : "—"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="mt-14">
          <h2
            className="[font-family:var(--font-display)] text-[1.3rem] font-semibold"
            style={{ color: "var(--theme-text)" }}
          >
            Resolved accuracy
          </h2>
          <p
            className="mt-2 max-w-[680px] text-[0.88rem] leading-[1.6]"
            style={{ color: "var(--theme-text-muted)" }}
          >
            Accuracy accrues as registered targets print. The headline tier is
            witness-verified scores only — runs whose sealed custody root was
            externally timestamped before the observation; recorded-timestamp
            (claimed-time) scores sit one tier below, published and flagged,
            never deleted. Interval coverage here is over claimed-or-better
            scores; the full scoreboard, paired persistence baselines, and
            per-agent leaderboards live on{" "}
            <Link href="/calibration">Calibration</Link>.
          </p>
          <div
            className="mt-5 overflow-x-auto rounded-[14px] border"
            style={{ borderColor: "var(--theme-border)" }}
          >
            <table className="w-full border-collapse text-[0.84rem]">
              <thead>
                <tr
                  className="[font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.1em]"
                  style={{ color: "var(--theme-text-muted)" }}
                >
                  <th className="px-4 py-3 text-left font-normal">Model</th>
                  <th className="px-4 py-3 text-right font-normal">
                    Resolved scores
                  </th>
                  <th className="px-4 py-3 text-right font-normal">
                    Witness-verified
                  </th>
                  <th className="px-4 py-3 text-right font-normal">
                    Claimed-time or better
                  </th>
                  <th className="px-4 py-3 text-right font-normal">
                    80% coverage
                  </th>
                </tr>
              </thead>
              <tbody>
                {accuracyRows.map((row) => (
                  <tr
                    key={row.model}
                    className="border-t"
                    style={{ borderColor: "var(--theme-border)" }}
                  >
                    <td
                      className="px-4 py-3 [font-family:var(--font-mono)] text-[0.78rem]"
                      style={{ color: "var(--theme-text)" }}
                    >
                      {row.model}
                    </td>
                    <td
                      className="px-4 py-3 text-right [font-family:var(--font-mono)]"
                      style={{ color: "var(--theme-text-muted)" }}
                    >
                      {row.resolved}
                    </td>
                    <td
                      className="px-4 py-3 text-right [font-family:var(--font-mono)]"
                      style={{ color: "var(--theme-text)" }}
                    >
                      {row.witnessVerified}
                    </td>
                    <td
                      className="px-4 py-3 text-right [font-family:var(--font-mono)]"
                      style={{ color: "var(--theme-text-muted)" }}
                    >
                      {row.claimedOrBetter}
                    </td>
                    <td
                      className="px-4 py-3 text-right [font-family:var(--font-mono)]"
                      style={{ color: "var(--theme-text-muted)" }}
                    >
                      {row.claimedOrBetter
                        ? `${Math.round((row.covered / row.claimedOrBetter) * 100)}%`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p
            className="mt-3 text-[0.78rem] leading-[1.55]"
            style={{ color: "var(--theme-text-muted)" }}
          >
            The gpt-5.6 comparison waves published on 2026-07-10 resolve from
            mid-July onward; per-model paired CRPS ratios against the
            persistence baseline appear on Calibration as those targets
            print.
          </p>
        </section>
      </main>
    </div>
  );
}
