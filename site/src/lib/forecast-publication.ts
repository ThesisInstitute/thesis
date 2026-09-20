import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import {
  FORECAST_CELLS,
  getForecastRunEntries,
  type ForecastCell,
  type ForecastComparisonRun,
  type ForecastRunEntry,
  type PredictionRunActivityArtifact,
} from "@/data/forecast-cells";
import type {
  ForecastToolEvidence,
  ForecastToolEvidenceByVariant,
} from "@/data/tool-evidence";
import { readCapturedToolCalls } from "@/lib/tool-evidence";
import { canonicalStringify, sha256Hex } from "@/data/canonical-json";
import {
  buildNumericCdfFromInterval,
  getDistributionTransformVersion,
  type PredictionDistribution,
} from "@/data/prediction-distribution";

// This is an archive/execution gate, not a substitute for source validation,
// workflow attestations, or the independent custody/witness verifier.
const MANIFEST_HASH_MODE =
  "canonical-json-v1; exclude artifacts where artifactType=manifest and exclude custodyRootSha256";
const MAX_ARTIFACT_BYTES = 128 * 1024 * 1024;
type Json = Record<string, any>;
type Artifact = PredictionRunActivityArtifact;
interface VerificationOptions {
  repositoryRoot?: string;
}
export interface ForecastRunVerification {
  eligible: boolean;
  reason: string;
}
interface VerifiedRun extends ForecastRunVerification {
  cell?: Json;
  archive?: { root: string; refs: Artifact[] };
}

const fileCache = new Map<
  string,
  { digest: string; bytes: number; text?: string }
>();
const ARCHIVE_PREFIX = "records/thesis-analyst/";
const DEFAULT_ARCHIVE_DIRECTORY = path.join(
  process.cwd(),
  "..",
  "records",
  "thesis-analyst",
);

function failure(reason: string): VerifiedRun {
  return { eligible: false, reason };
}
function requireCondition(value: unknown, reason: string): asserts value {
  if (!value) throw new Error(reason);
}

function readArtifact(relativePath: string, root: string, includeText = true) {
  requireCondition(
    typeof relativePath === "string" &&
      relativePath.startsWith(ARCHIVE_PREFIX) &&
      !relativePath.includes("\\") &&
      relativePath
        .split("/")
        .every((part) => part && part !== "." && part !== ".."),
    "Artifact path is outside the analyst archive",
  );
  requireCondition(
    !fs.lstatSync(root).isSymbolicLink() &&
      !fs.lstatSync(path.dirname(root)).isSymbolicLink(),
    "Artifact archive root contains a symbolic link",
  );
  let current = root;
  for (const segment of relativePath.slice(ARCHIVE_PREFIX.length).split("/")) {
    current = path.join(current, segment);
    requireCondition(
      !fs.lstatSync(current).isSymbolicLink(),
      "Artifact path contains a symbolic link",
    );
  }
  const stat = fs.statSync(current);
  requireCondition(
    stat.isFile() && stat.size <= MAX_ARTIFACT_BYTES,
    "Artifact is not a bounded regular file",
  );
  const cacheKey = `${current}:${stat.size}:${stat.mtimeMs}:${stat.ctimeMs}:${stat.ino}`;
  const cached = fileCache.get(cacheKey);
  if (cached)
    return {
      ...cached,
      text:
        cached.text ?? (includeText ? fs.readFileSync(current, "utf8") : ""),
    };
  const bytes = fs.readFileSync(current);
  const result = {
    digest: createHash("sha256").update(bytes).digest("hex"),
    bytes: bytes.length,
    text: bytes.toString("utf8"),
  };
  // Do not retain multi-megabyte event streams for every catalog run.
  fileCache.set(cacheKey, {
    ...result,
    text: result.bytes < 256 * 1024 ? result.text : undefined,
  });
  return result;
}

function jsonArtifact(relativePath: string, root: string): Json {
  return JSON.parse(readArtifact(relativePath, root).text);
}

