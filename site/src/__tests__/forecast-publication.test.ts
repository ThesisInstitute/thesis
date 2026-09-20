import { afterEach, describe, expect, it } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import {
  filterPublishedForecasts,
  verifyForecastRun,
} from "@/lib/forecast-publication";
import {
  getForecastRunEntries,
  type ForecastCell,
  type PredictionRunActivityArtifact,
} from "@/data/forecast-cells";
import { buildNumericCdfFromInterval } from "@/data/prediction-distribution";
import { canonicalStringify, sha256Hex } from "@/data/canonical-json";

const roots: string[] = [];
afterEach(() => {
  for (const root of roots.splice(0))
    fs.rmSync(root, { recursive: true, force: true });
});

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "thesis-publication-"));
  roots.push(root);
  const directory = "records/thesis-analyst/2026-09-20/test-run";
  fs.mkdirSync(path.join(root, directory), { recursive: true });
  const runAt = "2026-09-20T10:00:00Z";
  const cell = {
    slug: "test-forecast",
    type: "data",
    title: "Test forecast",
    question: "What will the value be?",
    unit: "percent",
    dataPointId: "test.series.2027.first_print",
    pointEstimate: 13,
    ciLow: 11.9,
    ciHigh: 14.3,
    confidence: 0.8,
    resolutionDate: "2027-01-10",
    resolutionSource: "Test agency",
    resolutionRule: "First print",
    runAt,
    historicalContext: [{ label: "2024", value: 13.4 }],
    drivers: ["Recent data"],
    sourceContext: ["https://example.gov"],
    reasoning: [
      { kind: "text", text: "The estimate uses the recent release." },
      { kind: "forecast", point: 13, ciLow: 11.9, ciHigh: 14.3 },
    ],
    predictionDistribution: buildNumericCdfFromInterval({
      pointEstimate: 13,
      ciLow: 11.9,
      ciHigh: 14.3,
    }),
  };
  const validation = {
    ok: true,
    cells: [{ slug: cell.slug, ok: true, errors: [] }],
  };
  const rawResponse = JSON.stringify(cell);
  const command = {
    argv: ["/usr/local/bin/codex", "exec", "-m", "test-model"],
    returnCode: 0,
    processReturnCode: 0,
    timedOut: false,
  };
  const trace = {
    backend: "codex-exec",
    model: "test-model",
    effectiveReturnCode: 0,
    timedOut: false,
    usage: { output_tokens: 100 },
  };
  const values = new Map<
    string,
    { type: PredictionRunActivityArtifact["artifactType"]; content: string }
  >([
    ["prompt.md", { type: "prompt", content: "Forecast this target." }],
    ["command.json", { type: "command", content: JSON.stringify(command) }],
    [
      "codex_trace.json",
      { type: "codex_trace", content: JSON.stringify(trace) },
    ],
    ["raw_response.txt", { type: "raw_response", content: rawResponse }],
    [
      "codex_last_message.txt",
      { type: "codex_last_message", content: rawResponse },
    ],
    [
      "codex_stdout.jsonl",
      {
        type: "codex_stdout_jsonl",
        content: [
          JSON.stringify({
            type: "item.completed",
            item: { type: "agent_message", text: rawResponse },
          }),
          JSON.stringify({
            type: "turn.completed",
            usage: { output_tokens: 100 },
          }),
        ].join("\n"),
      },
    ],
    [
      "normalized_cells.json",
      { type: "normalized_cell", content: JSON.stringify([cell]) },
    ],
    [
      "validation.json",
      { type: "validation_report", content: JSON.stringify(validation) },
    ],
  ]);
  const forecast = {
    ...cell,
    predictionRun: {
      kind: "recorded-agent-run",
      runAt,
      agent: "thesis.analyst",
      model: "test-model",
      sourceContext: ["https://example.gov"],
      activityLog: [],
    },
  } as ForecastCell;
  const writeRef = (
    filename: string,
    type: PredictionRunActivityArtifact["artifactType"],
    content: string,
  ): PredictionRunActivityArtifact => {
    fs.writeFileSync(path.join(root, directory, filename), content);
    return {
      artifactType: type,
      path: `${directory}/${filename}`,
      bytes: Buffer.byteLength(content),
      sha256: createHash("sha256").update(content).digest("hex"),
      createdAt: runAt,
    };
  };
  const seal = (canonical = false) => {
    const refs = [...values].map(([name, entry]) =>
      writeRef(name, entry.type, entry.content),
    );
    const manifest: Record<string, any> = {
      schemaVersion: "thesis_analyst_run_manifest_v1",
      agent: { agent: "thesis.analyst", model: "test-model" },
      ok: true,
      validation,
      artifacts: refs,
    };
    if (!canonical) {
      forecast.predictionRun!.activityLog = [
        ...refs,
        writeRef("manifest.json", "manifest", JSON.stringify(manifest)),
      ];
    } else {
      const hashMode =
        "canonical-json-v1; exclude artifacts where artifactType=manifest and exclude custodyRootSha256";
      const canonicalBytes = Buffer.from(canonicalStringify(manifest));
      const manifestRef = {
        artifactType: "manifest",
        path: `${directory}/manifest.json`,
        bytes: canonicalBytes.length,
        sha256: createHash("sha256").update(canonicalBytes).digest("hex"),
        createdAt: runAt,
        hashMode,
      };
      manifest.artifacts = [...refs, manifestRef];
      const custody = {
        schemaVersion: "thesis_custody_root_v1",
        manifestWithoutCustodyRoot: {
          canonicalJsonSha256: sha256Hex(manifest),
        },
      };
      manifest.custodyRootSha256 = sha256Hex(custody);
      forecast.predictionRun!.custodyRootSha256 = manifest.custodyRootSha256;
      fs.writeFileSync(
        path.join(root, directory, "custody_root.json"),
        JSON.stringify(custody),
      );
      fs.writeFileSync(
        path.join(root, directory, "manifest.json"),
        JSON.stringify(manifest),
      );
      // Modern catalog metadata exposes the prefix; the root binds manifest.
      forecast.predictionRun!.activityLog = refs;
    }
  };
  seal();
  return {
    root,
    directory,
    cell,
    forecast,
    values,
    seal,
    command,
    validation,
    verify: () =>
      verifyForecastRun(forecast, getForecastRunEntries(forecast)[0], {
        repositoryRoot: root,
      }),
  };
}

