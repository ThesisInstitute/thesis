"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import type {
  ExperimentDetail,
  ForecastDetail,
  MatrixCell,
  TaskComparison,
} from "@/data/generated/thesis-lab";
import { LAB_DIGEST } from "@/lib/lab-paths";
import { useLab, useLabPages, withQuery } from "./lab-client";
import { CdfChart } from "./CdfChart";
import {
  Attempts,
  CoverageLine,
  Evidence,
  ExperimentsTable,
  Fact,
  Facts,
  Heading,
  Mode,
  PageFooter,
  Reasons,
  Record,
  Refresh,
  Release,
  Resolution,
  Score,
  Section,
  State,
  number,
  time,
  unit,
  words,
} from "./lab-ui";

export function ForecastsView() {
  const page = useLabPages("/lab/forecasts?limit=20", "ForecastPage");
  return (
    <>
      <Heading
        title="Forecasts"
        description="Registered public outcomes, their forecasts and the evidence that resolves them."
      >
        <Refresh onClick={page.refresh} />
      </Heading>
      <State
        resource={page.resource}
        empty={page.resource.state === "ready" && page.items.length === 0}
      >
        {(data) => (
          <>
            <div className="lab-table-scroll">
              <table className="lab-table lab-forecast-table">
                <thead>
                  <tr>
                    <th>Public outcome</th>
                    <th>Release notice</th>
                    <th>Selected tasks</th>
                    <th>Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <Link
                          className="lab-name"
                          href={`/lab/forecasts/${item.id}`}
                        >
                          {item.title}
                        </Link>
                        <small>
                          {item.source.name} · {item.measurement_period} ·{" "}
                          {unit(item.unit)}
                        </small>
                        <small>
                          {item.experiment_count} experiments
                          {item.mode_counts.live_pilot > 0 &&
                            " · live pilot unranked"}
                          {item.mode_counts.replay > 0 && " · includes replay"}
                        </small>
                      </td>
                      <td>
                        <Release value={item.release} />
                      </td>
                      <td className="lab-number">
                        {item.coverage.selected_tasks}/
                        {item.coverage.declared_tasks}
                      </td>
                      <td>
                        <Resolution value={item.resolution} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <PageFooter
              loaded={page.items.length}
              total={data.total}
              next={data.next_cursor}
              loading={page.loadingMore}
              error={page.pageError}
              loadMore={page.loadMore}
            />
            <p className="lab-caption">
              Updated {time(data.generated_at)}. Forecasts remain grouped by
              their registered experiment.
            </p>
          </>
        )}
      </State>
    </>
  );
}

export function ForecastView({ id }: { id: string }) {
  const { resource, refresh } = useLab(
    `/lab/forecasts/${id}`,
    "ForecastDetail",
  );
  return (
    <State resource={resource}>
      {(data) => (
        <>
          <Heading
            title={data.title}
            description={`${data.source.name} · ${data.measurement_period} · ${unit(data.unit)}`}
            back={{ href: "/lab/forecasts", label: "Forecasts" }}
          >
            <Refresh onClick={refresh} />
          </Heading>
          <div className="lab-overview">
            <div>
              <Resolution value={data.resolution} />
              <CoverageLine coverage={data.coverage} />
            </div>
            <div>
              <span className="lab-eyebrow">Official release evidence</span>
              <Release value={data.release} detail />
            </div>
          </div>
          <ForecastCohorts data={data} />
          <Section
            title="Resolution contract"
            description="The submission deadline, official publication window and chosen data vintage are separate commitments."
          >
            <Facts>
              <Fact label="Resolution policy">
                {words(data.resolution_policy)}
              </Fact>
              <Fact label="Vintage date">
                {data.vintage_date ?? "Not specified"}
              </Fact>
              <Fact label="Submission deadline">
                {time(data.submission_deadline)}
              </Fact>
              <Fact label="Resolution recorded">
                {time(data.resolution.recorded_at)}
              </Fact>
            </Facts>
            <p className="lab-rule">{data.resolution_rule}</p>
            <div className="lab-links">
              <Record record={data.target}>Target record</Record>
              <Record record={data.source_record}>Source record</Record>
              <Record record={data.resolution.resolution}>
                Resolution record
              </Record>
              <Record record={data.resolution.observation}>
                Official observation
              </Record>
            </div>
            <Evidence items={data.evidence_links} />
          </Section>
        </>
      )}
    </State>
  );
}

