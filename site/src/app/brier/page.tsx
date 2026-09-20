import { getPublishedForecasts } from "@/lib/forecast-publication";
import type { Metadata } from "next";
import Link from "next/link";
import { Header } from "@/components/Header";
import {
  buildPredictionSpecs,
  buildRecordedPredictionRunRecords,
} from "@/data/prediction-specs";
import {
  buildBrierRewardExport,
  summarizeBrierCoverage,
  type BrierAgentLeaderboardRow,
  type BrierEvalSplit,
  type BrierRewardRow,
} from "@/data/brier-lab";
import {
  loadPolicyEngineLedger,
  withResolvedOutcomes,
} from "@/data/thesis-log";

export const metadata: Metadata = {
  title: "Brier Lab — Thesis Institute",
  description:
    "Agent-only forecast accuracy lab built on Thesis prediction records, resolution facts, and proper scoring rewards.",
  robots: {
    index: false,
    follow: false,
    nocache: true,
    googleBot: {
      index: false,
      follow: false,
      noimageindex: true,
    },
  },
};

export default async function BrierLabPage() {
  const ledger = await loadPolicyEngineLedger();
  const forecasts = withResolvedOutcomes(getPublishedForecasts(), ledger);
  const specs = buildPredictionSpecs(forecasts);
  const runs = buildRecordedPredictionRunRecords(forecasts, specs);
  const rewardExport = buildBrierRewardExport({
    forecasts,
    specs,
    runs,
    ledger,
  });
  const coverage = summarizeBrierCoverage({ forecasts, ledger });
  const scoredRows = rewardExport.rewardRows.filter(
    (row) => row.reward.value !== null,
  );
  const recentRows = [...rewardExport.rewardRows]
    .sort((left, right) => (right.runAt ?? "").localeCompare(left.runAt ?? ""))
    .slice(0, 10);

  return (
    <div>
      <Header activePage="brier" />
      <main className="mx-auto max-w-[1200px] px-8 pb-32 pt-12 max-md:px-5">
        <section className="mb-10 max-w-[820px]">
          <p className="mb-3 [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.15em] text-[var(--color-accent)]">
            Brier Lab · forecast reward engine
          </p>
          <h1 className="mb-5 [font-family:var(--font-display)] text-[clamp(1.9rem,4vw,2.6rem)] font-light leading-[1.15] tracking-[-0.02em] text-[var(--theme-text)]">
            Training substrate for agentic forecasting
          </h1>
          <p className="text-[1.03rem] leading-[1.65] text-[var(--theme-text-muted)]">
            Brier turns Thesis runs into an objective reward table: immutable
            agent outputs, first-print resolutions, proper scoring rows, and
            time-based holdouts. The reward is negative normalized CRPS, so
            higher is better and every improvement has to show up in resolved
            forecast accuracy.
          </p>
          <div className="mt-5 flex flex-wrap gap-4">
            <a
              href="/brier/reward.json"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--color-accent)] no-underline hover:no-underline"
            >
              Reward JSON →
            </a>
            <a
              href="/log.json"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
            >
              Thesis Log JSON →
            </a>
            <Link
              href="/forecasts/log"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
            >
              Scoreboard →
            </Link>
            <Link
              href="/brier/strategies"
              className="inline-block [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.12em] text-[var(--theme-text-dim)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
            >
              Strategy Lab →
            </Link>
          </div>
        </section>

        <section className="mb-8 grid grid-cols-1 gap-4 md:grid-cols-3 lg:grid-cols-6">
          <MetricCard label="runs" value={rewardExport.counts.runs} />
          <MetricCard label="scored" value={rewardExport.counts.scoredRuns} />
          <MetricCard label="agents" value={rewardExport.counts.agents} />
          <MetricCard label="specs" value={rewardExport.counts.specs} />
          <MetricCard label="resolved" value={coverage.resolvedEvents} />
          <MetricCard
            label="activity logs"
            value={coverage.activityLoggedRuns}
          />
        </section>

        <section
          className="mb-8 rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
          style={{ borderColor: "var(--theme-border)" }}
        >
          <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
              Reward Contract
            </h2>
            <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              {rewardExport.mission.reward}
            </span>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-5">
            {rewardExport.mission.constraints.map((constraint) => (
              <div
                className="border-l border-[var(--theme-border)] pl-4 text-[0.82rem] leading-[1.55] text-[var(--theme-text-muted)]"
                key={constraint}
              >
                {constraint}
              </div>
            ))}
          </div>
          <div className="mt-5 border-t border-[var(--theme-border)] pt-4 text-[0.86rem] leading-[1.6] text-[var(--theme-text-muted)]">
            {rewardExport.noLeakagePolicy.rule}
          </div>
        </section>

        <section className="mb-8 grid grid-cols-1 gap-4 md:grid-cols-4">
          {(["train", "validation", "test", "unresolved"] as const).map(
            (split) => (
              <SplitCard
                key={split}
                split={split}
                summary={rewardExport.splits[split]}
              />
            ),
          )}
        </section>

        <section
          className="mb-8 rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
          style={{ borderColor: "var(--theme-border)" }}
        >
          <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
              Agent Leaderboard
            </h2>
            <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              {scoredRows.length} reward rows
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] border-collapse text-left [font-family:var(--font-body)] text-[0.84rem]">
              <thead>
                <tr className="border-b border-[var(--theme-border)] [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                  <th className="py-3 pr-5 font-medium">agent</th>
                  <th className="py-3 pr-5 font-medium">model</th>
                  <th className="py-3 pr-5 font-medium">runs</th>
                  <th className="py-3 pr-5 font-medium">
                    CRPS ratio vs persistence
                  </th>
                  <th className="py-3 pr-5 font-medium">win rate</th>
                  <th className="py-3 pr-5 font-medium">unpaired reward</th>
                  <th className="py-3 pr-5 font-medium">unpaired nCRPS</th>
                  <th className="py-3 pr-5 font-medium">unpaired coverage</th>
                  <th className="py-3 font-medium">activity</th>
                </tr>
              </thead>
              <tbody>
                {rewardExport.leaderboard.map((row) => (
                  <LeaderboardRow key={`${row.agent}:${row.model}`} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section
          className="rounded-xl border bg-[var(--theme-bg-elevated)] p-6"
          style={{ borderColor: "var(--theme-border)" }}
        >
          <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold tracking-[-0.01em] text-[var(--theme-text)]">
              Recent Reward Rows
            </h2>
            <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
              newest 10 runs
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] border-collapse text-left [font-family:var(--font-body)] text-[0.84rem]">
              <thead>
                <tr className="border-b border-[var(--theme-border)] [font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
                  <th className="py-3 pr-5 font-medium">prediction</th>
                  <th className="py-3 pr-5 font-medium">run</th>
                  <th className="py-3 pr-5 font-medium">split</th>
                  <th className="py-3 pr-5 font-medium">reward</th>
                  <th className="py-3 pr-5 font-medium">resolution</th>
                  <th className="py-3 font-medium">artifacts</th>
                </tr>
              </thead>
              <tbody>
                {recentRows.map((row) => (
                  <RewardRow key={row.runId} row={row} />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: number }) {
  return (
    <div
      className="rounded-xl border bg-[var(--theme-bg-elevated)] p-4"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <div className="[font-family:var(--font-mono)] text-[0.58rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
        {label}
      </div>
      <div className="mt-2 [font-family:var(--font-display)] text-[1.55rem] font-semibold tracking-[-0.02em] text-[var(--theme-text)]">
        {value.toLocaleString()}
      </div>
    </div>
  );
}

function SplitCard({
  split,
  summary,
}: {
  split: BrierEvalSplit;
  summary: { runs: number; scoredRuns: number; rule: string };
}) {
  return (
    <div
      className="rounded-xl border bg-[var(--theme-bg-elevated)] p-5"
      style={{ borderColor: "var(--theme-border)" }}
    >
      <div className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--color-accent)]">
        {split}
      </div>
      <div className="mt-3 [font-family:var(--font-display)] text-[1.45rem] font-semibold tracking-[-0.02em] text-[var(--theme-text)]">
        {summary.scoredRuns.toLocaleString()}
        <span className="ml-2 text-[0.9rem] font-normal text-[var(--theme-text-dim)]">
          / {summary.runs.toLocaleString()}
        </span>
      </div>
      <p className="mt-3 text-[0.82rem] leading-[1.55] text-[var(--theme-text-muted)]">
        {summary.rule}
      </p>
    </div>
  );
}

function LeaderboardRow({ row }: { row: BrierAgentLeaderboardRow }) {
  return (
    <tr className="border-b border-[var(--theme-border)] last:border-b-0">
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {row.agent}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text-muted)]">
        {row.model ?? "unreported"}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {row.scoredRuns.toLocaleString()} / {row.totalRuns.toLocaleString()}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatMaybe(row.pairedCrpsRatioGeomean)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatPercent(row.pairedWinRate)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatMaybe(row.unpairedMeanReward)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatMaybe(row.unpairedMeanNormalizedCrps)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatPercent(row.unpairedInterval80Coverage)}
      </td>
      <td className="py-4 align-top text-[var(--theme-text)]">
        {formatPercent(row.activityArtifactCoverage)}
      </td>
    </tr>
  );
}