function verifyArtifact(ref: Artifact, root: string) {
  requireCondition(
    /^[a-f0-9]{64}$/.test(ref.sha256) &&
      Number.isSafeInteger(ref.bytes) &&
      ref.bytes >= 0,
    "Invalid artifact commitment",
  );
  const actual = readArtifact(ref.path, root, Boolean(ref.hashMode));
  if (!ref.hashMode) {
    requireCondition(
      actual.bytes === ref.bytes && actual.digest === ref.sha256,
      `Artifact commitment mismatch: ${ref.path}`,
    );
    return;
  }
  requireCondition(
    ref.artifactType === "manifest" && ref.hashMode === MANIFEST_HASH_MODE,
    "Unsupported artifact hash mode",
  );
  const manifest = JSON.parse(actual.text);
  delete manifest.custodyRootSha256;
  manifest.artifacts = manifest.artifacts.filter(
    (artifact: Artifact) => artifact.artifactType !== "manifest",
  );
  const bytes = Buffer.from(canonicalStringify(manifest));
  requireCondition(
    bytes.length === ref.bytes &&
      createHash("sha256").update(bytes).digest("hex") === ref.sha256,
    "Manifest commitment mismatch",
  );
}

function sameCommitment(a: Artifact, b: Artifact) {
  return (
    a.artifactType === b.artifactType &&
    a.path === b.path &&
    a.sha256 === b.sha256 &&
    a.bytes === b.bytes &&
    a.hashMode === b.hashMode
  );
}

function comparableDistribution(distribution: PredictionDistribution) {
  return {
    ...distribution,
    transformVersion: getDistributionTransformVersion(distribution),
  };
}

/** Replay the runner's documented distribution transform from model output. */
function responseDistribution(cell: Json): PredictionDistribution {
  if (cell.predictionDistribution) return cell.predictionDistribution;
  if (!cell.thresholdLadder)
    return buildNumericCdfFromInterval({
      pointEstimate: cell.pointEstimate,
      ciLow: cell.ciLow,
      ciHigh: cell.ciHigh,
    });
  const { thresholds, cumulativeProbabilities } = cell.thresholdLadder;
  requireCondition(
    Array.isArray(thresholds) &&
      Array.isArray(cumulativeProbabilities) &&
      thresholds.length >= 3 &&
      thresholds.length === cumulativeProbabilities.length,
    "Invalid model-reported threshold ladder",
  );
  requireCondition(
    thresholds.every(
      (value: number, index: number) =>
        Number.isFinite(value) &&
        (index === 0 || value > thresholds[index - 1]),
    ) &&
      cumulativeProbabilities.every(
        (value: number, index: number) =>
          Number.isFinite(value) &&
          value >= 0 &&
          value <= 1 &&
          (index === 0 || value >= cumulativeProbabilities[index - 1]),
      ),
    "Invalid model-reported threshold values",
  );
  const lower = Math.min(
    cell.ciLow -
      Math.max(Math.abs(cell.pointEstimate - cell.ciLow), 1e-9) * 1.5,
    thresholds[0],
  );
  const upper = Math.max(
    cell.ciHigh +
      Math.max(Math.abs(cell.ciHigh - cell.pointEstimate), 1e-9) * 1.5,
    thresholds.at(-1),
  );
  const knots = [{ value: lower, probability: 0 }];
  for (let index = 0; index < thresholds.length; index++) {
    if (thresholds[index] > knots.at(-1)!.value)
      knots.push({
        value: thresholds[index],
        probability: cumulativeProbabilities[index],
      });
  }
  if (upper > knots.at(-1)!.value) knots.push({ value: upper, probability: 1 });
  else knots[knots.length - 1].probability = 1;
  const rounded = (value: number) => Number(value.toFixed(10));
  const step = (upper - lower) / 200;
  const points = Array.from({ length: 201 }, (_, index) => {
    const value = lower + step * index;
    const right = knots.findIndex((knot) => knot.value >= value);
    if (right <= 0)
      return { value: rounded(value), probability: right === 0 ? 0 : 1 };
    const start = knots[right - 1];
    const end = knots[right];
    return {
      value: rounded(value),
      probability: rounded(
        start.probability +
          ((value - start.value) / (end.value - start.value)) *
            (end.probability - start.probability),
      ),
    };
  });
  return {
    format: "numeric_cdf_v1",
    pointCount: 201,
    support: { lower: points[0].value, upper: points[200].value },
    points,
    summary: {
      pointEstimate: cell.pointEstimate,
      median: cell.pointEstimate,
      interval80: { lower: cell.ciLow, upper: cell.ciHigh },
    },
    provenance: "agent_reported",
    transformVersion: "agent_cdf_v1",
  };
}

