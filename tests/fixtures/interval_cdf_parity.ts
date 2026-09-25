// Differential oracle for tests/test_distribution_rounding_parity.py.
//
// Materializes interval_anchor_v1 CDFs with BOTH TypeScript builders — the
// site reference (site/src/data/prediction-distribution.ts, which defines the
// immutable transform) and the forecast-api copy — so the Python port
// (scripts/run_thesis_analyst.py interval_distribution) can be held to them
// byte for byte. Both modules load from their own files, unmodified.
//
// stdin: a JSON array of {pointEstimate, ciLow, ciHigh}.
// stdout: two lines per input, site first then forecast-api, each the
// canonicalStringify (site/src/data/canonical-json.ts) of {points, support}.
// Canonical JSON never contains a raw newline, so lines split cleanly.
import { plugin } from "bun";

import { canonicalStringify } from "../../site/src/data/canonical-json.ts";
import { buildNumericCdfFromInterval as buildSite } from "../../site/src/data/prediction-distribution.ts";

// The forecast-api module imports zod only to build its validation schemas at
// load time; buildNumericCdfFromInterval never touches z. CI's python-tests
// job installs bun but not forecast-api's node_modules, so an inert chainable
// stub stands in for zod. It must be registered before the dynamic import.
const inert: unknown = new Proxy(function () {}, {
  get: (_target, key) => (key === "then" ? undefined : inert),
  apply: () => inert,
});
plugin({
  name: "inert-zod",
  setup(build) {
    build.module("zod", () => ({ exports: { z: inert }, loader: "object" }));
  },
});
const { buildNumericCdfFromInterval: buildForecastApi } = await import(
  "../../forecast-api/src/lib/prediction-distribution.ts"
);

type IntervalInput = { pointEstimate: number; ciLow: number; ciHigh: number };

const inputs: IntervalInput[] = JSON.parse(await Bun.stdin.text());
const lines: string[] = [];
for (const input of inputs) {
  for (const build of [buildSite, buildForecastApi]) {
    const { points, support } = build(input);
    lines.push(canonicalStringify({ points, support }));
  }
}
await Bun.write(Bun.stdout, lines.join("\n") + "\n");
