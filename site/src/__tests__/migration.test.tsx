import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";

// Mock next/link to render as a simple <a> tag
vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

// Import components after mocks are set up
import HomePage from "../app/page";
import BillDetailPage from "../app/bills/[slug]/page";
import DocsPage from "../app/docs/page";
import ForecastLedgerPage from "../app/forecasts/ledger/page";
import { GET as getForecastLedgerJson } from "../app/forecasts/ledger.json/route";
import ForecastLogPage from "../app/forecasts/log/page";
import { GET as getForecastLogJson } from "../app/forecasts/log.json/route";
import { GET as getThesisLogChunkJson } from "../app/log/[collection]/[chunk].json/route";
import ForecastsPage from "../app/forecasts/page";
import { GET as getForecastTargetChunkJson } from "../app/forecasts/targets/[table]/[chunk].json/route";
import { GET as getForecastTargetTableJson } from "../app/forecasts/targets/[table]/[chunk].json/route";
import { GET as getForecastTargetsJson } from "../app/forecasts/targets.json/route";
import TargetArchitecturePage from "../app/forecasts/targets/page";
import ThesisPage from "../app/thesis/page";
import { ForecastRuntime } from "../components/ForecastRuntime";
import { FORECAST_CELLS, getForecastCell } from "../data/forecast-cells";
import { resolveMetricCell } from "../lib/metric-cells";
import { buildTargetArchitectureProjection } from "../data/thesis-target-architecture";
import {
  buildTargetArchitectureChunkHashPayload,
  buildTargetArchitectureRootPayload,
} from "../data/thesis-target-architecture-export";
import { sha256Hex } from "../data/canonical-json";
import { buildTargetArchitectureBackfillSql } from "../data/thesis-target-architecture-sql";
import {
  loadPolicyEngineLedger,
  scoreResolvedForecast,
  withResolvedOutcome,
  withResolvedOutcomes,
} from "../data/thesis-log";