function equalWithinRounding(a: unknown, b: unknown): boolean {
  if (typeof a === "number" && typeof b === "number")
    return (
      Number.isFinite(a) &&
      Number.isFinite(b) &&
      Math.abs(a - b) <=
        Math.max(1e-9, Math.max(Math.abs(a), Math.abs(b)) * Number.EPSILON * 4)
    );
  if (
    a === null ||
    b === null ||
    typeof a !== "object" ||
    typeof b !== "object"
  )
    return a === b;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const left = a as Record<string, unknown>;
  const right = b as Record<string, unknown>;
  const keys = Object.keys(left);
  return (
    keys.length === Object.keys(right).length &&
    keys.every(
      (key) =>
        Object.hasOwn(right, key) && equalWithinRounding(left[key], right[key]),
    )
  );
}

function verifyRun(
  forecast: ForecastCell,
  run: ForecastRunEntry,
  options: VerificationOptions,
): VerifiedRun {
  try {
    const root = options.repositoryRoot
      ? path.join(options.repositoryRoot, "records", "thesis-analyst")
      : DEFAULT_ARCHIVE_DIRECTORY;
    const metadata = run.predictionRun;
    requireCondition(
      metadata?.kind === "recorded-agent-run",
      "No archived agent run",
    );
    requireCondition(
      !run.externalSubmission,
      "External submissions require a separate execution-verification contract",
    );
    const refs = metadata.activityLog;
    requireCondition(refs?.length, "No archived activity artifacts");
    requireCondition(
      !metadata.aggregationAlgorithmVersion,
      "Derived ensembles require constituent verification",
    );
    const normalizedRef = refs.find(
      (ref) => ref.artifactType === "normalized_cell",
    );
    requireCondition(normalizedRef, "No normalized output artifact");
    const directory = path.posix.dirname(normalizedRef.path);
    requireCondition(
      refs.every((ref) => path.posix.dirname(ref.path) === directory),
      "Run artifacts cross archive directories",
    );
    for (const ref of refs) verifyArtifact(ref, root);

    const manifestPath = `${directory}/manifest.json`;
    const manifest = jsonArtifact(manifestPath, root);
    requireCondition(
      manifest.schemaVersion === "thesis_analyst_run_manifest_v1" &&
        manifest.ok === true,
      "Run manifest is unsuccessful or unsupported",
    );
    requireCondition(
      Array.isArray(manifest.artifacts),
      "Manifest has no artifact inventory",
    );
    requireCondition(
      manifest.agent?.agent === metadata.agent,
      "Displayed agent differs from the archived run",
    );
    for (const field of [
      "agentVersion",
      "promptHash",
      "toolPolicyHash",
      "model",
    ] as const) {
      if (metadata[field] !== undefined) {
        requireCondition(
          metadata[field] === manifest.agent?.[field],
          `Displayed ${field} differs from the archived run`,
        );
      }
    }
    for (const field of ["promptMode", "preSubmitReview", "packSet"] as const) {
      if (metadata[field] !== undefined) {
        requireCondition(
          canonicalStringify(metadata[field]) ===
            canonicalStringify(manifest[field] ?? null),
          `Displayed ${field} differs from the archived run`,
        );
      }
    }
    if (metadata.generationTicket) {
      requireCondition(
        metadata.generationTicket.ticketId ===
          manifest.generationTicket?.ticketId &&
          metadata.generationTicket.ticketPath ===
            manifest.generationTicket?.ticketPath,
        "Displayed generation ticket differs from the archived run",
      );
    }
    const manifestRefs: Artifact[] = manifest.artifacts;
    requireCondition(
      manifestRefs.every((ref) => path.posix.dirname(ref.path) === directory),
      "Manifest artifacts cross archive directories",
    );
    requireCondition(
      new Set(manifestRefs.map((ref) => ref.path)).size === manifestRefs.length,
      "Duplicate manifest artifact paths",
    );
    requireCondition(
      refs.every(
        (ref) =>
          (ref.artifactType === "manifest" && ref.path === manifestPath) ||
          manifestRefs.some((other) => sameCommitment(ref, other)),
      ),
      "Catalog artifacts disagree with the manifest",
    );
    for (const ref of manifestRefs) verifyArtifact(ref, root);

    const manifestRef = refs.find(
      (ref) => ref.artifactType === "manifest" && ref.path === manifestPath,
    );
    if (!manifestRef) {
      requireCondition(
        metadata.custodyRootSha256 &&
          manifest.custodyRootSha256 === metadata.custodyRootSha256,
        "Manifest has no catalog-bound commitment",
      );
      const custody = jsonArtifact(`${directory}/custody_root.json`, root);
      requireCondition(
        custody.schemaVersion === "thesis_custody_root_v1" &&
          sha256Hex(custody) === metadata.custodyRootSha256,
        "Custody root commitment mismatch",
      );
      const withoutRoot = { ...manifest };
      delete withoutRoot.custodyRootSha256;
      requireCondition(
        custody.manifestWithoutCustodyRoot?.canonicalJsonSha256 ===
          sha256Hex(withoutRoot),
        "Custody root does not bind the manifest",
      );
    }

    const required = (type: Artifact["artifactType"], filename?: string) => {
      const ref = manifestRefs.find(
        (item) =>
          item.artifactType === type &&
          (!filename || item.path === `${directory}/${filename}`),
      );
      requireCondition(ref, `Missing ${type} execution artifact`);
      return ref;
    };
    required("prompt");
    const commandRef = required("command", "command.json");
    const command = jsonArtifact(commandRef.path, root);
    const argv = command.argv;
    requireCondition(
      Array.isArray(argv) &&
        argv.every((arg: unknown) => typeof arg === "string") &&
        path.basename(argv[0]) === "codex" &&
        argv.includes("exec"),
      "Command is not an archived Codex execution",
    );
    requireCondition(
      command.returnCode === 0 &&
        command.processReturnCode === 0 &&
        command.timedOut === false,
      "Agent command did not complete successfully",
    );
    const modelIndex = argv.findIndex(
      (arg: string) => arg === "-m" || arg === "--model",
    );
    const commandModel =
      modelIndex >= 0
        ? argv[modelIndex + 1]
        : argv.find((arg: string) => arg.startsWith("--model="))?.slice(8);
    requireCondition(
      commandModel && commandModel === metadata.model,
      "Displayed model differs from the executed command",
    );
    const trace = jsonArtifact(
      required("codex_trace", "codex_trace.json").path,
      root,
    );
    requireCondition(
      trace.backend === "codex-exec" &&
        trace.model === commandModel &&
        trace.effectiveReturnCode === 0 &&
        trace.timedOut === false &&
        trace.usage?.output_tokens > 0,
      "No successful model execution receipt",
    );
    const rawResponse = readArtifact(
      required("raw_response").path,
      root,
    ).text.trim();
    requireCondition(
      rawResponse.length > 0 &&
        readArtifact(
          required("codex_last_message", "codex_last_message.txt").path,
          root,
        ).text.trim() === rawResponse,
      "Raw response does not match the model output",
    );
    const events = readArtifact(
      required("codex_stdout_jsonl", "codex_stdout.jsonl").path,
      root,
    )
      .text.trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    requireCondition(
      events.some(
        (event) =>
          event.type === "turn.completed" && event.usage?.output_tokens > 0,
      ) &&
        events.some(
          (event) =>
            event.type === "item.completed" &&
            event.item?.type === "agent_message" &&
            event.item.text?.trim() === rawResponse,
        ),
      "Event stream does not contain the successful model response",
    );

    const normalized = jsonArtifact(normalizedRef.path, root);
    requireCondition(
      Array.isArray(normalized),
      "Normalized output is not a cell array",
    );
    const cell = normalized.find(
      (candidate: Json) =>
        candidate.dataPointId && candidate.dataPointId === forecast.dataPointId,
    );
    requireCondition(
      cell,
      "Archived output does not match the forecast target",
    );
    requireCondition(
      cell.unit === forecast.unit,
      "Archived output uses a different unit",
    );
    const decoded = JSON.parse(
      rawResponse.replace(/^```(?:json)?\s*/, "").replace(/\s*```$/, ""),
    );
    const responseCells = Array.isArray(decoded)
      ? decoded
      : Array.isArray(decoded.cells)
        ? decoded.cells
        : [decoded];
    const responseCell = responseCells.find(
      (candidate: Json) => candidate.dataPointId === cell.dataPointId,
    );
    requireCondition(
      responseCell && responseCell.unit === cell.unit,
      "Normalized output is not the model's returned target",
    );
    for (const field of [
      "pointEstimate",
      "ciLow",
      "ciHigh",
      "confidence",
    ] as const) {
      requireCondition(
        Number.isFinite(cell[field]) && cell[field] === run[field],
        `Archived ${field} differs from the displayed run`,
      );
      requireCondition(
        responseCell[field] === cell[field],
        `Normalized ${field} differs from the model response`,
      );
    }
    requireCondition(
      cell.runAt === metadata.runAt,
      "Archived run time differs from the displayed run",
    );
    if (manifest.sealedAt)
      requireCondition(
        cell.runAt === manifest.sealedAt,
        "Normalized run time differs from the manifest seal",
      );
    requireCondition(
      canonicalStringify(metadata.sourceContext) ===
        canonicalStringify(cell.sourceContext),
      "Displayed source context differs from the archived run",
    );
    requireCondition(
      canonicalStringify(cell.reasoning) === canonicalStringify(run.reasoning),
      "Archived trace differs from the displayed run",
    );
    requireCondition(
      canonicalStringify(responseCell.reasoning) ===
        canonicalStringify(cell.reasoning),
      "Normalized trace differs from the model response",
    );
    requireCondition(
      canonicalStringify(cell.drivers) === canonicalStringify(run.drivers),
      "Archived drivers differ from the displayed run",
    );
    for (const field of ["drivers", "historicalContext", "sourceContext"]) {
      requireCondition(
        canonicalStringify(responseCell[field]) ===
          canonicalStringify(cell[field]),
        `Normalized ${field} differs from the model response`,
      );
    }
    if (cell.predictionDistribution) {
      requireCondition(
        canonicalStringify({
          ...cell.predictionDistribution,
          transformVersion: getDistributionTransformVersion(
            cell.predictionDistribution,
          ),
        }) ===
          canonicalStringify({
            ...run.predictionDistribution,
            transformVersion: getDistributionTransformVersion(
              run.predictionDistribution,
            ),
          }),
        "Archived distribution differs from the displayed run",
      );
    } else {
      requireCondition(
        canonicalStringify(run.predictionDistribution) ===
          canonicalStringify(
            buildNumericCdfFromInterval({
              pointEstimate: cell.pointEstimate,
              ciLow: cell.ciLow,
              ciHigh: cell.ciHigh,
            }),
          ),
        "Unarchived distribution differs from the documented interval transform",
      );
    }
    const fromResponse = responseDistribution(responseCell);
    const archiveDistribution =
      cell.predictionDistribution ?? run.predictionDistribution;
    // agent_cdf_v1 rounds to 10 decimal places in Python. Permit the public
    // 1e-9 tolerance, or four float64 rounding units for large dollar values.
    const distributionMatchesResponse = responseCell.predictionDistribution
      ? canonicalStringify(comparableDistribution(fromResponse)) ===
        canonicalStringify(comparableDistribution(archiveDistribution))
      : equalWithinRounding(
          comparableDistribution(fromResponse),
          comparableDistribution(archiveDistribution),
        );
    requireCondition(
      distributionMatchesResponse,
      "Archived distribution differs from the model response or its documented transform",
    );
    const validation = jsonArtifact(required("validation_report").path, root);
    requireCondition(
      validation.ok === true &&
        validation.cells?.some(
          (item: Json) =>
            item.slug === cell.slug &&
            item.ok === true &&
            Array.isArray(item.errors) &&
            item.errors.length === 0,
        ),
      "Archived output did not pass validation",
    );
    requireCondition(
      manifest.validation?.ok === true,
      "Manifest validation failed",
    );
    return {
      eligible: true,
      reason: "Archived output and successful model execution verified",
      cell,
      archive: { root, refs: manifestRefs },
    };
  } catch (error) {
    return failure(
      error instanceof Error ? error.message : "Archive verification failed",
    );
  }
}

