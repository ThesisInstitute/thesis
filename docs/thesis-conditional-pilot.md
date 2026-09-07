# Conditional forecasts in the lab

This increment produces one real, recorded pair of education forecasts using
one frozen evidence packet and a common baseline. It adds a generic conditional
comparison workspace to the existing Thesis lab. It does not register the
unrealized policy alternative as an observed outcome.

The first question is the 2030 national, all-students NAEP grade 8 mathematics
mean under two explicit federal teacher-pay enactment conditions. Official
NCES source bytes determine the population, historical values and release
window. Official bill text and status determine the named proposals. A chosen
condition cutoff is a scenario assumption; it is not presented as a verified
constitutional deadline. Enactment, funding, implementation and take-up are
different assumptions and must remain visible.

## Shared inputs and recorded execution

The comparison freezes one outcome definition, two named conditions, one
official history and an evidence inventory with source URLs, capture times and
content hashes. The model receives public-source material only. Private meeting
notes and the older exploratory forecasts are not evidence for this run.

One subprocess receives the entire pair. Its response must use the shared
baseline and outcome/evidence identities. Both arms must validate together;
missing, duplicated, reordered or inconsistent arms fail the attempt. Original
201-point CDFs come from the model. Displayed medians and intervals are computed
from those points, with declared changes checked against the common baseline.
The application never constructs a policy-effect interval by subtracting two
marginal intervals.

Dispatch is recorded before invoking the model. The attempt has a finite
deadline and no automatic retry. The runner preserves the exact prompt,
invocation, code, sanitized output, response and validation artifacts. A failed
or interrupted attempt stays visible. All members of a successful pair are
sealed together. Requested model identity and observed provider metadata are
separate; unavailable metadata stays unknown.

## Storage and scientific boundary

Add append-only operational records and content-addressed artifacts alongside
the existing scientific graph. Database constraints prevent edits or competing
terminal results. Reopening an artifact verifies its hash. The attempt contract
binds the same frozen inputs and timeout used by execution.

These records have explicit exploratory, local-operator provenance and
`scoring_status=not_registered`. They are outside the existing Experiment,
ForecastRun, Resolution and reward-export paths. The current experiment model
compares forecasters on one realized outcome; it does not yet encode legal
conditions or condition-gated scoring. Labeling a conditional pair as an
ordinary experiment would incorrectly score both arms against the same outcome.

This increment changes no Chronicle schema or publisher records. Chronicle
continues to describe observations and source publications. Thesis owns its
forecasts. The old independent education runs and their traces remain preserved
at their existing local locations.

## Application

Read-only `/lab/conditionals` list and detail routes show the real run, both
distributions, their median difference, shared history, exact assumptions,
source links and execution artifacts. Failed and unknown attempts remain
enumerable. The existing lab typography, round chart ticks, CDF/PDF controls and
accessible inspection behavior carry over. Chart reuse accepts display curves;
it must not invent task, agent or experiment identities to satisfy a UI type.

The comparison is a modeled scenario contrast. Shared arithmetic improves
consistency but does not identify a causal effect or establish calibration.
Eventual scoring requires separately admitted condition and outcome resolvers;
only an eligible realized arm can receive an observed score. Missing official
release dates and resolver capabilities are displayed explicitly.

## Acceptance

Use real PostgreSQL tests for immutable dispatch/result storage, races, expired
attempts, failed execution and artifact corruption. Test strict pair identity,
history and arithmetic validation, CDF-derived summaries and separation from
ordinary forecasts and rewards. Test generated API contracts and closed proxy
routes, the conditional views, existing chart behavior and a production build.

Run the actual recorded model only after public inputs have been checked and
the implementation has passed focused tests. Inspect the resulting local
application in the browser. Request independent Fable review through Subfleet
of the concrete change and address actionable findings. Deliver the branch,
review status and the working local comparison; production cutover and merging
remain separate release actions. No email is sent by this work.

## Run and inspect

Use the existing core environment and artifact store. Archive the verified
public source files with `thesis-core artifact FILE`, then place their returned
hashes, sizes, media types and recorded source capture times in a
`ConditionalContract` JSON document. The exact schema is generated in
`thesis_core/schemas/lab.json`; domain validation additionally checks distinct
arm/source identities and complete source references.

```sh
thesis-core init
thesis-core forecast-conditionals contract.json --model MODEL_ID --timeout-seconds 600
thesis-core serve --host 127.0.0.1 --port 8112
```

`MODEL_ID` is the explicit requested Codex model. The CLI uses existing Codex
authentication and an isolated temporary working directory. It supplies only
the frozen evidence and forbids tools in the prompt, while retaining the honest
local-operator access classification. This is not verified tool isolation.

Set the site's server-only `THESIS_CORE_API_URL` to that API and open
`/lab/conditionals`. Results, failed attempts and execution artifacts are
available immediately through the read API. A second CLI invocation is a new
visible attempt; nothing retries automatically. After an interrupted process,
`thesis-core recover-conditionals` records expired attempts as unknown. A late
observed completion also records unknown with its captured artifacts and cannot
become a successful forecast.

Verification for the implementation: 651 core tests against isolated real
PostgreSQL 14.22, 1,221 site tests, generated-schema drift, scoped lint and the
production build. These tests establish implementation behavior, not forecast
accuracy or empirical calibration.