describe("Next.js migration", () => {
  describe("Bill detail", () => {
    it("renders the published CRP pair and retains its refusal history", async () => {
      render(
        await BillDetailPage({
          params: Promise.resolve({ slug: "farm-bill-2-0" }),
        }),
      );

      expect(screen.getAllByText("26,650,000").length).toBeGreaterThan(0);
      expect(screen.getAllByText("26,182,019").length).toBeGreaterThan(0);
      expect(
        screen.getByText("Forecast refused — fail-closed"),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/Every documented attempt failed closed/),
      ).toBeInTheDocument();
      expect(screen.queryByText("Forecast pending")).not.toBeInTheDocument();
    });

    it("renders the FLARE bounded target honestly for its lane state", async () => {
      // State-adaptive (the #181 precedent): before the ticketed lane
      // publishes the EIA cell, the page must carry the ticketed-lane
      // pending card; after publication the forecast surface replaces
      // it. Both are honest states — pinning only the pending card made
      // the publish leg's own site test refuse the publish that removes
      // the card. The next-roll promise is wrong in every state.
      render(
        await BillDetailPage({
          params: Promise.resolve({ slug: "flare-act-s1188-119" }),
        }),
      );

      // Resolve exactly the way the page does: the context-series card
      // renders the MetricCellMatch (which carries the display labels),
      // never the raw ForecastCell.
      const eiaMatch = resolveMetricCell("eia.ng.vented_flared.us.annual");
      if (eiaMatch) {
        expect(
          screen.queryByText(
            "Admitted to the docket — awaiting ticketed registration and generation through the attested lane.",
          ),
        ).not.toBeInTheDocument();
        // The published surface must actually render: the cell's own
        // card with its forecast values, not merely the series label
        // (which the pending state also shows).
        const card = screen.getByText(eiaMatch.title).closest("a");
        expect(card).not.toBeNull();
        expect(
          within(card as HTMLElement).getByText("Current forecast"),
        ).toBeInTheDocument();
        expect(
          within(card as HTMLElement).getByText(eiaMatch.pointLabel),
        ).toBeInTheDocument();
        expect(
          within(card as HTMLElement).getByText(eiaMatch.ciLabel),
        ).toBeInTheDocument();
      } else {
        expect(
          screen.getByText(
            "Admitted to the docket — awaiting ticketed registration and generation through the attested lane.",
          ),
        ).toBeInTheDocument();
      }
      expect(
        screen.queryByText(
          /first registered forecast arrives with the next roll/i,
        ),
      ).not.toBeInTheDocument();
    });
  });

  describe("Homepage", () => {
    it("renders without crashing", () => {
      render(<HomePage />);
    });

    it("renders header with Thesis brand", () => {
      render(<HomePage />);
      expect(screen.getAllByText(/thesis institute/i).length).toBeGreaterThan(
        0,
      );
    });

    it("renders landing page hero", () => {
      render(<HomePage />);
      expect(
        screen.getByText("Open-source forecasting agents for public outcomes."),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/We build agents whose job is to predict/),
      ).toBeInTheDocument();
    });

    it("keeps the forecast app one level deeper", () => {
      render(<HomePage />);
      expect(
        screen.getByText("The forecast app lives one level deeper."),
      ).toBeInTheDocument();
      expect(screen.queryByText("Prototype status")).not.toBeInTheDocument();
      expect(screen.queryByText("Static mock traces")).not.toBeInTheDocument();
      expect(
        screen.queryByText(
          "Forecasts on every consequential cell of government data",
        ),
      ).not.toBeInTheDocument();
    });

    it("links to the forecast app", () => {
      render(<HomePage />);
      const forecastLinks = screen
        .getAllByRole("link")
        .filter((link) => link.getAttribute("href") === "/forecasts");
      expect(forecastLinks.length).toBeGreaterThan(0);
      expect(
        screen.getAllByText(/Open forecasts|View all forecasts/).length,
      ).toBeGreaterThan(0);
    });

    it("renders the institute stack", () => {
      render(<HomePage />);
      expect(
        screen.getByText(
          "We connect prediction, law, data, and simulation in one open loop.",
        ),
      ).toBeInTheDocument();
      expect(screen.getAllByText("PolicyEngine").length).toBeGreaterThan(0);
      expect(screen.getByText("Microplex")).toBeInTheDocument();
      expect(screen.getAllByText("Brier Decisions").length).toBeGreaterThan(0);
    });

    it("renders the alignment method", () => {
      render(<HomePage />);
      expect(
        screen.getByText("Forecasting as alignment pressure"),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          "A system that must predict reality has to stay accountable to it.",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          "Define the public outcome and the exact source that will resolve it.",
        ),
      ).toBeInTheDocument();
    });

    it("renders public forecast examples without opening the app shell", () => {
      render(<HomePage />);
      expect(
        screen.getAllByText("SPM child poverty rate, 2025").length,
      ).toBeGreaterThan(0);
      expect(
        screen.getAllByText("CTC outlays under current law, TY2026").length,
      ).toBeGreaterThan(0);
      expect(
        screen.getAllByText("CPI-U annual average inflation, 2026").length,
      ).toBeGreaterThan(0);
      expect(screen.getAllByText(/resolves/i).length).toBeGreaterThan(0);
    });

    it("renders footer", () => {
      render(<HomePage />);
      expect(screen.getAllByText("Forecasts").length).toBeGreaterThan(0);
      expect(screen.getByText("Vision")).toBeInTheDocument();
      expect(screen.getAllByText("Brier Decisions").length).toBeGreaterThan(0);
      expect(screen.getAllByText("PolicyEngine").length).toBeGreaterThan(0);
    });

    it("links PolicyEngine externally", () => {
      render(<HomePage />);
      const policyEngineLinks = screen
        .getAllByRole("link")
        .filter(
          (link) => link.getAttribute("href") === "https://policyengine.org",
        );
      expect(policyEngineLinks.length).toBeGreaterThan(0);
    });

    it("links the vision page from the landing page", () => {
      render(<HomePage />);
      expect(
        screen.getByRole("link", { name: "Read the vision" }),
      ).toBeInTheDocument();
    });
  });

  describe("Thesis page", () => {
    it("renders without crashing", () => {
      render(<ThesisPage />);
    });

    it("renders header with active thesis link", () => {
      render(<ThesisPage />);
      const thesisLinks = screen.getAllByText("Thesis");
      expect(thesisLinks.length).toBeGreaterThan(0);
    });

    it("renders thesis title", () => {
      render(<ThesisPage />);
      expect(screen.getByText("Forecasting as a harness")).toBeInTheDocument();
    });

    it("renders all section headings", () => {
      render(<ThesisPage />);
      expect(screen.getByText("The problem with advice")).toBeInTheDocument();
      expect(screen.getByText("The reframe")).toBeInTheDocument();
      expect(
        screen.getByText("The superforecasting connection"),
      ).toBeInTheDocument();
      expect(screen.getByText("Why AI makes this better")).toBeInTheDocument();
      expect(screen.getByText("The calibration loop")).toBeInTheDocument();
      expect(
        screen.getByText("The decision quality chain"),
      ).toBeInTheDocument();
      expect(screen.getByText("The framework")).toBeInTheDocument();
      expect(screen.getByText("When to use it")).toBeInTheDocument();
      expect(screen.getByText("The vision")).toBeInTheDocument();
    });

    it("renders references section", () => {
      render(<ThesisPage />);
      expect(screen.getAllByText("References").length).toBeGreaterThan(0);
    });
  });

  describe("Docs page", () => {
    it("renders without crashing", () => {
      render(<DocsPage />);
    });

    it("renders docs title and install guidance", () => {
      render(<DocsPage />);
      expect(
        screen.getByText(
          "Use brier with Codex, Claude Code, or the local CLI.",
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Install the package and choose a path"),
      ).toBeInTheDocument();
      expect(screen.getAllByText(/brier setup codex/).length).toBeGreaterThan(
        0,
      );
      expect(screen.getAllByText(/brier doctor codex/).length).toBeGreaterThan(
        0,
      );
      expect(
        screen.getByText("See the packaged flow before you install"),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Fix drifted installs or reset cleanly"),
      ).toBeInTheDocument();
      expect(
        screen.getByText("Draft public forecast questions"),
      ).toBeInTheDocument();
      expect(screen.getAllByText(/\$brier/).length).toBeGreaterThan(0);
    });

    it("explains that the CLI does not need an API key", () => {
      render(<DocsPage />);
      expect(screen.getByText(/No LLM API key is/)).toBeInTheDocument();
    });
  });

  describe("Forecast runtime", () => {
    it("renders resolved prediction scores from the Thesis Log", async () => {
      HTMLElement.prototype.scrollTo = vi.fn();
      const forecast = getForecastCell("nonfarm-payrolls-may-2026");
      expect(forecast).toBeTruthy();
      const ledger = await loadPolicyEngineLedger();
      const resolvedForecast = withResolvedOutcome(forecast!, ledger);
      const resolvedScore = scoreResolvedForecast(resolvedForecast, ledger);

      render(
        <ForecastRuntime
          forecast={resolvedForecast}
          resolvedScore={resolvedScore}
        />,
      );

      expect(screen.getByText("resolved outcome")).toBeInTheDocument();
      expect(screen.getByText("inside 80% interval")).toBeInTheDocument();
      expect(screen.getByText("recorded in Thesis Log")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Open log →" })).toHaveAttribute(
        "href",
        "/log",
      );
      expect(screen.getByText("cdf score")).toBeInTheDocument();
      expect(screen.getByText(/CRPS/)).toBeInTheDocument();
      expect(screen.getByText(/PIT/)).toBeInTheDocument();
    }, 60_000);
  });

  describe("Forecast pages", () => {
    it("links from the forecast browser to the log and ledger", async () => {
      render(await ForecastsPage());
      expect(
        screen.getByRole("link", { name: "View Thesis Log →" }),
      ).toHaveAttribute("href", "/log");
      expect(
        screen.getByRole("link", { name: "View facts ledger →" }),
      ).toHaveAttribute("href", "/ledger");
    }, 60_000);

    it("renders the Thesis Log tables", async () => {
      render(await ForecastLogPage());

      expect(screen.getAllByText("Thesis Log").length).toBeGreaterThan(0);
      expect(screen.getByText("Recorded predictions")).toBeInTheDocument();
      expect(
        screen.getByRole("link", { name: "Machine-readable log JSON →" }),
      ).toHaveAttribute("href", "/log.json");
      expect(
        screen.getByRole("link", { name: "View facts ledger →" }),
      ).toHaveAttribute("href", "/ledger");
      expect(screen.getByText("Resolution queue")).toBeInTheDocument();
      expect(screen.getAllByText(/201-point CDFs/).length).toBeGreaterThan(0);
      expect(screen.getByText("Scored predictions")).toBeInTheDocument();
      expect(
        screen.getByText("Specs in, immutable runs out"),
      ).toBeInTheDocument();
      expect(
        screen.queryByText("Official observations"),
      ).not.toBeInTheDocument();
      expect(screen.getByText("Scoreboard")).toBeInTheDocument();
      expect(screen.getAllByText("nCRPS").length).toBeGreaterThan(0);
      expect(screen.getAllByText("CRPS").length).toBeGreaterThan(0);
      expect(screen.getByText("PIT")).toBeInTheDocument();
      expect(screen.getAllByText("201 points").length).toBeGreaterThan(0);
      const payrollLinks = screen.getAllByRole("link", {
        name: "Nonfarm payrolls, May 2026",
      });
      // The May payrolls score is legacy (seeded run time), so it appears
      // in resolutions but no longer in the chronology-verified scores table.
      expect(payrollLinks.length).toBeGreaterThanOrEqual(1);
      for (const link of payrollLinks) {
        expect(link).toHaveAttribute("href", "/nonfarm-payrolls-may-2026");
      }
    }, 60_000);

    it("renders the facts-only ledger tables", async () => {
      render(await ForecastLedgerPage());

      expect(screen.getAllByText("Ledger").length).toBeGreaterThan(0);
      expect(
        screen.getByText("PolicyEngine Ledger · targets and observations"),
      ).toBeVisible();
      expect(screen.getByText("Registered targets")).toBeInTheDocument();
      expect(screen.getByText("Official observations")).toBeInTheDocument();
      expect(
        screen.getByRole("link", { name: "Machine-readable ledger JSON →" }),
      ).toHaveAttribute("href", "/ledger.json");
      expect(
        screen.getByRole("link", { name: "View Thesis Log →" }),
      ).toHaveAttribute("href", "/log");
      expect(
        screen.queryByText("Recorded predictions"),
      ).not.toBeInTheDocument();
      expect(screen.queryByText("Scored predictions")).not.toBeInTheDocument();
    });

    it("serves the machine-readable Thesis Log JSON", async () => {
      const response = await getForecastLogJson();
      const body = await response.json();

      expect(body.schemaVersion).toBe("thesis_log_v3");
      expect(body.source.name).toBe("Thesis Log");
      expect(body.source.url).toBe("https://app.thesisinstitute.org/log");
      expect(body.source.factLedger.name).toBe("PolicyEngine Ledger");
      expect(body.counts.predictions).toBeGreaterThan(100);
      expect(body.counts.runs).toBe(body.counts.predictions);
      expect(body.counts.runs).toBeGreaterThanOrEqual(body.counts.specs);
      expect(body.counts.resolutionLinks).toBe(body.counts.specs);
      expect(body.counts.resolutionEvents).toBe(body.counts.resolutions);
      expect(body.counts.pendingResolution).toBeGreaterThan(0);
      expect(body.entries).toBeUndefined();
      expect(body.specs).toBeUndefined();
      expect(body.runs).toBeUndefined();
      expect(body.scores).toBeUndefined();
      expect(body.resolutionQueue[0].forecastSlug).toBeTruthy();
      expect(body.resolutionLinks[0].resolutionRef).toMatch(/^resolution\./);
      expect(body.resolutionEvents[0].resolutionEventId).toMatch(
        /^resolution_event\./,
      );
      expect(body.collections.entries.count).toBe(
        body.counts.predictions + body.counts.resolutions,
      );
      expect(body.collections.specs.count).toBe(body.counts.specs);
      expect(body.collections.runs.count).toBe(body.counts.runs);
      expect(body.collections.scores.count).toBe(
        body.counts.scored +
          body.counts.scoredClaimedTimeChronology +
          body.counts.scoredUnverifiedChronology +
          body.counts.scoredViolatedChronology,
      );

      const reference = body.collections.runs.chunks[0];
      const chunkResponse = await getThesisLogChunkJson(
        new Request(`http://test.local${reference.url}`),
        { params: Promise.resolve({}) },
      );
      const chunk = await chunkResponse.json();
      expect(chunk.schemaVersion).toBe("thesis_log_chunk_v1");
      expect(chunk.collection).toBe("runs");
      expect(chunk.rows[0].schemaVersion).toBe("thesis_prediction_run_v1");
      expect(chunk.rows[0].idempotencyKey).toMatch(/^[0-9a-f]{64}$/);
      expect(sha256Hex(chunk)).toBe(reference.sha256);
    });

    it("serves the clean target-architecture manifest JSON", async () => {
      const response = await getForecastTargetsJson();
      const body = await response.json();

      expect(body.schemaVersion).toBe("thesis_target_architecture_manifest_v2");
      expect(body.projectionSchemaVersion).toBe(
        "thesis_target_architecture_projection_v1",
      );
      expect(body.source).toEqual({
        records: "forecast_cells",
      });
      expect(body.sourceCommit).toBeTruthy();
      expect(body.builderVersion).toBe("thesis_target_architecture_builder_v2");
      expect(body.projectionRootSha256).toMatch(/^[0-9a-f]{64}$/);
      expect(body.projectionRootSha256).toBe(
        sha256Hex(buildTargetArchitectureRootPayload(body)),
      );
      expect(body.counts.targets).toBeGreaterThan(100);
      expect(body.counts.targetVersions).toBe(body.counts.targets);
      expect(body.counts.forecastRuns).toBeGreaterThanOrEqual(
        body.counts.targets,
      );
      expect(body.counts.forecastDistributionPoints).toBe(
        body.counts.forecastRuns * 201,
      );
      expect(body.counts.observations).toBeGreaterThan(0);
      expect(body.counts.observationVintages).toBe(body.counts.observations);
      expect(body.counts.resolutionEvents).toBeGreaterThan(0);
      expect(body.counts.scores).toBeGreaterThan(0);
      expect(body.counts.baselineCandidates).toBeGreaterThan(0);
      expect(body.counts.toolCalls).toBeGreaterThan(0);
      expect(body.counts.reviewRuns).toBeGreaterThan(0);
      expect(body.counts.judgeRuns).toBeGreaterThan(0);
      expect(body.tables.length).toBeGreaterThan(10);
      expect(
        body.tables.find(
          (table: { table: string }) => table.table === "targets",
        ),
      ).toMatchObject({
        rowCount: body.counts.targets,
        url: "/forecasts/targets/targets/manifest.json",
      });
      expect(
        body.tables.find(
          (table: { table: string }) => table.table === "forecastDistributions",
        ),
      ).toMatchObject({
        rowCount: body.counts.forecastDistributionPoints,
        url: "/forecasts/targets/forecastDistributions/manifest.json",
      });
      expect(
        body.tables.find(
          (table: { table: string }) => table.table === "forecastDistributions",
        ).chunkCount,
      ).toBeGreaterThan(1);
    });

    it("serves target-architecture table and chunk JSON", async () => {
      const tableResponse = await getForecastTargetTableJson(
        new Request(
          "http://test.local/forecasts/targets/targets/manifest.json",
        ),
        {
          params: Promise.resolve({}),
        },
      );
      const tableBody = await tableResponse.json();

      expect(tableBody.schemaVersion).toBe(
        "thesis_target_architecture_table_v2",
      );
      expect(tableBody.projectionSchemaVersion).toBe(
        "thesis_target_architecture_projection_v1",
      );
      expect(tableBody.table).toBe("targets");
      expect(tableBody.rowCount).toBeGreaterThan(100);
      expect(tableBody.projectionRootSha256).toMatch(/^[0-9a-f]{64}$/);
      expect(tableBody.sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(tableBody.rows[0].targetId).toMatch(/^target\./);
      expect(tableBody.rows[0].dataPointId).toBeTruthy();

      const distributionTableResponse = await getForecastTargetTableJson(
        new Request(
          "http://test.local/forecasts/targets/forecastDistributions/manifest.json",
        ),
        {
          params: Promise.resolve({}),
        },
      );
      const distributionTableBody = await distributionTableResponse.json();

      expect(distributionTableBody.schemaVersion).toBe(
        "thesis_target_architecture_table_v2",
      );
      expect(distributionTableBody.table).toBe("forecastDistributions");
      expect(distributionTableBody.chunkCount).toBeGreaterThan(1);
      expect(distributionTableBody.rows).toBeUndefined();
      expect(distributionTableBody.chunks[0]).toMatchObject({
        index: 0,
        url: "/forecasts/targets/forecastDistributions/0.json",
      });
      expect(distributionTableBody.chunks[0].sha256).toMatch(/^[0-9a-f]{64}$/);

      const chunkResponse = await getForecastTargetChunkJson(
        new Request(
          "http://test.local/forecasts/targets/forecastDistributions/0.json",
        ),
        {
          params: Promise.resolve({}),
        },
      );
      const chunkBody = await chunkResponse.json();

      expect(chunkBody.schemaVersion).toBe(
        "thesis_target_architecture_chunk_v2",
      );
      expect(chunkBody.table).toBe("forecastDistributions");
      expect(chunkBody.chunkIndex).toBe(0);
      expect(chunkBody.rows.length).toBeLessThanOrEqual(chunkBody.chunkSize);
      expect(chunkBody.rows[0].pointIndex).toBe(0);
      expect(chunkBody.projectionRootSha256).toBe(
        distributionTableBody.projectionRootSha256,
      );
      expect(
        sha256Hex(buildTargetArchitectureChunkHashPayload(chunkBody)),
      ).toBe(distributionTableBody.chunks[0].sha256);
    });

    it("builds the clean target-architecture projection rows", async () => {
      const ledger = await loadPolicyEngineLedger();
      const projection = buildTargetArchitectureProjection(
        withResolvedOutcomes(FORECAST_CELLS, ledger),
        ledger,
      );

      expect(projection.schemaVersion).toBe(
        "thesis_target_architecture_projection_v1",
      );
      expect(projection.targets[0].targetId).toMatch(/^target\./);
      expect(projection.targets[0].dataPointId).toBeTruthy();
      expect(projection.targetVersions[0].targetVersionId).toMatch(
        /^target_version\./,
      );
      expect(projection.targetVersions[0].resolverKind).toBeTruthy();
      expect(projection.forecastRuns[0].strategyVersionId).toMatch(
        /^strategy_version\./,
      );
      expect(projection.forecastDistributions[0].pointIndex).toBe(0);
      expect(projection.reasoningEvents[0].redactionStatus).toBe("public_only");
      expect(projection.observations[0].observationId).toMatch(/^obs\./);
      expect(
        projection.observations.some((observation: { observationId: string }) =>
          observation.observationId.startsWith("obs.history."),
        ),
      ).toBe(true);
      expect(
        projection.observations
          .filter((observation: { observationId: string }) =>
            observation.observationId.startsWith("obs.history."),
          )
          .every(
            (observation: { dataPointId?: string }) =>
              observation.dataPointId === undefined,
          ),
      ).toBe(true);
      expect(projection.observationVintages[0].vintageId).toMatch(/^vintage\./);
      expect(projection.resolutionEvents[0].resolutionEventId).toMatch(
        /^resolution_event\./,
      );
      expect(projection.scores[0].scoreId).toMatch(/^score\./);
      expect(projection.baselineCandidates[0].candidateId).toMatch(
        /^candidate\./,
      );
      expect(
        projection.baselineCandidates.every(
          (candidate: {
            artifactRefId?: string;
            sourceSeriesId?: string;
            provenance: { forecastRunId: string };
          }) =>
            (candidate.artifactRefId || candidate.sourceSeriesId) &&
            candidate.provenance.forecastRunId,
        ),
      ).toBe(true);
      expect(
        projection.baselineCandidates.some(
          (candidate: { artifactRefId?: string }) =>
            candidate.artifactRefId?.startsWith("artifact.generated_baseline."),
        ),
      ).toBe(true);
      expect(projection.toolCalls[0].runId).toMatch(/^run\./);
      expect(projection.reviewRuns[0].reviewRunId).toMatch(/^review\./);
      expect(projection.judgeRuns[0].judgeRunId).toMatch(/^judge\./);
      expect(
        projection.judgeRuns
          .filter((judgeRun: { batchId?: string }) =>
            judgeRun.batchId?.startsWith("pairwise."),
          )
          .every(
            (judgeRun: { leftRunId?: string; rightRunId?: string }) =>
              judgeRun.leftRunId && judgeRun.rightRunId,
          ),
      ).toBe(true);
    });

    it("generates a full SQL backfill for the target schema", async () => {
      const ledger = await loadPolicyEngineLedger();
      const sampleForecasts = withResolvedOutcomes(FORECAST_CELLS, ledger)
        .filter((forecast) => forecast.dataPointId)
        .slice(0, 3);
      const backfill = buildTargetArchitectureBackfillSql({
        forecasts: sampleForecasts,
        ledger,
      });

      expect(backfill.schemaVersion).toBe(
        "thesis_target_architecture_backfill_sql_v1",
      );
      expect(backfill.counts.targets).toBe(sampleForecasts.length);
      expect(backfill.counts.forecastDistributionPoints).toBe(
        backfill.projection.counts.forecastRuns * 201,
      );
      expect(backfill.sql).toContain("begin;");
      expect(backfill.sql).toContain('insert into "targets"');
      expect(backfill.sql).toContain('insert into "target_versions"');
      expect(backfill.sql).toContain('insert into "forecast_runs"');
      expect(backfill.sql).toContain('insert into "forecast_distributions"');
      expect(backfill.sql).not.toContain('insert into "prediction_specs"');
      expect(backfill.sql).not.toContain('insert into "spec_versions"');
      expect(backfill.sql).not.toContain('insert into "prediction_runs"');
      expect(backfill.sql).not.toContain('insert into "cdf_points"');
      expect(backfill.sql).not.toContain('insert into "public_traces"');
      expect(backfill.sql).not.toContain('insert into "resolution_links"');
      expect(backfill.sql).not.toContain('insert into "quality_gate_results"');
      expect(backfill.sql).toContain("on conflict do nothing;");
      expect(backfill.sql).not.toContain("undefined");
    });

    it("renders the clean target-architecture projection page", async () => {
      render(await TargetArchitecturePage());

      expect(screen.getByText("Target architecture")).toBeInTheDocument();
      expect(
        screen.getByText("Target architecture manifest →"),
      ).toHaveAttribute("href", "/targets.json");
      expect(screen.getByText("Brier no-pack LLM")).toBeInTheDocument();
      expect(
        screen.getByText("baseline.persistence.last_print"),
      ).toBeInTheDocument();
      expect(screen.getAllByText("targets").length).toBeGreaterThan(0);
      expect(screen.getAllByText("source series").length).toBeGreaterThan(0);
      expect(screen.getAllByText("resolved").length).toBeGreaterThan(0);
    });

    it("serves the machine-readable ledger JSON", async () => {
      const response = await getForecastLedgerJson();
      const body = await response.json();

      expect(body.schemaVersion).toBe("policyengine_ledger_v1");
      expect(body.source.name).toBe("PolicyEngine Ledger");
      expect(body.source.url).toBe("https://github.com/PolicyEngine/chronicle");
      expect(body.counts.facts).toBeGreaterThan(0);
      expect(body.counts.targets).toBeGreaterThan(0);
      expect(body.counts.observations).toBeGreaterThan(0);
      expect(body.counts.facts).toBe(
        body.counts.targets + body.counts.observations,
      );
      expect(
        body.entries.some(
          (entry: { kind: string }) => entry.kind === "target_registered",
        ),
      ).toBe(true);
      expect(
        body.entries.some(
          (entry: { kind: string }) => entry.kind === "observation_recorded",
        ),
      ).toBe(true);
      expect(body.scores).toBeUndefined();
      expect(body.resolutionQueue).toBeUndefined();
    });
  });

  // Paper page is now rendered by Quarto (not a React component)

  describe("shared Header component", () => {
    it("links the conditional forecasts from the public app navigation", async () => {
      const { Header } = await import("../components/Header");
      render(<Header activePage="conditionals" />);
      const navigation = screen.getByRole("navigation", {
        name: "Main navigation",
      });
      expect(
        within(navigation).getByRole("link", { name: "Conditionals" }),
      ).toHaveAttribute("href", "/lab/conditionals");
      expect(
        within(navigation).getByRole("link", { name: "Conditionals" }),
      ).toHaveAttribute("aria-current", "page");
    });
    it("renders nav links on all pages", () => {
      render(<HomePage />);
      expect(screen.getAllByText("Docs").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Forecasts").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Thesis").length).toBeGreaterThan(0);
      expect(screen.getAllByLabelText("GitHub").length).toBeGreaterThan(0);
    });

    it("flags the site as a prototype", () => {
      render(<HomePage />);
      expect(screen.getByLabelText("Prototype build")).toBeInTheDocument();
    });

    it("uses Tailwind classes (no old CSS module class names)", () => {
      const { container } = render(<HomePage />);
      const html = container.innerHTML;

      // These old CSS class names should NOT appear
      const oldClasses = [
        'class="app-dark"',
        'class="header"',
        'class="header-inner"',
        'class="nav-link"',
        'class="btn "',
        'class="btn-accent"',
        'class="btn-ghost"',
      ];

      for (const cls of oldClasses) {
        expect(html).not.toContain(cls);
      }
    });
  });

  describe("theme classes", () => {
    it("Homepage wrapper does NOT have dark theme class (light by default)", () => {
      const { container } = render(<HomePage />);
      const wrapper = container.firstElementChild as HTMLElement;
      expect(wrapper.className).not.toContain("theme-dark");
    });

    it("Thesis page renders without dark theme", () => {
      const { container } = render(<ThesisPage />);
      const wrapper = container.firstElementChild as HTMLElement;
      expect(wrapper.className).not.toContain("theme-dark");
    });

    // Paper page is now Quarto-rendered, not a React component
  });
});