export function verifyForecastRun(
  forecast: ForecastCell,
  run: ForecastRunEntry,
  options: VerificationOptions = {},
): ForecastRunVerification {
  const { eligible, reason } = verifyRun(forecast, run, options);
  return { eligible, reason };
}

/** Only verified archive artifacts may populate the public evidence view. */
export function loadForecastToolEvidence(
  forecast: ForecastCell,
  options: VerificationOptions = {},
): ForecastToolEvidenceByVariant {
  return Object.fromEntries(
    getForecastRunEntries(forecast).map((run) => {
      const verification = verifyRun(forecast, run, options);
      let evidence: ForecastToolEvidence;
      if (!verification.eligible || !verification.archive) {
        evidence = { status: "invalid" };
      } else {
        const { root, refs } = verification.archive;
        const artifacts = refs.filter(
          (ref) => ref.artifactType === "tool_evidence",
        );
        const reports = refs.filter(
          (ref) => ref.artifactType === "tool_evidence_verification",
        );
        if (!artifacts.length && !reports.length) {
          evidence = { status: "missing" };
        } else {
          try {
            requireCondition(
              artifacts.length === reports.length,
              "Missing evidence or replay report",
            );
            evidence = {
              status: "available",
              artifacts: artifacts.map((ref) => {
                const filename = path.posix.basename(ref.path);
                requireCondition(
                  [
                    "tool_evidence.json",
                    "draft_tool_evidence.json",
                    "pre_submit_review_tool_evidence.json",
                  ].includes(filename),
                  "Unsupported evidence stage",
                );
                const verificationPath = ref.path.replace(
                  /tool_evidence\.json$/,
                  "tool_evidence_verification.json",
                );
                const report = reports.find(
                  (candidate) => candidate.path === verificationPath,
                );
                requireCondition(report, "Missing bound tool replay report");
                const prefix = filename.slice(0, -"tool_evidence.json".length);
                const directory = path.posix.dirname(ref.path);
                const commandRef = refs.find(
                  (candidate) =>
                    candidate.artifactType === "command" &&
                    candidate.path === `${directory}/${prefix}command.json`,
                );
                const stdoutRef = refs.find(
                  (candidate) =>
                    candidate.artifactType === "codex_stdout_jsonl" &&
                    candidate.path ===
                      `${directory}/${prefix}codex_stdout.jsonl`,
                );
                requireCondition(
                  commandRef && stdoutRef,
                  "Missing stage command or native tool events",
                );
                return {
                  stage:
                    filename === "tool_evidence.json"
                      ? "forecast"
                      : filename === "draft_tool_evidence.json"
                        ? "draft"
                        : "review",
                  artifactPath: ref.path,
                  artifactSha256: ref.sha256,
                  verificationPath,
                  calls: readCapturedToolCalls(
                    readArtifact(ref.path, root).text,
                    readArtifact(report.path, root).text,
                    {
                      prefix,
                      command: jsonArtifact(commandRef.path, root),
                      stdout: readArtifact(stdoutRef.path, root).text,
                    },
                  ),
                };
              }),
            };
          } catch {
            evidence = { status: "invalid" };
          }
        }
      }
      return [run.variantId, evidence];
    }),
  );
}

