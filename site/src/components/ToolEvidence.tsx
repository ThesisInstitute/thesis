import type {
  CapturedToolCall,
  ForecastToolEvidence,
} from "@/data/tool-evidence";

const artifactHref = (path: string) =>
  `https://github.com/ThesisInstitute/thesis/blob/main/${path}`;
const json = (value: unknown) => JSON.stringify(value, null, 2);
const stageNames = { forecast: "Forecast", draft: "Draft", review: "Review" };

export function ToolEvidence({
  evidence = { status: "missing" },
}: {
  evidence?: ForecastToolEvidence;
}) {
  return (
    <section
      aria-labelledby="tool-evidence-heading"
      className="border-t border-[var(--theme-border)] pt-7"
    >
      <h2
        id="tool-evidence-heading"
        className="mb-4 [font-family:var(--font-display)] text-2xl font-semibold"
      >
        Tool evidence
      </h2>
      {evidence.status === "missing" ? (
        <p className="text-sm leading-relaxed text-[var(--theme-text-muted)]">
          This run has no captured tool responses. “Reported tool use” in the
          analysis is the model’s account, not an archived tool response.
        </p>
      ) : evidence.status === "invalid" ? (
        <p className="text-sm leading-relaxed text-[var(--theme-text-muted)]">
          Tool evidence could not be verified against this run’s archive and is
          not displayed.
        </p>
      ) : (
        <>
          <p className="mb-5 max-w-[75ch] text-sm leading-relaxed text-[var(--theme-text-muted)]">
            Captured by Axiom Forecasts’ tools. Artifact hashes match the run archive;
            replay results below were recorded by the runner. These checks do
            not authenticate the source publisher or validate the forecast’s
            judgment. Calls made through other tools are not covered.
          </p>
          {evidence.artifacts.map((artifact) => (
            <div key={artifact.artifactPath} className="mb-7 last:mb-0">
              <div className="mb-3 flex flex-wrap items-baseline gap-x-4 gap-y-2 text-sm">
                <h3 className="font-semibold">
                  {stageNames[artifact.stage]} calls
                </h3>
                <span className="text-[var(--theme-text-muted)]">
                  Archive integrity checked
                </span>
                <a
                  className="text-[var(--color-accent)] hover:underline"
                  href={artifactHref(artifact.artifactPath)}
                >
                  Raw evidence ↗
                </a>
                <a
                  className="text-[var(--color-accent)] hover:underline"
                  href={artifactHref(artifact.verificationPath)}
                >
                  Replay report ↗
                </a>
              </div>
              {!artifact.calls.length && (
                <p className="text-sm text-[var(--theme-text-muted)]">
                  No tool calls were captured in this stage.
                </p>
              )}
              <div className="divide-y divide-[var(--theme-border)] border-y border-[var(--theme-border)]">
                {artifact.calls.map((call) => (
                  <CapturedCall key={call.callId} call={call} />
                ))}
              </div>
            </div>
          ))}
        </>
      )}
    </section>
  );
}

function CapturedCall({ call }: { call: CapturedToolCall }) {
  return (
    <details className="py-4">
      <summary className="cursor-pointer text-sm leading-relaxed">
        <code className="mr-3 text-[var(--theme-text-muted)]">
          {call.callId}
        </code>
        <span className="font-medium">{call.tool}</span>
        <span className="ml-3 text-[var(--theme-text-muted)]">
          {call.status === "failed"
            ? "Failed · retained for audit"
            : call.replay === "replayed"
              ? "Succeeded · runner replay passed"
              : "Succeeded · response captured"}
        </span>
      </summary>
      <div className="mt-4 space-y-4">
        <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[100px_minmax(0,1fr)]">
          <dt className="text-[var(--theme-text-muted)]">Started</dt>
          <dd className="break-all">
            <time dateTime={call.startedAt}>{call.startedAt}</time>
          </dd>
          <dt className="text-[var(--theme-text-muted)]">Completed</dt>
          <dd className="break-all">
            <time dateTime={call.completedAt}>{call.completedAt}</time>
          </dd>
          {call.response && (
            <>
              <dt className="text-[var(--theme-text-muted)]">Source</dt>
              <dd className="break-all">
                <a
                  href={call.response.url}
                  className="text-[var(--color-accent)] hover:underline"
                >
                  {call.response.url}
                </a>
              </dd>
              <dt className="text-[var(--theme-text-muted)]">Response</dt>
              <dd>
                HTTP {call.response.status} ·{" "}
                {call.response.bytes.toLocaleString("en-US")} bytes · body hash
                checked
              </dd>
              <dt className="text-[var(--theme-text-muted)]">SHA-256</dt>
              <dd className="break-all">
                <code>{call.response.sha256}</code>
              </dd>
            </>
          )}
        </dl>
        <CodeBlock label="Input" value={json(call.arguments)} />
        <CodeBlock label="Output" value={json(call.result)} />
        {call.error && <CodeBlock label="Error" value={call.error} />}
        {call.response && (
          <>
            <details>
              <summary className="cursor-pointer text-sm text-[var(--theme-text-muted)]">
                Response headers
              </summary>
              <CodeBlock value={json(call.response.headers)} />
            </details>
            {call.response.bodyText !== undefined ? (
              <details>
                <summary className="cursor-pointer text-sm text-[var(--theme-text-muted)]">
                  {call.response.bodyTextTruncated
                    ? "Response text preview"
                    : "Full response text"}
                </summary>
                {call.response.bodyTextTruncated && (
                  <p className="mt-2 text-sm text-[var(--theme-text-muted)]">
                    Preview limited to the first 64 KiB. Full response bytes are
                    available as base64 in Raw evidence.
                  </p>
                )}
                <CodeBlock value={call.response.bodyText} />
              </details>
            ) : (
              <p className="text-sm text-[var(--theme-text-muted)]">
                Response bytes are available as base64 in Raw evidence.
              </p>
            )}
          </>
        )}
        {!!call.replayChecks.length && (
          <details>
            <summary className="cursor-pointer text-sm text-[var(--theme-text-muted)]">
              Runner verification checks
            </summary>
            <ul className="mt-2 list-disc pl-5 text-sm text-[var(--theme-text-muted)]">
              {call.replayChecks.map((check, index) => (
                <li key={index}>{check}</li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </details>
  );
}

function CodeBlock({
  label,
  value,
}: {
  label?: string;
  value: string | undefined;
}) {
  return (
    <div>
      {label && <h4 className="mb-2 text-sm font-medium">{label}</h4>}
      <pre className="mt-2 max-h-[32rem] overflow-auto rounded-md border border-[var(--theme-border)] bg-[var(--theme-bg-surface)] p-4 text-xs leading-relaxed">
        <code>{value}</code>
      </pre>
    </div>
  );
}
