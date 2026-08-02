// Executes the REAL site TypeScript scoring module against a batch of cases.
//
// This file deliberately contains no scoring logic. It imports
// `site/src/data/prediction-distribution.ts` directly (Node >= 22.6 strips the
// type annotations natively) so the numbers it emits originate from the file
// under test, not from a retyped copy. It also reports the resolved path and
// the SHA-256 of the source it loaded, which `pin_against_typescript.py`
// verifies against its own hash of the same path — so a stale or substituted
// module cannot masquerade as the original.
//
// Usage: node ts_driver.mjs <cases.json> [--points]
//   cases.json: {"cases": [{"id": 0, "point": ..., "ci_low": ..., "ci_high": ...,
//                           "observed": ...}, ...]}
//   stdout: one JSON object (see SHAPE below).

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const TS_SOURCE = path.resolve(
  HERE,
  "..",
  "..",
  "site",
  "src",
  "data",
  "prediction-distribution.ts",
);

function die(message) {
  process.stderr.write(`ts_driver: ${message}\n`);
  process.exit(2);
}

// JSON.stringify maps NaN/Infinity to null, which would let a non-finite
// result masquerade as a missing one. Tag them explicitly instead.
function encodeNumber(value) {
  if (typeof value !== "number") return { __nonnumber__: String(value) };
  if (Number.isNaN(value)) return { __nonfinite__: "NaN" };
  if (value === Infinity) return { __nonfinite__: "Infinity" };
  if (value === -Infinity) return { __nonfinite__: "-Infinity" };
  return value;
}

const args = process.argv.slice(2);
const casePath = args.find((a) => !a.startsWith("--"));
const emitPoints = args.includes("--points");
if (!casePath) die("expected a cases JSON path as the first argument");

let sourceBytes;
try {
  sourceBytes = readFileSync(TS_SOURCE);
} catch (error) {
  die(`cannot read TypeScript source at ${TS_SOURCE}: ${error.message}`);
}
const sourceSha256 = createHash("sha256").update(sourceBytes).digest("hex");

let mod;
try {
  mod = await import(pathToFileURL(TS_SOURCE).href);
} catch (error) {
  die(
    `failed to import ${TS_SOURCE} (node ${process.version} native type ` +
      `stripping): ${error.message}`,
  );
}

const { buildNumericCdfFromInterval, scoreNumericCdfDistribution } = mod;
for (const [name, fn] of [
  ["buildNumericCdfFromInterval", buildNumericCdfFromInterval],
  ["scoreNumericCdfDistribution", scoreNumericCdfDistribution],
]) {
  if (typeof fn !== "function") {
    die(`${TS_SOURCE} does not export a callable ${name}`);
  }
}

const payload = JSON.parse(readFileSync(casePath, "utf8"));
if (!Array.isArray(payload.cases)) die("cases JSON must contain a 'cases' array");

const results = payload.cases.map((testCase) => {
  const out = { id: testCase.id };
  let distribution;
  try {
    distribution = buildNumericCdfFromInterval({
      pointEstimate: testCase.point,
      ciLow: testCase.ci_low,
      ciHigh: testCase.ci_high,
    });
  } catch (error) {
    out.build_status = "error";
    out.build_error = `${error.constructor.name}: ${error.message}`;
    out.score_status = "skipped";
    return out;
  }
  out.build_status = "ok";
  out.support = {
    lower: encodeNumber(distribution.support.lower),
    upper: encodeNumber(distribution.support.upper),
  };
  out.point_count = distribution.points.length;
  if (emitPoints) {
    out.points = distribution.points.map((p) => [
      encodeNumber(p.value),
      encodeNumber(p.probability),
    ]);
  }

  try {
    const score = scoreNumericCdfDistribution(distribution, testCase.observed);
    out.score_status = "ok";
    out.crps = encodeNumber(score.crps);
    out.pit = encodeNumber(score.probabilityIntegralTransform);
  } catch (error) {
    out.score_status = "error";
    out.score_error = `${error.constructor.name}: ${error.message}`;
  }
  return out;
});

// SHAPE: everything the Python side needs to prove which code ran.
process.stdout.write(
  JSON.stringify({
    node_version: process.version,
    ts_source_path: TS_SOURCE,
    ts_source_sha256: sourceSha256,
    exports_seen: Object.keys(mod).sort(),
    case_count: results.length,
    results,
  }),
);
