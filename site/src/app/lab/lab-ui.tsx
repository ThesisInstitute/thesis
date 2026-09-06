"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import type {
  ArtifactLink,
  Coverage,
  ExperimentSummary,
  RecordLink,
  ReleaseSummary,
  ResolutionSummary,
  ScoreSummary,
} from "@/data/generated/thesis-lab";
import { labProxyPath } from "@/lib/lab-paths";
import { useLabPages, type Resource } from "./lab-client";

export const modeLabels = {
  prospective: "Prospective",
  replay: "Replay · unranked",
  live_pilot: "Live pilot · unranked",
} as const;
export function Mode({ mode }: { mode: keyof typeof modeLabels }) {
  return (
    <span className={`lab-mode lab-mode-${mode}`}>{modeLabels[mode]}</span>
  );
}
export const words = (code: string) => code.replaceAll("_", " ");
export function number(value: number | null, digits = 3): string {
  return value === null
    ? "Not reported"
    : value.toLocaleString("en-US", { maximumFractionDigits: digits });
}
export function unit(value: string): string {
  return (
    (
      {
        percent: "%",
        usd_billions: "US$ billions",
        usd_millions: "US$ millions",
      } as Record<string, string>
    )[value] ?? value
  );
}
export function time(value: string | null): string {
  return value === null
    ? "Not reported"
    : value
        .replace("T", " ")
        .replace(/\.\d+Z$/, "Z")
        .replace("Z", " UTC");
}