function RewardRow({ row }: { row: BrierRewardRow }) {
  return (
    <tr className="border-b border-[var(--theme-border)] last:border-b-0">
      <td className="max-w-[260px] py-4 pr-5 align-top">
        <Link
          href={`/forecasts/${row.predictionId}`}
          className="break-all text-[var(--theme-text)] no-underline hover:text-[var(--color-accent)] hover:no-underline"
        >
          {row.predictionId}
        </Link>
        <div className="mt-1 break-all [font-family:var(--font-mono)] text-[0.66rem] text-[var(--theme-text-dim)]">
          {row.dataPointId}
        </div>
      </td>
      <td className="max-w-[220px] py-4 pr-5 align-top">
        <div className="text-[var(--theme-text)]">{row.runLabel}</div>
        <div className="mt-1 [font-family:var(--font-mono)] text-[0.66rem] text-[var(--theme-text-dim)]">
          {row.agent ?? "prototype seed"}
        </div>
      </td>
      <td className="py-4 pr-5 align-top [font-family:var(--font-mono)] text-[0.66rem] uppercase tracking-[0.08em] text-[var(--color-accent)]">
        {row.split}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text)]">
        {formatMaybe(row.reward.value)}
      </td>
      <td className="py-4 pr-5 align-top text-[var(--theme-text-muted)]">
        {row.resolutionDate}
      </td>
      <td className="py-4 align-top text-[var(--theme-text)]">
        {row.provenance.activityArtifactCount.toLocaleString()}
      </td>
    </tr>
  );
}

function formatMaybe(value: number | null) {
  if (value === null) return "pending";
  return value.toFixed(3);
}

function formatPercent(value: number | null) {
  if (value === null) return "pending";
  return `${Math.round(value * 100)}%`;
}