export function filterPublishedForecasts(
  cells: ForecastCell[],
  options: VerificationOptions = {},
): ForecastCell[] {
  return cells.flatMap((forecast) => {
    const candidates = getForecastRunEntries(forecast)
      .map((run) => ({ run, verification: verifyRun(forecast, run, options) }))
      .filter(({ verification }) => verification.eligible);
    if (!candidates.length) return [];
    // Keep a valid original primary. Promotion is required only when the
    // catalog headline was illustrative or lacks verifiable receipts.
    const primary =
      candidates.find(({ run }) => run.isPrimary) ??
      [...candidates].sort(
        (a, b) =>
          Date.parse(b.run.predictionRun!.runAt) -
          Date.parse(a.run.predictionRun!.runAt),
      )[0];
    const { run, verification } = primary;
    const comparisonRuns: ForecastComparisonRun[] = candidates
      .filter((candidate) => candidate !== primary)
      .map(({ run: comparison, verification: comparisonVerification }) => ({
        ...comparison,
        historicalContext: comparisonVerification.cell!.historicalContext,
        predictionRun: comparison.predictionRun!,
      }));
    return [
      {
        ...forecast,
        primaryVariantId: run.variantId,
        normalizationCutoffRunAt:
          forecast.normalizationCutoffRunAt !== undefined
            ? forecast.normalizationCutoffRunAt
            : (forecast.predictionRun?.runAt ?? null),
        pointEstimate: run.pointEstimate,
        ciLow: run.ciLow,
        ciHigh: run.ciHigh,
        confidence: run.confidence,
        drivers: run.drivers,
        reasoning: run.reasoning,
        historicalContext: verification.cell!.historicalContext,
        predictionRun: run.predictionRun,
        predictionDistribution: run.predictionDistribution,
        comparisonRuns,
      },
    ];
  });
}

let publishedForecasts: ForecastCell[] | undefined;
export function getPublishedForecasts(): ForecastCell[] {
  return (publishedForecasts ??= filterPublishedForecasts(FORECAST_CELLS));
}

export function getPublishedForecast(slug: string): ForecastCell | undefined {
  return getPublishedForecasts().find((forecast) => forecast.slug === slug);
}