export function LabShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  return (
    <div className="lab">
      <a className="lab-skip" href="#lab-main">
        Skip to content
      </a>
      <header className="lab-header">
        <Link className="lab-brand" href="/lab/forecasts">
          <span className="lab-mark" aria-hidden="true">
            ∿
          </span>
          thesis<span className="lab-brand-sub">lab</span>
        </Link>
        <nav aria-label="Forecast lab">
          {["forecasts", "experiments", "agents"].map((page) => (
            <Link
              key={page}
              href={`/lab/${page}`}
              aria-current={
                path?.startsWith(`/lab/${page}`) ? "page" : undefined
              }
            >
              {page[0].toUpperCase() + page.slice(1)}
            </Link>
          ))}
        </nav>
        <div className="lab-secondary-nav">
          <Link
            href="/lab/operations"
            aria-current={path === "/lab/operations" ? "page" : undefined}
          >
            Operations
          </Link>
          <Link href="/forecasts">Legacy archive ↗</Link>
        </div>
      </header>
      <main id="lab-main" className="lab-main">
        {children}
      </main>
      <footer className="lab-footer">
        <span>Public forecasts. Inspectable evidence.</span>
        <Link href="/core">Record inspector</Link>
        <Link href="/">Thesis Institute ↗</Link>
      </footer>
    </div>
  );
}
export function Heading({
  title,
  description,
  children,
  back,
}: {
  title: string;
  description?: string;
  children?: ReactNode;
  back?: { href: string; label: string };
}) {
  return (
    <header className="lab-heading">
      {back && (
        <Link className="lab-back" href={back.href}>
          ← {back.label}
        </Link>
      )}
      <div className="lab-heading-row">
        <div>
          <h1>{title}</h1>
          {description && <p>{description}</p>}
        </div>
        {children}
      </div>
    </header>
  );
}
export function Section({
  title,
  description,
  children,
  action,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="lab-section">
      <div className="lab-section-heading">
        <div>
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
export function Refresh({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="lab-button" onClick={onClick}>
      Refresh
    </button>
  );
}
export function State<T>({
  resource,
  empty,
  children,
}: {
  resource: Resource<T>;
  empty?: boolean;
  children: (data: T) => ReactNode;
}) {
  if (resource.state === "loading")
    return (
      <div role="status" className="lab-notice lab-loading">
        Reading experiment records…
      </div>
    );
  if (resource.state === "error")
    return (
      <div role="alert" className="lab-notice lab-error">
        <strong>Records unavailable</strong>
        <p>{resource.message}</p>
      </div>
    );
  if (empty)
    return (
      <div className="lab-notice">
        <strong>No records yet</strong>
        <p>Registered records will appear here when they are available.</p>
      </div>
    );
  return <>{children(resource.data)}</>;
}
export function PageFooter({
  loaded,
  total,
  next,
  loading,
  error,
  loadMore,
}: {
  loaded: number;
  total: number;
  next: string | null;
  loading: boolean;
  error: string | null;
  loadMore: () => void;
}) {
  return (
    <div className="lab-page-footer">
      <p>
        {loaded} of {total} loaded{next && " · more records available"}
      </p>
      {next && (
        <button
          className="lab-button"
          type="button"
          disabled={loading}
          onClick={loadMore}
        >
          {loading ? "Loading…" : "Load more"}
        </button>
      )}
      {error && (
        <p role="alert" className="lab-error-text">
          {error}
        </p>
      )}
    </div>
  );
}
export function Record({
  record,
  children,
}: {
  record: RecordLink | null;
  children?: ReactNode;
}) {
  return record ? (
    <a
      className="lab-record"
      href={labProxyPath(record.record_path)}
      target="_blank"
      rel="noopener noreferrer"
      title={record.id}
    >
      {children ?? `${record.kind} · ${record.id.slice(0, 10)}`} ↗
    </a>
  ) : (
    <span className="lab-muted">Not recorded</span>
  );
}
export function Facts({ children }: { children: ReactNode }) {
  return <dl className="lab-facts">{children}</dl>;
}
export function Fact({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
export function CoverageLine({ coverage }: { coverage: Coverage }) {
  return (
    <p className="lab-coverage">
      <strong>
        {coverage.selected_tasks}/{coverage.declared_tasks}
      </strong>{" "}
      selected tasks <span>·</span> {coverage.resolved_targets}/
      {coverage.declared_targets} targets resolved{" "}
      {coverage.failed_tasks > 0 && (
        <>
          <span>·</span> {coverage.failed_tasks} failed
        </>
      )}{" "}
      {coverage.unknown_tasks > 0 && (
        <>
          <span>·</span> {coverage.unknown_tasks} unknown
        </>
      )}{" "}
      {coverage.invalid_tasks > 0 && (
        <>
          <span>·</span> {coverage.invalid_tasks} invalid
        </>
      )}
    </p>
  );
}
export function Resolution({ value }: { value: ResolutionSummary }) {
  return (
    <span className={`lab-status lab-status-${value.state}`}>
      {value.state === "resolved"
        ? `${number(value.value)} ${unit(value.unit)} · resolved`
        : value.state === "invalid"
          ? "Resolution invalidated"
          : "Awaiting outcome"}
    </span>
  );
}
export function Release({
  value,
  detail = false,
}: {
  value: ReleaseSummary;
  detail?: boolean;
}) {
  if (value.state !== "verified")
    return (
      <span className="lab-muted">
        {value.state === "invalid"
          ? "Release evidence invalid"
          : "Release timing unknown"}
      </span>
    );
  return (
    <div className="lab-release">
      <span>
        {value.raw_value ?? `${time(value.lower)} – ${time(value.upper)}`}
      </span>
      {detail && (
        <>
          <small>
            Verified interval: {time(value.lower)} – {time(value.upper)}
            {value.timezone && ` (${value.timezone})`}
          </small>
          {value.official_url && (
            <a
              href={value.official_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Official release notice ↗
            </a>
          )}
        </>
      )}
    </div>
  );
}
export const reasonLabels: Record<string, string> = {
  live_pilot: "Live pilot: permanently unranked",
  unranked_live_pilot: "Live pilot: permanently unranked",
  replay: "Historical replay: unranked",
  late_pilot_execution: "Pilot execution crossed its deadline",
  awaiting_resolution: "Awaiting official outcome",
  no_selected_run: "No run selected",
  unresolved_attempt: "An earlier attempt remains unresolved",
  invalid_contract: "Registered contract invalid",
  invalid_resolution: "Resolution evidence invalid",
  not_selected: "Run not selected",
  missing_artifact: "Required artifact missing",
  outcome_availability_unknown: "Official outcome timing unknown",
};
export function Reasons({ codes }: { codes: readonly string[] }) {
  return codes.length ? (
    <ul className="lab-reasons">
      {codes.map((code) => (
        <li key={code}>{reasonLabels[code] ?? words(code)}</li>
      ))}
    </ul>
  ) : (
    <span className="lab-muted">None reported</span>
  );
}
export function Score({ score }: { score: ScoreSummary }) {
  return (
    <div className="lab-score">
      <div className="lab-score-values">
        <span>
          <small>CRPS</small>
          <strong>{number(score.crps)}</strong>
        </span>
        <span>
          <small>Normalized CRPS</small>
          <strong>{number(score.normalized_crps)}</strong>
        </span>
        <span>
          <small>PIT</small>
          <strong>{number(score.pit)}</strong>
        </span>
      </div>
      <p className="lab-caption">
        {score.eligibility.state === "eligible"
          ? "Eligible score"
          : score.crps !== null
            ? "Diagnostic score · excluded from ranking"
            : words(score.eligibility.state)}
        {score.scoring_version && ` · ${score.scoring_version}`}
      </p>
      <Reasons codes={score.eligibility.reason_codes} />
    </div>
  );
}
export function Evidence({
  items,
  title = "Evidence and artifacts",
}: {
  items: readonly ArtifactLink[];
  title?: string;
}) {
  return (
    <details className="lab-disclosure">
      <summary>
        {title}
        <span>{items.length} artifacts</span>
      </summary>
      {items.length === 0 ? (
        <p className="lab-muted">No artifacts reported for this record.</p>
      ) : (
        <ul className="lab-evidence">
          {items.map((item, i) => (
            <li key={`${item.sha256}-${item.role}-${i}`}>
              <div>
                <a href={labProxyPath(item.download_path)} download>
                  {words(item.role)} ↓
                </a>
                <code title={item.sha256}>{item.sha256.slice(0, 16)}…</code>
              </div>
              <span>
                {item.bytes === null
                  ? "Size not reported"
                  : `${number(item.bytes / 1024, 1)} KiB`}
                {item.bytes !== null && item.bytes > 33_554_432 && (
                  <small>
                    Exceeds browser download limit; requires operator download.
                  </small>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="lab-caption">
        Downloads preserve the archived bytes. HTML is downloaded as an
        attachment.
      </p>
    </details>
  );
}
export function ExperimentsTable({
  items,
}: {
  items: readonly ExperimentSummary[];
}) {
  return (
    <div className="lab-table-scroll">
      <table className="lab-table">
        <thead>
          <tr>
            <th>Experiment</th>
            <th>Mode</th>
            <th>Targets / agents</th>
            <th>Selected tasks</th>
            <th>Resolved</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>
                <Link className="lab-name" href={`/lab/experiments/${item.id}`}>
                  {item.title}
                </Link>
                <small>Baseline: {item.baseline.label}</small>
              </td>
              <td>
                <Mode mode={item.mode} />
              </td>
              <td className="lab-number">
                {item.target_count} / {item.agent_count}
              </td>
              <td className="lab-number">
                {item.coverage.selected_tasks}/{item.coverage.declared_tasks}
              </td>
              <td className="lab-number">
                {item.coverage.resolved_targets}/{item.target_count}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AttemptHistory({ path }: { path: string }) {
  const page = useLabPages(path, "AttemptPage");
  return (
    <State resource={page.resource}>
      {(data) => (
        <>
          <p className="lab-caption">
            Attempt sequence describes execution order. This collection is
            paginated independently.
          </p>
          {[...page.items]
            .sort((a, b) => a.sequence - b.sequence)
            .map((attempt) => (
              <article className="lab-attempt" key={attempt.id}>
                <h4>
                  Attempt {attempt.sequence}
                  <span>
                    {attempt.outcome}
                    {attempt.selected ? " · selected" : " · not selected"}
                  </span>
                </h4>
                <Facts>
                  <Fact label="Started">{time(attempt.started_at)}</Fact>
                  <Fact label="Recorded elapsed">
                    {attempt.elapsed_seconds === null
                      ? "Not reported"
                      : `${number(attempt.elapsed_seconds, 2)} s`}
                  </Fact>
                  <Fact label="Observed model">
                    {attempt.observed_model ?? "Not reported"}
                  </Fact>
                  <Fact label="Cost">Not reported</Fact>
                </Facts>
                <Record record={attempt.record}>Attempt record</Record>
                {attempt.results.map((result) => (
                  <div className="lab-attempt-result" key={result.record.id}>
                    <strong>
                      {result.reconciles_result_id
                        ? "Reconciliation"
                        : "Original result"}
                      : {result.outcome}
                    </strong>
                    <span>{time(result.recorded_at)}</span>
                    {result.reconciliation_verified !== null && (
                      <p>
                        Reconciliation{" "}
                        {result.reconciliation_verified
                          ? "verified"
                          : "not verified"}
                      </p>
                    )}
                    <Record record={result.record}>Result record</Record>{" "}
                    <Record record={result.run}>Recorded run</Record>
                    <Evidence
                      items={result.evidence_links}
                      title="Result artifacts"
                    />
                  </div>
                ))}
                <Evidence
                  items={attempt.evidence_links}
                  title="Attempt artifacts"
                />
              </article>
            ))}
          {page.items.length === 0 && (
            <p className="lab-muted">No attempts recorded.</p>
          )}
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
  );
}
export function Attempts({ path }: { path: string | null }) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="lab-disclosure"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Attempt history</summary>
      {open &&
        (path ? (
          <AttemptHistory path={path} />
        ) : (
          <p className="lab-muted">
            No task was registered for this comparison.
          </p>
        ))}
    </details>
  );
}
