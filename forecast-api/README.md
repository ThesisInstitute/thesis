# Thesis forecast API

Small Vercel-deployable backend for live forecast traces, deployed as the
`thesis-api` Vercel project behind `api.thesisinstitute.org`. Production
deploys go through `~/thesis-institute` ops tooling — never a bare
`vercel --prod` from an unreviewed checkout.

## Local development

```bash
bun install
bun run dev -- --hostname 127.0.0.1 --port 3002
```

Forecast detail pages render complete reports without starting an API request
on each visit. At build time, `site/src/lib/forecast-publication.ts` verifies
catalog runs against archived model execution and output artifacts. Only runs
that pass this gate can supply public estimates, distributions, and reasoning.
An eligible comparison can replace a withdrawn prototype headline. Targets
without an eligible run show “No forecast available.” Report text and code
blocks appear immediately, without playback controls or a typewriter animation.

Recorder snapshots remain audit records. A final API forecast event by itself
does not provide the complete execution receipts required for publication;
failed, fallback, and unverified snapshots cannot supply a public forecast.
The recorder workflow continues to archive endpoint results, including failures,
and historical records are retained unchanged. See
[`docs/forecast-publication-policy.md`](../docs/forecast-publication-policy.md)
for the publication rules and verification limits.

Build from the full repository with `records/` available alongside `site/`
(including files outside Vercel's root directory), as with the existing
build-time bill artifacts.

AI Gateway access is required to produce a forecast. Missing credentials,
`BRIER_DISABLE_AI=1`, denied model access, and invalid model responses terminate
the stream with `failure` and `done` containing `ok: false`. They never emit a
`forecast` event or substitute an estimate or authored explanation. Public data
checks completed before the failure remain visible in the stream.

The current-law CTC outlay endpoint is unavailable until an absolute outlay
calculation is implemented; it fails before invoking tools. The other endpoints
continue to fetch their source inputs and emit forecasts only after a successful,
validated model response. Their stored calibration assumptions are labeled as
priors, not presented as executed calibration tool calls.

Run the API regression checks with `bun run test`, followed by
`bun run typecheck` and `bun run build`.

## Endpoints

- `GET /health`
- `GET /forecasts/spm-child-poverty-2025/stream`
- `GET /forecasts/cpi-u-annual-2026/stream`
- `GET /forecasts/ctc-expansion-cost-ty2026/stream`
- `GET /forecasts/ctc-current-law-outlays-ty2026/stream`

## CORS

Allowed browser origins default to the thesisinstitute.org surfaces plus the
local development origins (`src/lib/cors.ts`). Override with
`THESIS_SITE_ORIGINS` as a comma-separated list.
