# Thesis core PR review response

Fable reviewed PR #228 at `025da734a7a3fa0a475c69aee22f2993ca1c76b3`
through four Subfleet runs using `claude-fable-5-1`. The execution/security
review requested changes. Scientific, custody and application reviews approved
within their scopes with findings. Independent local reproductions confirmed
the changes below and rejected two proposed scientific defects.

## Implemented corrections

- Credential-shaped command arguments are handled before registration and
  archival, including lowercase `--api-key=value` and separate flag/value
  arguments. The archived forecaster and command must not contain those values.
- Text redaction matches complete assignment candidates once instead of
  backtracking over every suffix of a long uppercase stream. JSON redaction
  bounds nesting and refuses documents it cannot safely preserve. The executor
  records an observed malformed-output failure and a content-omission marker;
  it does not archive an unsafe fallback or turn that observed failure into an
  unknown provider outcome.
- Native observation registration replays the linked official source bytes
  before committing. A malformed peer observation still prevents an inferred
  later outcome boundary, but the prospective assessment reports
  `outcome_availability_unknown` through experiment validation.
- Receipt replay selects the proof's recorded trust bundle from the verifier's
  code-pinned registry. New requests use the default bundle. Changing the
  default therefore does not invalidate an older proof whose original bundle
  remains authorized; unknown bundles and mismatched bytes still refuse.
- Public reward and leaderboard exclusions contain typed reasons. Internal
  exception diagnostics do not enter those rows. Queries naming the wrong
  record kind return `experiment_not_found`; request and backend errors share
  the `error.code` envelope.
- The canonical compatibility shim preserves an already importable installed
  package, matching the verifier shims. The package's flat trust directory uses
  a flat package-data glob.

Regression coverage includes synthetic credentials, bounded long output,
excessive JSON nesting and integer limits, native registration against real
PostgreSQL, prospective exclusion reasons, historical trust-bundle replay,
and the actual prospective cohort dispatch gate using locally signed receipts.
Synthetic trust roots are confined to test fixtures. The original approved
implementation-plan bytes remain unchanged.

## Follow-up execution review

Fable approved the scientific and timestamp fixes at
`7d90098e1846cdc4f4778a04cdb2bd32519d947b`. Its execution review identified an
overly broad malformed-JSON rule that rejected ordinary stderr diagnostics and
prompt excerpts. The follow-up preserves those mixed logs while inspecting
credential fragments whose value boundaries cannot be established safely.

Additional local checks exposed whitespace-bearing credential arguments,
repeated JSON keys, and serialized JSON inside event strings. Argument values
are now treated atomically; repeated JSON members all require inspection before
raw-byte preservation; embedded JSON shares the structural depth limit. Mixed-log checks retain scalar
key lines, recognize escaped names, and avoid treating prose quotes as enclosing
later credential fields. Complete JSONL events are scrubbed separately from
unparsed fragments. Regression tests cover successful recorded-log shapes and
known failures without archiving the planted credential values.

A later Fable pass found ordinary Drupal settings and source excerpts still
triggered refusal. The broader recorded-stream audit also exposed legitimate
duplicate transport identifiers. The correction distinguishes safely bounded
values from incomplete credential fragments, preserves every duplicate member
for inspection and redaction, and keeps complete JSON events separate from text
filtering. Public settings names retain recursive checks on their children;
explicitly declared credential names still override these narrow exceptions.
Escaped names and quoted values remain structurally protected. The repeated
unescaped-name path avoids a compiler call for each token. Credential containers
must parse as JSON or a bounded Python literal before removal. Scalar values
require a definite boundary or short plain diagnostic prose; formatting,
conditional and other ambiguous expression continuations refuse. A quoted
conditional branch result is not classified as a field merely because a colon
follows it.

Worker, capture and publication diagnostics now use a bounded helper that
withholds an unsafe message while preserving the original failure state. The
legacy runner handles refusal per channel, retains safe output and observed
process status, and records which channel was omitted. A refused Codex
last-message file is cleaned before the result returns. These changes do not
authorize another model attempt.

## Rejected or qualified findings

The database's migration 006 already prevents a second resolution for one
target. Reproduction preserved one resolution and a working resolver. The
evidence builder already accepts an explicitly selected observation iterable;
passing one capture after repeated captures succeeds. Neither finding calls
for changing those scientific contracts.

The read API reconstructs the graph per request. Its throughput at production
scale has not been established; caching must not silently replace raw evidence
and receipt verification with trusted score rows. Load testing and deployment
budgets remain release work. The existing conservative handling of uncertain
database acknowledgements and heartbeat failures remains intact. Failed
publication jobs can be explicitly retried; unknown model outcomes require
reconciliation under the registered attempt policy.

Fable's runtime estimates for the old redaction regex were not measured.
Local bounded measurements established quadratic scaling. Trust-bundle
rollover was a latent replay defect, not evidence that current proofs were
invalid. The earlier setuptools floor also had a preexisting license-format
incompatibility, so the claimed silent broken-wheel path was conditional.

See the [verification report](thesis-core-verification.md) for executed checks
and the [runbook](thesis-core-runbook.md) for the local operational contract.
