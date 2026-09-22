# Bill analysis and conditional forecasts

The bill lane connects provision-anchored outcomes to Chronicle identities and
reviewed conditional registrations. Extraction is an agent proposal. Admission
and legal contracts are reviewed repository inputs. Forecasts run only against
those immutable registrations, with both legal-state arms selected together.

## Analyze a bill

Run `ingest-bill.yml` on main with `bill_ref=119/s/3596` and
`bill_slug=s3596-119`. For an official committee draft, supply `source_url`
instead of `bill_ref`. To reanalyze the preserved source version, set
`use_committed_source=true` and leave both remote-source inputs empty.

The workflow fetches a Chronicle catalog at an immutable commit and runs the
bill analyst with shell and search disabled. It supplies the complete source
text and catalog identities. The extractor checks the closed JSON schema,
source identity, exact contiguous provision quotes, and metric/goal links.
`scripts/map_bill_metrics.py` then matches hints to exact concepts, aliases and
unambiguous descendants. Ambiguities remain work items. A national row cannot
disambiguate unrelated concepts.

Every attempt, including failure, retains its source, catalog, prompt, command,
native stdout, stderr, response, validation, mapping decisions and hashes in
the workflow's `bill-analysis-<run>-<attempt>` artifact. Draft files are under
`drafts/bill-ingestion/github-<run>-<attempt>/`; the job has no write permission.
The extraction is not a forecast and does not change the public bill page.

## Review and admit

Review the draft's quotes, scope, mechanisms, outcome identities and policy
premises. Promote the validated `bill.json` to `bills/<slug>.json` only through
a reviewed PR, retaining the source/provenance and attempt link. Do not copy
the `.mapped.json` into the bill index; it is a proposal annotated with the
mapping snapshot. Bill pages recompute admission against the current docket.

When XML extraction flattens section headings, promotion can retain a reviewed
`bills/raw/<slug>.sections.json` with `sourceTextSha256` and a `sections` map
from section numbers to complete, exact source substrings. The site uses it
only if the existing text parser finds no section, the source-byte hash matches,
and every supplied span remains verbatim. Review establishes section boundaries;
these checks prevent stale source versions or edited excerpts from displaying.
Archive the original extraction unchanged and record every promotion edit in
`bills/provenance/<slug>/`, including retained historical compute evidence.

Every outcome without an admitted series produces an explicit open request:
identify the precise official series; ingest witnessed first prints into
Chronicle; implement or reuse a resolvable adapter; independently verify
anchors; and review docket admission. Missing series are work to complete,
never silently replaced by an adjacent context series. Candidate conditions
must become reviewed, provision-anchored contracts before preregistration.

`scripts/bill_forecast_bindings.json` joins a reviewed analysis and source hash
to a canonical Chronicle identity, outcome metric and exact registered arms.
Changing the bill analysis or source requires review of this binding too.
The binding and site's bill forecast links share one registry. Existing legacy
bill examples without a binding remain visible but cannot use this new lane.

## Forecast a reviewed pair

For a fresh ACTC comparison, dispatch the existing `strategy-docket.yml` with:

```text
bill_slug=s3596-119
bill_series=irs.actc.total_claims
catalog_slugs=
auto_select=false
max_targets=2
suite=ladder
ladder_prompt_mode=ladder
```

Omit model overrides to retain the workflow default. An empty `bill_series`
selects all reviewed pairs for the bill and requires enough capacity for every
arm. The bill mode supports the reviewed ladder lane; median sampling is not
admitted for bill comparisons yet.

Selection reauthenticates both published registrations, exact legal premises,
Chronicle identity, anchors, and release windows. Both conditions must still be
recorded open, and generation must precede the condition deadline and earliest
possible release day. The same checks run before generation, publication, and
every rebase. Fresh official legal-state evidence must be reviewed before a
dispatch; the condition registry is a recorded state, not a live bill tracker.
Enactment tests are provision-based, so checking only whether a named vehicle
became law is insufficient.

The standard analyst runner captures source bytes and replayable calculations,
binds native MCP calls to its transcript, and seals the complete artifact
inventory. The trusted publisher checks cells against each arm's exact premise
and type. If either arm fails, both attempted traces are retained but neither
arm appears as a new paired comparison. Existing forecasts stay intact.

Successful comparisons deploy through the existing publisher and automatically
dispatch the signed recorder. Completion requires both successful captured
fetches and replays, native event custody, visible report/raw/replay links, and
the recorder snapshot's `artifactCommitments.custodyRoots` linking to both run
manifests. Full-chain verification runs remotely; selected Receipt signatures
use the existing pinned key and `thesis-record-snapshot/v1` plus NUL domain.

A conditional difference is a model forecast under two stated legal premises.
It is not an observed causal estimate, and non-exhaustive policy pairs may both
remain unscored if an intermediate policy is enacted.
