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

Forecast detail pages replay saved results instead of starting an API request
on each visit. At build time, `site/src/lib/saved-forecast.ts` reads the newest
valid indexed recorder result for each API target from `records/`, verifying
the compressed and uncompressed bytes against the snapshot's hashes. The
initial HTML contains that result's estimate and interval; playback uses its
own saved explanation, assumptions, and caveats. A failed or malformed newer
snapshot falls back to the last valid one. With no usable archive, the page
shows the labeled catalog example without calling the API.

The current archives contain the final forecast event, not the original full
stream of tool activity. The page discloses this and links to the archived
result. The recorder workflow continues to call the endpoints below. Its
snapshot commits trigger the normal site deployment to publish newly saved
results. Build from the full repository with
`records/` available alongside `site/` (including files outside Vercel's root
directory), as with the existing build-time bill artifacts.

AI Gateway is optional locally. Without `AI_GATEWAY_API_KEY`,
`VERCEL_OIDC_TOKEN`, or a Vercel runtime, live endpoints still stream public
data/tool traces plus deterministic or calibration fallback forecasts.

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