function ForecastCohorts({ data }: { data: ForecastDetail }) {
  const router = useRouter();
  const search = useSearchParams();
  const requested = search.get("experiment_id");
  const selected = requested && LAB_DIGEST.test(requested) ? requested : null;
  const page = useLabPages(data.experiments_path, "ExperimentPage");
  const selectedDetail = useLab(
    selected ? `/lab/experiments/${selected}` : null,
    "ExperimentDetail",
  );
  const current =
    selectedDetail.resource.state === "ready"
      ? selectedDetail.resource.data
      : null;
  return (
    <Section
      title="Forecast comparison"
      description="Choose one experiment to compare methods with the same declared cohort."
    >
      <State resource={page.resource}>
        {(result) => (
          <>
            <label className="lab-cohort-selector">
              <span>Experiment</span>
              <select
                value={selected ?? ""}
                onChange={(event) =>
                  router.replace(
                    `/lab/forecasts/${data.id}${event.target.value ? `?experiment_id=${event.target.value}` : ""}`,
                    { scroll: false },
                  )
                }
              >
                <option value="">Select an experiment</option>
                {selected &&
                  !page.items.some((item) => item.id === selected) && (
                    <option value={selected}>
                      {current?.title ?? "Loading selected experiment…"}
                    </option>
                  )}
                {page.items.map((item) => (
                  <option value={item.id} key={item.id}>
                    {item.title}
                  </option>
                ))}
              </select>
              {current && (
                <>
                  <Mode mode={current.mode} />
                  <Link href={`/lab/experiments/${selected}`}>
                    Open experiment →
                  </Link>
                </>
              )}
            </label>
            {page.items.length === 0 && (
              <p className="lab-muted">
                This target has no registered experiment yet.
              </p>
            )}
            <PageFooter
              loaded={page.items.length}
              total={result.total}
              next={result.next_cursor}
              loading={page.loadingMore}
              error={page.pageError}
              loadMore={page.loadMore}
            />
            {selected ? (
              <ForecastComparisons
                key={selected}
                target={data}
                experimentId={selected}
              />
            ) : (
              <div className="lab-notice">
                Select a cohort to inspect its forecasts, baseline and attempts.
              </div>
            )}
          </>
        )}
      </State>
    </Section>
  );
}