describe("forecast publication archive gate", () => {
  it("accepts matching archive commitments and successful model output", () => {
    expect(fixture().verify().eligible).toBe(true);
  });

  it("verifies a canonical manifest bound through the catalog custody root", () => {
    const f = fixture();
    f.seal(true);
    expect(f.verify().eligible).toBe(true);
    fs.writeFileSync(path.join(f.root, f.directory, "custody_root.json"), "{}");
    expect(f.verify()).toMatchObject({
      eligible: false,
      reason: "Custody root commitment mismatch",
    });
  });

  it("rejects unarchived seeds and metadata-only model labels", () => {
    const f = fixture();
    delete f.forecast.predictionRun;
    expect(f.verify().eligible).toBe(false);
    expect(
      filterPublishedForecasts([f.forecast], { repositoryRoot: f.root }),
    ).toEqual([]);
  });

  it.each([
    "agent",
    "agentVersion",
    "promptHash",
    "toolPolicyHash",
    "model",
    "promptMode",
  ] as const)(
    "rejects altered %s attribution with copied receipts",
    (field) => {
      const f = fixture();
      expect(f.verify().eligible).toBe(true);
      f.forecast.predictionRun![field] = "invented";
      expect(f.verify().eligible).toBe(false);
    },
  );

  it("rechecks displayed output even after a successful cached file read", () => {
    const f = fixture();
    expect(f.verify().eligible).toBe(true);
    f.forecast.pointEstimate = 14;
    expect(f.verify()).toMatchObject({
      eligible: false,
      reason: "Archived pointEstimate differs from the displayed run",
    });
  });

  it("rejects modified artifact bytes after the first verification", () => {
    const f = fixture();
    expect(f.verify().eligible).toBe(true);
    fs.appendFileSync(path.join(f.root, f.directory, "prompt.md"), "changed");
    expect(f.verify()).toMatchObject({
      eligible: false,
      reason: expect.stringContaining("Artifact commitment mismatch"),
    });
  });

  it.each([
    "records/thesis-analyst/../outside.json",
    "/tmp/output.json",
    "ledger://observation/test",
  ])("rejects unsafe artifact paths: %s", (artifactPath) => {
    const f = fixture();
    f.forecast.predictionRun!.activityLog![0].path = artifactPath;
    expect(f.verify().eligible).toBe(false);
  });

  it("rejects symbolic links in an otherwise matching archive", () => {
    const f = fixture();
    const artifact = path.join(f.root, f.directory, "prompt.md");
    const other = path.join(f.root, "other.txt");
    fs.renameSync(artifact, other);
    fs.symlinkSync(other, artifact);
    expect(f.verify()).toMatchObject({
      eligible: false,
      reason: "Artifact path contains a symbolic link",
    });
  });

  it("rejects a mocked command despite successful metadata and matching hashes", () => {
    const f = fixture();
    f.command.argv = ["python", "write_fake_forecast.py"];
    f.values.get("command.json")!.content = JSON.stringify(f.command);
    f.seal();
    expect(f.verify()).toMatchObject({
      eligible: false,
      reason: "Command is not an archived Codex execution",
    });
  });

  it("rejects failed commands and failed validation", () => {
    const f = fixture();
    f.command.returnCode = 1;
    f.values.get("command.json")!.content = JSON.stringify(f.command);
    f.seal();
    expect(f.verify().eligible).toBe(false);
    f.command.returnCode = 0;
    f.validation.ok = false;
    f.values.get("command.json")!.content = JSON.stringify(f.command);
    f.values.get("validation.json")!.content = JSON.stringify(f.validation);
    f.seal();
    expect(f.verify().eligible).toBe(false);
  });

  it("rejects event streams without the recorded model response", () => {
    const f = fixture();
    f.values.get("codex_stdout.jsonl")!.content = JSON.stringify({
      type: "turn.completed",
      usage: { output_tokens: 100 },
    });
    f.seal();
    expect(f.verify()).toMatchObject({
      eligible: false,
      reason: "Event stream does not contain the successful model response",
    });
  });

  it("rejects normalized output altered after the model response even with new hashes", () => {
    const f = fixture();
    f.cell.reasoning[0] = { kind: "text", text: "Invented analysis" };
    f.values.get("normalized_cells.json")!.content = JSON.stringify([f.cell]);
    f.seal();
    expect(f.verify()).toMatchObject({
      eligible: false,
      reason: "Normalized trace differs from the model response",
    });
  });

  it("does not allow interval provenance to conceal a modified distribution", () => {
    const f = fixture();
    f.forecast.predictionDistribution!.points[20].probability = 0.001;
    expect(f.verify()).toMatchObject({
      eligible: false,
      reason: "Archived distribution differs from the displayed run",
    });
  });

  it("rejects a normalized distribution altered after the model response even with new hashes", () => {
    const f = fixture();
    f.cell.predictionDistribution.points[20].probability = 0.001;
    f.values.get("normalized_cells.json")!.content = JSON.stringify([f.cell]);
    f.seal();
    expect(f.verify()).toMatchObject({
      eligible: false,
      reason:
        "Archived distribution differs from the model response or its documented transform",
    });
  });

  it("projects comparison history from its verified output rather than catalog additions", () => {
    const f = fixture();
    const original = getForecastRunEntries(f.forecast)[0];
    f.forecast.comparisonRuns = [
      {
        ...original,
        variantId: "comparison",
        predictionRun: original.predictionRun!,
        historicalContext: [{ label: "2099", value: 999 }],
      },
    ];
    const [published] = filterPublishedForecasts([f.forecast], {
      repositoryRoot: f.root,
    });
    expect(published.comparisonRuns![0].historicalContext).toEqual(
      f.cell.historicalContext,
    );
    expect(published.historicalContext).toEqual(f.cell.historicalContext);
  });

  it("promotes a verified comparison without changing its canonical identity or cutoff", () => {
    const f = fixture();
    const original = getForecastRunEntries(f.forecast)[0];
    const seed: ForecastCell = {
      ...f.forecast,
      pointEstimate: 99,
      predictionRun: undefined,
      comparisonRuns: [
        {
          ...original,
          variantId: "recorded-comparison",
          predictionRun: original.predictionRun!,
        },
      ],
    };
    const [published] = filterPublishedForecasts([seed], {
      repositoryRoot: f.root,
    });
    expect(published.pointEstimate).toBe(13);
    expect(published.primaryVariantId).toBe("recorded-comparison");
    expect(getForecastRunEntries(published)[0].variantId).toBe(
      "recorded-comparison",
    );
    expect(published.normalizationCutoffRunAt).toBeNull();
    expect(published.comparisonRuns).toEqual([]);
    expect(
      filterPublishedForecasts([published], { repositoryRoot: f.root })[0]
        .normalizationCutoffRunAt,
    ).toBeNull();
  });
});
