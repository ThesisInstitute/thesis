"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type {
  ArtifactLink,
  ConditionalDetail,
  ConditionalSummary,
  Quantiles,
} from "@/data/generated/thesis-lab";
import { labProxyPath } from "@/lib/lab-paths";
import { DistributionChart } from "./CdfChart";
import { useLab, useLabPages, withQuery } from "./lab-client";
import {
  Evidence,
  Fact,
  Facts,
  Heading,
  PageFooter,
  Refresh,
  Section,
  State,
  number,
  time,
  unit,
  words,
} from "./lab-ui";

function ConditionalState({
  state,
}: {
  state: ConditionalSummary["execution_state"];
}) {
  return (
    <span className={`lab-status lab-conditional-${state}`}>
      {words(state)}
    </span>
  );
}

export function ConditionalsView() {
  const [model, setModel] = useState("");
  const page = useLabPages(
    withQuery("/lab/conditionals?limit=20", "requested_model", model || null),
    "ConditionalPage",
  );
  return (
    <>
      <Heading
        title="Conditionals"
        description="Paired forecasts under two stated conditions, with one shared reference and evidence record."
      >
        <Refresh onClick={page.refresh} />
      </Heading>
      <p className="lab-conditional-disclosure">
        Exploratory · local operator · scoring not registered
      </p>
      <State resource={page.resource}>
        {(data) => (
          <>
            <label className="lab-cohort-selector lab-model-filter">
              <span>Requested model</span>
              <select
                value={model}
                onChange={(event) => setModel(event.target.value)}
              >
                <option value="">All models</option>
                {data.requested_models.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            {page.items.length === 0 ? (
              <div className="lab-notice">
                <strong>
                  {model
                    ? "No attempts for this model"
                    : "No conditional attempts yet"}
                </strong>
                <p>
                  Paired forecasts and unsuccessful attempts will appear here
                  when recorded.
                </p>
              </div>
            ) : (
              <div className="lab-table-scroll">
                <table className="lab-table">
                  <thead>
                    <tr>
                      <th>Conditional question</th>
                      <th>Requested / provider-reported model</th>
                      <th>Attempt</th>
                      <th>Started</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.items.map((item) => (
                      <tr key={item.id}>
                        <td>
                          <Link
                            className="lab-name"
                            href={`/lab/conditionals/${item.id}`}
                          >
                            {item.title}
                          </Link>
                          <small>
                            {item.measurement_period} · {unit(item.unit)}
                          </small>
                        </td>
                        <td className="lab-conditional-model-cell">
                          <span>{item.requested_model}</span>
                          <small>
                            Provider-reported:{" "}
                            {item.provider_metadata?.reported_model ??
                              "Not reported"}
                          </small>
                        </td>
                        <td>
                          <ConditionalState state={item.execution_state} />
                          {item.error_code && (
                            <small>{words(item.error_code)}</small>
                          )}
                        </td>
                        <td className="lab-number">
                          {time(item.started_at)}
                          <small>{item.id.slice(0, 12)}</small>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
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
              Recorded attempts remain individually inspectable, including
              failed and unknown outcomes. Updated {time(data.generated_at)}.
            </p>
          </>
        )}
      </State>
    </>
  );
}

export function ConditionalView({ id }: { id: string }) {
  const { resource, refresh } = useLab(
    `/lab/conditionals/${id}`,
    "ConditionalDetail",
  );
  return (
    <State resource={resource}>
      {(data) => (
        <>
          <Heading
            title={data.title}
            description={data.question}
            back={{ href: "/lab/conditionals", label: "Conditionals" }}
          >
            <div className="lab-conditional-actions">
              <ShareLink key={id} />
              <Refresh onClick={refresh} />
            </div>
          </Heading>
          <div className="lab-conditional-status">
            <p className="lab-conditional-disclosure">
              Exploratory · local operator · scoring not registered
            </p>
            <span>
              Attempt <ConditionalState state={data.execution_state} />
            </span>
          </div>
          <div className="lab-conditional-identity">
            <Facts>
              <Fact label="Requested model">{data.requested_model}</Fact>
              <Fact label="Provider-reported model">
                {data.provider_metadata?.reported_model ?? "Not reported"}
              </Fact>
              <Fact label="Completed">{time(data.finished_at)}</Fact>
            </Facts>
            <p className="lab-caption">
              {data.provider_metadata
                ? "Provider-reported metadata matches the recorded response. Model authorship is unverified."
                : "No provider model metadata was reported. Model authorship is unverified."}
              {data.provider_metadata && (
                <>
                  {" "}
                  <a
                    className="lab-record"
                    href={labProxyPath(
                      data.provider_metadata.source_artifact.download_path,
                    )}
                    download
                  >
                    Provider response ↓
                  </a>
                </>
              )}
            </p>
          </div>
          <ConditionalReviews data={data} />
          {data.response ? (
            <PairedDistributions data={data} />
          ) : (
            <div className="lab-notice">
              <strong>
                {data.execution_state === "running"
                  ? "Paired forecast in progress"
                  : "No validated paired forecast"}
              </strong>
              <p>
                {data.execution_state === "unknown"
                  ? "No confirmed result was recorded before the deadline. Its archived attempt remains available below."
                  : data.execution_state === "failed"
                    ? "This attempt failed validation or execution. Its archived attempt remains available below."
                    : "The attempt is recorded. Refresh to check for its result."}
              </p>
              {data.error_code && <p>{words(data.error_code)}</p>}
            </div>
          )}
          <RevisionHistory data={data} />
          <Section
            title="Conditions"
            description={`Condition deadline: ${time(data.contract.condition_deadline)}. ${data.contract.condition_resolution_note}`}
          >
            <div className="lab-conditional-arms">
              {data.contract.arms.map((arm, i) => (
                <article key={arm.id}>
                  <h3>{arm.label}</h3>
                  <p>{arm.condition}</p>
                  {arm.assumptions.length > 0 && (
                    <>
                      <h4>Assumptions</h4>
                      <ul>
                        {arm.assumptions.map((assumption, j) => (
                          <li key={j}>{assumption}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  {data.response && (
                    <details className="lab-disclosure">
                      <summary>Forecast reasoning</summary>
                      <p className="lab-conditional-prose">
                        {data.response.arms[i].reasoning}
                      </p>
                    </details>
                  )}
                </article>
              ))}
            </div>
            <p className="lab-caption">
              {data.contract.exhaustive
                ? "These conditions are declared exhaustive."
                : "These conditions are not declared exhaustive; other policy states may occur."}
            </p>
          </Section>
          <ConditionalEvidence data={data} />
          <Section title="Outcome and scope">
            <Facts>
              <Fact label="Outcome">{data.contract.outcome.name}</Fact>
              <Fact label="Measure">{data.contract.outcome.measure}</Fact>
              <Fact label="Period and unit">
                {data.measurement_period} · {unit(data.unit)}
              </Fact>
              <Fact label="Geography">
                {data.contract.outcome.geography} ·{" "}
                {data.contract.outcome.country}
              </Fact>
              <Fact label="Population">{data.contract.outcome.population}</Fact>
              <Fact label="Official release date">
                {data.contract.outcome.release_date ?? "Not announced"}
              </Fact>
            </Facts>
            <p className="lab-rule">{data.contract.outcome.resolution_rule}</p>
            <a
              className="lab-record"
              href={data.contract.outcome.resolution_source_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Resolution source ↗
            </a>
            {data.contract.limitations.length > 0 && (
              <ul className="lab-conditional-limitations">
                {data.contract.limitations.map((limitation, i) => (
                  <li key={i}>{limitation}</li>
                ))}
              </ul>
            )}
          </Section>
          <Section
            title="Attempt and trace"
            description="The local operator's recorded execution and original artifacts. This lane has no registered scoring or ranking."
          >
            <Facts>
              <Fact label="Requested model">
                {data.requested_model}
                <small>Model authorship unverified</small>
              </Fact>
              <Fact label="Provider-reported model">
                {data.provider_metadata?.reported_model ?? "Not reported"}
              </Fact>
              {data.provider_metadata && (
                <Fact label="Provider response ID">
                  {data.provider_metadata.response_id ?? "Not reported"}
                </Fact>
              )}
              <Fact label="Started">{time(data.started_at)}</Fact>
              <Fact label="Finished">{time(data.finished_at)}</Fact>
              <Fact label="Execution deadline">{time(data.expires_at)}</Fact>
              <Fact label="Result">
                <ConditionalState state={data.execution_state} />
                {data.error_code && <small>{words(data.error_code)}</small>}
              </Fact>
            </Facts>
            {data.provider_metadata && (
              <details className="lab-disclosure">
                <summary>Provider-reported usage</summary>
                <Facts>
                  <Fact label="Prompt tokens">
                    {data.provider_metadata.usage.prompt_tokens ??
                      "Not reported"}
                  </Fact>
                  <Fact label="Output tokens">
                    {data.provider_metadata.usage.output_tokens ??
                      "Not reported"}
                  </Fact>
                  <Fact label="Thought tokens">
                    {data.provider_metadata.usage.thought_tokens ??
                      "Not reported"}
                  </Fact>
                  <Fact label="Total tokens">
                    {data.provider_metadata.usage.total_tokens ??
                      "Not reported"}
                  </Fact>
                </Facts>
              </details>
            )}
            <details className="lab-disclosure">
              <summary>Record identifiers</summary>
              <Facts>
                <Fact label="Attempt">
                  <code>{data.id}</code>
                </Fact>
                <Fact label="Contract">
                  <code>{data.contract_id}</code>
                </Fact>
                <Fact label="Shared evidence">
                  <code>{data.shared_evidence_id}</code>
                </Fact>
              </Facts>
            </details>
            <Evidence
              items={data.artifacts}
              title="Prompt, response and execution artifacts"
            />
          </Section>
        </>
      )}
    </State>
  );
}

function ShareLink() {
  const [copied, setCopied] = useState(false);
  const [fallback, setFallback] = useState<string | null>(null);
  async function share() {
    const url = window.location.href;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setFallback(null);
    } catch {
      setCopied(false);
      setFallback(url);
    }
  }
  return (
    <div className="lab-share">
      <button className="lab-button" type="button" onClick={share}>
        Share
      </button>
      <span className="lab-caption" role="status">
        {copied ? "Link copied" : ""}
      </span>
      {fallback && (
        <label className="lab-share-fallback">
          Copy this link
          <input
            readOnly
            value={fallback}
            onFocus={(event) => event.target.select()}
          />
        </label>
      )}
    </div>
  );
}

/** Show exact archived text on demand without treating its contents as markup. */
function ArtifactText({
  artifact,
  label,
}: {
  artifact: ArtifactLink;
  label: string;
}) {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setContent(null);
    setError(false);
    void fetch(labProxyPath(artifact.download_path), {
      credentials: "omit",
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Artifact unavailable");
        const value = await response.text();
        if (!controller.signal.aborted) setContent(value);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError(true);
      });
    return () => controller.abort();
  }, [open, artifact.download_path]);
  return (
    <details
      className="lab-disclosure"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>{label}</summary>
      {open &&
        (error ? (
          <p className="lab-muted">
            The archived text could not be loaded. Its download link remains
            available.
          </p>
        ) : content === null ? (
          <p className="lab-muted">Loading recorded text…</p>
        ) : (
          <pre className="lab-conditional-artifact-text">{content}</pre>
        ))}
      <a
        className="lab-record"
        href={labProxyPath(artifact.download_path)}
        download
      >
        Download recorded text ↓
      </a>
    </details>
  );
}

function ConditionalReviews({ data }: { data: ConditionalDetail }) {
  if (data.reviews.length === 0)
    return (
      <p className="lab-caption lab-conditional-no-review">
        No source or reasoning review recorded.
      </p>
    );
  return (
    <section
      className="lab-conditional-reviews"
      aria-label="Source and reasoning reviews"
    >
      {data.reviews.map((review) => (
        <article
          key={review.id}
          id={`conditional-review-${review.id}`}
          className="lab-conditional-review"
        >
          <h2>
            {review.outcome === "issues_remaining"
              ? "Review findings remain"
              : "No actionable findings reported"}
          </h2>
          <p className="lab-caption">
            {review.reviewer} · {time(review.recorded_at)} · operator assessment
          </p>
          <ul className="lab-conditional-review-findings">
            {review.findings.map((finding) => (
              <li key={finding.id}>
                <strong>{finding.title}</strong>
                <p>{finding.detail}</p>
                <div className="lab-links">
                  {finding.source_ids.map((sourceId) => (
                    <a
                      key={sourceId}
                      className="lab-record"
                      href={`#conditional-source-${sourceId}`}
                    >
                      {
                        data.contract.sources.find(
                          (source) => source.id === sourceId,
                        )!.title
                      }
                    </a>
                  ))}
                </div>
                <small className="lab-muted">
                  Response location: {finding.response_location}
                </small>
              </li>
            ))}
          </ul>
          <ArtifactText artifact={review.report} label="Full review report" />
          <a
            className="lab-record"
            href={labProxyPath(review.record_artifact.download_path)}
            download
          >
            Review record ↓
          </a>
        </article>
      ))}
    </section>
  );
}

function RevisionHistory({ data }: { data: ConditionalDetail }) {
  if (data.revision_history.length < 2) return null;
  return (
    <Section
      title="Revision history"
      description="Each recorded attempt retains its original forecasts, reasoning and review."
    >
      <div className="lab-table-scroll">
        <table className="lab-table lab-conditional-revisions">
          <thead>
            <tr>
              <th>Attempt</th>
              <th>Requested model</th>
              {data.contract.arms.map((arm) => (
                <th key={arm.id}>
                  {arm.label}
                  <small>Median · 80% interval</small>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.revision_history.map((entry) => (
              <tr
                key={entry.attempt_id}
                aria-current={entry.attempt_id === data.id ? "true" : undefined}
              >
                <td>
                  <Link
                    className="lab-name"
                    href={`/lab/conditionals/${entry.attempt_id}`}
                  >
                    {entry.parent_attempt_id
                      ? "Revised attempt"
                      : "Original attempt"}
                  </Link>
                  <small>
                    {time(entry.started_at)} · {entry.attempt_id.slice(0, 12)}
                  </small>
                  <small>
                    <ConditionalState state={entry.execution_state} />
                    {entry.attempt_id === data.id
                      ? " · Viewing this attempt"
                      : ""}
                  </small>
                  {entry.parent_attempt_id && (
                    <small>
                      Revision of{" "}
                      <Link
                        href={`/lab/conditionals/${entry.parent_attempt_id}`}
                      >
                        {entry.parent_attempt_id.slice(0, 12)}
                      </Link>
                    </small>
                  )}
                </td>
                <td className="lab-conditional-model-cell">
                  {entry.requested_model}
                  <small>
                    Provider-reported:{" "}
                    {entry.provider_metadata?.reported_model ?? "Not reported"}
                  </small>
                </td>
                {data.contract.arms.map((arm, i) => (
                  <td key={arm.id} className="lab-number">
                    {entry.arm_quantiles[i] ? (
                      <>
                        <strong>{number(entry.arm_quantiles[i].q50)}</strong>
                        <small>
                          {number(entry.arm_quantiles[i].q10)}–
                          {number(entry.arm_quantiles[i].q90)}
                        </small>
                      </>
                    ) : (
                      "Not available"
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.revision_history
        .filter((entry) => entry.feedback)
        .map((entry) => (
          <div key={entry.attempt_id} className="lab-revision-feedback">
            <ArtifactText
              artifact={entry.feedback!}
              label={`Revision feedback · ${entry.attempt_id.slice(0, 12)}`}
            />
            {entry.triggering_review_id && entry.parent_attempt_id && (
              <a
                className="lab-record"
                href={`/lab/conditionals/${entry.parent_attempt_id}#conditional-review-${entry.triggering_review_id}`}
              >
                Review that prompted this revision →
              </a>
            )}
            {entry.association_artifact && (
              <>
                {" "}
                <a
                  className="lab-record"
                  href={labProxyPath(entry.association_artifact.download_path)}
                  download
                >
                  Revision record ↓
                </a>
              </>
            )}
            {entry.linked_at && (
              <p className="lab-caption">
                Revision relationship recorded retrospectively on{" "}
                {time(entry.linked_at)}. This timestamp records the association,
                not when the review was performed.
              </p>
            )}
          </div>
        ))}
    </Section>
  );
}

function PairedDistributions({ data }: { data: ConditionalDetail }) {
  const response = data.response!;
  const reference = data.reference_quantiles!;
  const difference = data.arm_quantiles[0].q50 - data.arm_quantiles[1].q50;
  const rows: {
    id: string;
    label: string;
    quantiles: Quantiles;
    delta: number | null;
  }[] = [
    {
      id: "reference:shared",
      label: "Shared reference",
      quantiles: reference,
      delta: null,
    },
    ...data.contract.arms.map((arm, i) => ({
      id: `arm:${arm.id}`,
      label: arm.label,
      quantiles: data.arm_quantiles[i],
      delta: response.arms[i].baseline_delta,
    })),
  ];
  return (
    <Section
      title="Paired distributions"
      description={`${data.measurement_period} · ${unit(data.unit)} · one reference and two conditional forecasts from the same response.`}
    >
      <DistributionChart
        curves={[
          {
            id: "reference:shared",
            label: "Shared reference",
            distribution: response.reference,
            reference: true,
          },
          ...response.arms.map((arm, i) => ({
            id: `arm:${arm.id}`,
            label: data.contract.arms[i].label,
            distribution: arm.distribution,
          })),
        ]}
        unitName={data.unit}
        seriesLabel="distributions"
      />
      <div className="lab-table-scroll">
        <table className="lab-table lab-conditional-quantiles">
          <thead>
            <tr>
              <th>Distribution</th>
              <th>Median</th>
              <th>80% interval</th>
              <th>Median shift from reference</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td>{row.label}</td>
                <td className="lab-number">{number(row.quantiles.q50)}</td>
                <td className="lab-number">
                  {number(row.quantiles.q10)}–{number(row.quantiles.q90)}
                </td>
                <td className="lab-number">
                  {row.delta === null
                    ? "—"
                    : `${row.delta > 0 ? "+" : ""}${number(row.delta)}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="lab-caption">
        Medians and 80% intervals are read from each original 201-point CDF.
        Intervals describe the outcome within each condition.
      </p>
      <div className="lab-conditional-difference">
        <span>Difference between conditional medians</span>
        <strong>
          {difference > 0 ? "+" : ""}
          {number(difference)} {unit(data.unit)}
        </strong>
        <p>
          {data.contract.arms[0].label} minus {data.contract.arms[1].label}.
          These marginal forecasts do not establish a causal effect or an
          uncertainty interval for the difference.
        </p>
      </div>
      <details className="lab-disclosure">
        <summary>Shared reference</summary>
        <p className="lab-conditional-prose">
          {data.contract.reference_description}
        </p>
        <p className="lab-conditional-prose">{response.reference_reasoning}</p>
      </details>
    </Section>
  );
}

function ConditionalEvidence({ data }: { data: ConditionalDetail }) {
  const { contract } = data;
  const sourceLabel = (id: string) =>
    contract.sources.find((source) => source.id === id)?.title ?? id;
  return (
    <>
      <Section
        title="Shared history"
        description="The same observations anchor the reference and both conditions."
      >
        {contract.shared_history.length === 0 ? (
          <p className="lab-muted">No history recorded.</p>
        ) : (
          <div className="lab-table-scroll">
            <table className="lab-table lab-conditional-history">
              <thead>
                <tr>
                  <th>Period</th>
                  <th>{unit(data.unit)}</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {contract.shared_history.map((point, i) => (
                  <tr key={`${point.period}-${i}`}>
                    <td>{point.period}</td>
                    <td className="lab-number">{number(point.value)}</td>
                    <td>
                      <a href={`#conditional-source-${point.source_id}`}>
                        {sourceLabel(point.source_id)}
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
      <Section title="Shared evidence">
        <ul className="lab-conditional-claims">
          {contract.shared_evidence.map((item, i) => (
            <li key={i}>
              <p>{item.claim}</p>
              <div className="lab-links">
                {item.source_ids.map((id) => (
                  <a
                    className="lab-record"
                    key={id}
                    href={`#conditional-source-${id}`}
                  >
                    {sourceLabel(id)}
                  </a>
                ))}
              </div>
            </li>
          ))}
        </ul>
        <ul className="lab-conditional-sources">
          {contract.sources.map((source) => (
            <li id={`conditional-source-${source.id}`} key={source.id}>
              <a href={source.url} target="_blank" rel="noopener noreferrer">
                {source.title} ↗
              </a>
              <span>Retrieved {time(source.retrieved_at)}</span>
              <a
                className="lab-record"
                href={labProxyPath(`/artifacts/${source.artifact.sha256}`)}
                download
              >
                Archived source ↓
              </a>
            </li>
          ))}
        </ul>
      </Section>
    </>
  );
}
