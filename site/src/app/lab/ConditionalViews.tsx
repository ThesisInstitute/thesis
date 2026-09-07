"use client";

import Link from "next/link";
import type {
  ConditionalDetail,
  ConditionalSummary,
  Quantiles,
} from "@/data/generated/thesis-lab";
import { labProxyPath } from "@/lib/lab-paths";
import { DistributionChart } from "./CdfChart";
import { useLab, useLabPages } from "./lab-client";
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
  const page = useLabPages("/lab/conditionals?limit=20", "ConditionalPage");
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
            {page.items.length === 0 ? (
              <div className="lab-notice">
                <strong>No conditional attempts yet</strong>
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
              Every recorded attempt remains visible, including failed and
              unknown outcomes. Updated {time(data.generated_at)}.
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
            <Refresh onClick={refresh} />
          </Heading>
          <div className="lab-conditional-status">
            <p className="lab-conditional-disclosure">
              Exploratory · local operator · scoring not registered
            </p>
            <span>
              Attempt <ConditionalState state={data.execution_state} />
            </span>
          </div>
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
              <Fact label="Started">{time(data.started_at)}</Fact>
              <Fact label="Finished">{time(data.finished_at)}</Fact>
              <Fact label="Execution deadline">{time(data.expires_at)}</Fact>
              <Fact label="Result">
                <ConditionalState state={data.execution_state} />
                {data.error_code && <small>{words(data.error_code)}</small>}
              </Fact>
            </Facts>
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