function ForecastComparisons({
  target,
  experimentId,
}: {
  target: ForecastDetail;
  experimentId: string;
}) {
  const page = useLabPages(
    `/lab/forecasts/${target.id}/comparisons?experiment_id=${experimentId}&limit=20`,
    "ComparisonPage",
  );
  return (
    <State resource={page.resource}>
      {(data) => (
        <>
          <CdfChart
            comparisons={page.items}
            outcome={target.resolution.value}
            unitName={target.unit}
          />
          <div className="lab-table-scroll">
            <table className="lab-table">
              <thead>
                <tr>
                  <th>Method</th>
                  <th>Execution / selection</th>
                  <th>Median</th>
                  <th>80% interval</th>
                  <th>Raw CRPS</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((row) => (
                  <tr key={row.task.id}>
                    <td>
                      <Link
                        className="lab-name"
                        href={`/lab/agents/${row.agent.id}`}
                      >
                        {row.agent.label}
                      </Link>
                      {row.is_baseline && <small>Persistence baseline</small>}
                      <Mode mode={row.mode} />
                    </td>
                    <td>
                      {words(row.execution.state)}
                      <small>
                        {row.selected_run ? "Run selected" : "No selected run"}
                      </small>
                    </td>
                    <td className="lab-number">
                      {row.quantiles
                        ? number(row.quantiles.q50)
                        : "Not reported"}
                    </td>
                    <td className="lab-number">
                      {row.quantiles
                        ? `${number(row.quantiles.q10)} – ${number(row.quantiles.q90)}`
                        : "Not reported"}
                    </td>
                    <td className="lab-number">
                      {number(row.score.crps)}
                      {row.score.crps !== null &&
                        row.score.eligibility.state !== "eligible" && (
                          <small>Diagnostic only</small>
                        )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="lab-caption">
            Median and 80% interval use the server’s inverse piecewise linear
            CDF. Reported agent summaries remain in each original distribution.
          </p>
          <PageFooter
            loaded={page.items.length}
            total={data.total}
            next={data.next_cursor}
            loading={page.loadingMore}
            error={page.pageError}
            loadMore={page.loadMore}
          />
          {page.items.map((row) => (
            <MethodDetail row={row} key={row.task.id} />
          ))}
          {page.items.length === 0 && (
            <p className="lab-muted">
              No task records are present for this target in the selected
              experiment. The experiment matrix retains any missing membership
              as invalid.
            </p>
          )}
        </>
      )}
    </State>
  );
}

function MethodDetail({ row }: { row: TaskComparison }) {
  return (
    <details className="lab-method-detail" id={`method-${row.agent.id}`}>
      <summary>
        <span>{row.agent.label}</span>
        <span>
          {words(row.execution.state)} ·{" "}
          {row.selected_run ? "selected" : "not selected"}
        </span>
      </summary>
      <div className="lab-method-body">
        <Mode mode={row.mode} />
        <Facts>
          <Fact label="Information cutoff">
            {time(row.declared_information_cutoff)}
          </Fact>
          <Fact label="Evidence frozen">
            {time(row.effective_information_boundary)}
          </Fact>
          <Fact label="Submission deadline">
            {time(row.submission_deadline)}
          </Fact>
          <Fact label="Recorded attempt elapsed">
            {row.execution.elapsed_seconds === null
              ? "Not reported"
              : `${number(row.execution.elapsed_seconds, 2)} s`}
          </Fact>
          <Fact label="Requested model">{row.agent.model_request}</Fact>
          <Fact label="Observed model">
            {row.agent.observed_model ?? "Not reported"}
          </Fact>
          <Fact label="Reported point estimate">
            {row.distribution
              ? number(row.distribution.summary.pointEstimate)
              : "Not reported"}
          </Fact>
          <Fact label="Measured cost">Not reported</Fact>
        </Facts>
        <Score score={row.score} />
        <div className="lab-links">
          <Record record={row.task}>Task record</Record>
          <Record record={row.selected_run}>
            Selected run and original distribution
          </Record>
        </div>
        <Attempts path={row.execution.attempts_path} />
        <Evidence items={row.evidence_links} />
      </div>
    </details>
  );
}

export function ExperimentsView() {
  const page = useLabPages("/lab/experiments?limit=20", "ExperimentPage");
  return (
    <>
      <Heading
        title="Experiments"
        description="Compare registered methods on the same target cohort."
      >
        <Refresh onClick={page.refresh} />
      </Heading>
      <State
        resource={page.resource}
        empty={page.resource.state === "ready" && page.items.length === 0}
      >
        {(data) => (
          <>
            <ExperimentsTable items={page.items} />
            <PageFooter
              loaded={page.items.length}
              total={data.total}
              next={data.next_cursor}
              loading={page.loadingMore}
              error={page.pageError}
              loadMore={page.loadMore}
            />
          </>
        )}
      </State>
    </>
  );
}

export function ExperimentView({ id }: { id: string }) {
  const { resource, refresh } = useLab(
    `/lab/experiments/${id}`,
    "ExperimentDetail",
  );
  return (
    <State resource={resource}>
      {(data) => (
        <>
          <Heading
            title={data.title}
            description={`${data.target_count} registered targets · ${data.agent_count} methods`}
            back={{ href: "/lab/experiments", label: "Experiments" }}
          >
            <Refresh onClick={refresh} />
          </Heading>
          <div className="lab-overview">
            <div>
              <Mode mode={data.mode} />
              <CoverageLine coverage={data.coverage} />
            </div>
            <div>
              <span className="lab-eyebrow">Baseline</span>
              <Link href={`/lab/agents/${data.baseline.id}`}>
                {data.baseline.label}
              </Link>
            </div>
          </div>
          <ExperimentMatrix experiment={data} />
          <Section
            title="Method results"
            description="Scores and paired coverage apply to this experiment only. Incomplete coverage does not establish a rank."
          >
            <ResultTable path={data.results_path} by="agent" />
          </Section>
          <Section title="Registration">
            <Facts>
              <Fact label="Hypothesis">Not registered</Fact>
              <Fact label="Registration deadline">
                {time(data.registration_deadline)}
              </Fact>
              <Fact label="Information cutoff">
                {time(data.declared_information_cutoff)}
              </Fact>
              <Fact label="Evidence frozen">
                {time(data.effective_information_boundary)}
              </Fact>
              <Fact label="Ranking policy">{words(data.ranking_policy)}</Fact>
            </Facts>
            <Record record={data.record}>Complete experiment record</Record>
          </Section>
        </>
      )}
    </State>
  );
}

function MatrixValue({ cell }: { cell: MatrixCell }) {
  return (
    <>
      <span className="lab-cell-state">{words(cell.execution.state)}</span>
      <strong>{cell.quantiles ? number(cell.quantiles.q50) : "—"}</strong>
      <small>
        {cell.selected_run ? "Selected forecast" : "No selected run"}
      </small>
      {cell.score.crps !== null && (
        <small>
          CRPS {number(cell.score.crps)}
          {cell.score.eligibility.state !== "eligible" && " · diagnostic"}
        </small>
      )}
      {cell.execution.state === "invalid" && <small>Contract invalid</small>}
    </>
  );
}
function ExperimentMatrix({ experiment }: { experiment: ExperimentDetail }) {
  const [rows, setRows] = useState<(string | null)[]>([null]);
  const [methods, setMethods] = useState<(string | null)[]>([null]);
  const path = withQuery(
    withQuery(
      withQuery(
        withQuery(experiment.matrix_path, "limit", "20"),
        "method_limit",
        "10",
      ),
      "after",
      rows.at(-1)!,
    ),
    "method_after",
    methods.at(-1)!,
  );
  const { resource } = useLab(path, "MatrixPage");
  return (
    <Section
      title="Target × method"
      description="Every declared target and method appears, including missing or unsuccessful tasks."
    >
      <State resource={resource}>
        {(data) => (
          <>
            <div className="lab-table-scroll">
              <table className="lab-table lab-matrix">
                <thead>
                  <tr>
                    <th>Target</th>
                    {data.columns.map((column) => (
                      <th key={column.forecaster_id}>
                        <Link href={`/lab/agents/${column.forecaster_id}`}>
                          {column.agent.label}
                        </Link>
                        {column.is_baseline && <small>Baseline</small>}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row) => (
                    <tr key={row.target_id}>
                      <th>
                        <Link
                          href={`/lab/forecasts/${row.target_id}?experiment_id=${experiment.id}`}
                        >
                          {row.title}
                        </Link>
                        <small>
                          {row.measurement_period} · {unit(row.unit)}
                        </small>
                      </th>
                      {row.cells.map((cell) => (
                        <td key={cell.forecaster_id}>
                          <Link
                            className={`lab-matrix-cell lab-execution-${cell.execution.state}`}
                            href={`/lab/forecasts/${row.target_id}?experiment_id=${experiment.id}#method-${cell.forecaster_id}`}
                          >
                            <MatrixValue cell={cell} />
                          </Link>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="lab-matrix-controls">
              <div>
                <span>
                  {data.rows.length} of {data.total_targets} targets · page{" "}
                  {rows.length}
                </span>
                <button
                  className="lab-button"
                  disabled={rows.length === 1}
                  onClick={() => setRows((old) => old.slice(0, -1))}
                >
                  Previous targets
                </button>
                <button
                  className="lab-button"
                  disabled={!data.next_cursor}
                  onClick={() => setRows((old) => [...old, data.next_cursor])}
                >
                  Next targets
                </button>
              </div>
              <div>
                <span>
                  {data.columns.length} of {data.total_methods} methods · page{" "}
                  {methods.length}
                </span>
                <button
                  className="lab-button"
                  disabled={methods.length === 1}
                  onClick={() => setMethods((old) => old.slice(0, -1))}
                >
                  Previous methods
                </button>
                <button
                  className="lab-button"
                  disabled={!data.next_method_cursor}
                  onClick={() =>
                    setMethods((old) => [...old, data.next_method_cursor])
                  }
                >
                  Next methods
                </button>
              </div>
            </div>
          </>
        )}
      </State>
    </Section>
  );
}

function ResultTable({
  path,
  by,
}: {
  path: string;
  by: "agent" | "experiment";
}) {
  const page = useLabPages(path, "ExperimentResultPage");
  return (
    <State resource={page.resource}>
      {(data) => (
        <>
          <div className="lab-table-scroll">
            <table className="lab-table">
              <thead>
                <tr>
                  <th>{by === "agent" ? "Method" : "Experiment"}</th>
                  <th>Mode / rank</th>
                  <th>Paired targets</th>
                  <th>Mean normalized CRPS</th>
                  <th>Recorded elapsed</th>
                  <th>Exclusions</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((row) => (
                  <tr key={`${row.experiment_id}-${row.forecaster_id}`}>
                    <td>
                      <Link
                        className="lab-name"
                        href={
                          by === "agent"
                            ? `/lab/agents/${row.forecaster_id}`
                            : `/lab/experiments/${row.experiment_id}`
                        }
                      >
                        {by === "agent"
                          ? row.agent.label
                          : row.experiment_title}
                      </Link>
                      {row.is_baseline && <small>Baseline</small>}
                      <small>
                        {row.attempt_counts.total} attempts ·{" "}
                        {row.attempt_counts.failed} failed ·{" "}
                        {row.attempt_counts.unknown} unknown
                      </small>
                    </td>
                    <td>
                      <Mode mode={row.mode} />
                      <small>
                        {row.rank === null ? "Unranked" : `Rank ${row.rank}`}
                      </small>
                    </td>
                    <td className="lab-number">
                      {row.paired_coverage}/{row.targets}
                    </td>
                    <td className="lab-number">
                      {number(row.mean_normalized_crps)}
                    </td>
                    <td className="lab-number">
                      {row.mean_elapsed_seconds === null
                        ? "Not reported"
                        : `${number(row.mean_elapsed_seconds, 2)} s`}
                      <small>
                        {row.elapsed_sample_count} measured attempts
                      </small>
                    </td>
                    <td>
                      <Reasons codes={row.exclusions} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {page.items.length === 0 && (
            <p className="lab-muted">No experiment results reported.</p>
          )}
          <PageFooter
            loaded={page.items.length}
            total={data.total}
            next={data.next_cursor}
            loading={page.loadingMore}
            error={page.pageError}
            loadMore={page.loadMore}
          />
          <p className="lab-caption">
            Monetary cost is not reported. Recorded attempt elapsed time is not
            provider latency.
          </p>
        </>
      )}
    </State>
  );
}

export function AgentsView() {
  const page = useLabPages("/lab/agents?limit=20", "AgentPage");
  return (
    <>
      <Heading
        title="Agents"
        description="Exact forecaster configurations, compared within their registered experiments."
      >
        <Refresh onClick={page.refresh} />
      </Heading>
      <State
        resource={page.resource}
        empty={page.resource.state === "ready" && page.items.length === 0}
      >
        {(data) => (
          <>
            <div className="lab-table-scroll">
              <table className="lab-table">
                <thead>
                  <tr>
                    <th>Forecaster version</th>
                    <th>Requested / observed model</th>
                    <th>Experiments</th>
                    <th>Declared tasks</th>
                    <th>Attempts</th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((agent) => (
                    <tr key={agent.id}>
                      <td>
                        <Link
                          className="lab-name"
                          href={`/lab/agents/${agent.id}`}
                        >
                          {agent.label}
                        </Link>
                        <small>
                          {agent.provider} · {agent.agent_version}
                        </small>
                      </td>
                      <td>
                        {agent.model_request}
                        <small>
                          Observed: {agent.observed_model ?? "Not reported"}
                        </small>
                      </td>
                      <td className="lab-number">{agent.experiment_count}</td>
                      <td className="lab-number">
                        {agent.declared_task_count}
                      </td>
                      <td>
                        {agent.attempt_counts.total}
                        <small>
                          {agent.attempt_counts.failed} failed ·{" "}
                          {agent.attempt_counts.unknown} unknown
                        </small>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <PageFooter
              loaded={page.items.length}
              total={data.total}
              next={data.next_cursor}
              loading={page.loadingMore}
              error={page.pageError}
              loadMore={page.loadMore}
            />
          </>
        )}
      </State>
    </>
  );
}

export function AgentView({ id }: { id: string }) {
  const { resource, refresh } = useLab(`/lab/agents/${id}`, "AgentDetail");
  return (
    <State resource={resource}>
      {(data) => (
        <>
          <Heading
            title={data.label}
            description={`${data.provider} · ${data.agent_version} · ${data.experiment_count} experiments`}
            back={{ href: "/lab/agents", label: "Agents" }}
          >
            <Refresh onClick={refresh} />
          </Heading>
          <Facts>
            <Fact label="Requested model">{data.model_request}</Fact>
            <Fact label="Observed model">
              {data.observed_model ?? "Not reported"}
            </Fact>
            <Fact label="Harness">{data.harness_version}</Fact>
            <Fact label="Execution policy">{words(data.execution_policy)}</Fact>
            <Fact label="Retry policy">{words(data.retry_policy)}</Fact>
            <Fact label="Cost">Not reported</Fact>
          </Facts>
          <Section
            title="Results by experiment"
            description="Each row retains its own cohort, baseline and eligibility rules. There is no global rank."
          >
            <ResultTable path={data.experiments_path} by="experiment" />
          </Section>
          <Section title="Recorded configuration">
            <Record record={data.record}>Forecaster record</Record>
            <details className="lab-disclosure">
              <summary>Inference settings</summary>
              <pre>{JSON.stringify(data.inference_settings, null, 2)}</pre>
            </details>
            <Evidence
              items={[
                data.prompt_template,
                data.system_prompt,
                data.tool_policy,
                ...(data.briefing ? [data.briefing] : []),
              ]}
              title="Prompt, tools and briefing"
            />
          </Section>
        </>
      )}
    </State>
  );
}

const recovery: Record<string, string> = {
  schedule_capture:
    "An operator can register a capture schedule for this target.",
  inspect_capture:
    "An operator should inspect the capture schedule and its last failure.",
  inspect_resolution:
    "Review the registered vintage and official resolution evidence.",
  inspect_jobs: "Review the failed or expired background job before retrying.",
  reconcile_attempt:
    "Reconcile the unknown attempt from its sealed evidence before any new execution.",
};
export function OperationsView() {
  const page = useLabPages("/lab/operations?limit=20", "OperationsSummary");
  return (
    <>
      <Heading
        title="Operations"
        description="Capture schedules and recorded worker activity. Operational times do not establish forecast eligibility."
      >
        <Refresh onClick={page.refresh} />
      </Heading>
      <State resource={page.resource}>
        {(data) => (
          <>
            <Facts>
              <Fact label="Database">
                Available · {time(data.database.checked_at)}
              </Fact>
              <Fact label="Forecast worker">
                {words(data.worker.state)}
                <small>{time(data.worker.last_activity_at)}</small>
              </Fact>
              <Fact label="Capture worker">
                {words(data.polling.worker.status)}
                <small>{time(data.polling.worker.last_poll_at)}</small>
              </Fact>
              <Fact label="Next capture">
                {time(data.polling.next_poll_at)}
              </Fact>
              <Fact label="Last successful capture">
                {time(data.polling.last_success_at)}
              </Fact>
              <Fact label="Capture scheduling">
                {words(data.polling.state)} · {data.polling.scheduled_sources}{" "}
                sources
              </Fact>
            </Facts>
            <Section title="Background jobs">
              <div className="lab-job-counts">
                {Object.entries(data.jobs).map(([state, count]) => (
                  <span key={state}>
                    <strong>{count}</strong>
                    {words(state)}
                  </span>
                ))}
              </div>
              <p className="lab-caption">
                A completed job does not show that a worker is currently
                running. An active lease establishes activity only at the
                observation time.
              </p>
            </Section>
            <Section title="Target monitoring">
              <div className="lab-table-scroll">
                <table className="lab-table">
                  <thead>
                    <tr>
                      <th>Target</th>
                      <th>Capture state</th>
                      <th>Next poll / last success</th>
                      <th>Resolution</th>
                      <th>Attention</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.items.map((target) => (
                      <tr key={target.target_id}>
                        <td>
                          <Link
                            className="lab-name"
                            href={`/lab/forecasts/${target.target_id}`}
                          >
                            {target.title}
                          </Link>
                          <Release value={target.release} />
                        </td>
                        <td>{words(target.polling_state)}</td>
                        <td>
                          <span>{time(target.next_poll_at)}</span>
                          <small>
                            Last success: {time(target.last_success_at)}
                          </small>
                        </td>
                        <td>
                          <Resolution value={target.resolution} />
                        </td>
                        <td>
                          {target.attention_codes.length ? (
                            <ul className="lab-reasons">
                              {target.attention_codes.map((code) => (
                                <li key={code}>{words(code)}</li>
                              ))}
                            </ul>
                          ) : (
                            <span className="lab-muted">None reported</span>
                          )}
                          {target.recovery_action_codes.map((code) => (
                            <p className="lab-caption" key={code}>
                              {recovery[code]}
                            </p>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {page.items.length === 0 && (
                <p className="lab-notice">
                  No target monitoring rows are available.
                </p>
              )}
              <PageFooter
                loaded={page.items.length}
                total={data.total}
                next={data.next_cursor}
                loading={page.loadingMore}
                error={page.pageError}
                loadMore={page.loadMore}
              />
            </Section>
          </>
        )}
      </State>
    </>
  );
}
