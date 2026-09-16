import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Same discipline as adapter-union-sync: a union member the python runner can
// seal but the TS type does not name breaks the site build only AFTER a run
// lands in the records. The System One runner seals four artifact types the
// analyst never wrote (state, questions, request, response) plus error.json
// on every failure phase, so this test moves that failure to the PR that
// changes the runner's inventory.
function pythonArtifactTypes(): string[] {
  const py = readFileSync(
    join(__dirname, "../../../scripts/run_system_one_forecast.py"),
    "utf8",
  );
  const success = py.match(/\nSUCCESS_INVENTORY = \(([\s\S]*?)\n\)\n/);
  const failures = py.match(/\nFAILURE_INVENTORIES = \{([\s\S]*?)\n\}\n/);
  expect(success).not.toBeNull();
  expect(failures).not.toBeNull();
  const pairs = /\("([a-z0-9_]+)",\s*"[^"]+"\)/g;
  const types = [
    ...[...success![1].matchAll(pairs)].map((match) => match[1]),
    ...[...failures![1].matchAll(pairs)].map((match) => match[1]),
    // Every sealed run names its own manifest as the last inventory entry.
    "manifest",
  ];
  return [...new Set(types)].sort();
}

function unionMembers(): string[] {
  const ts = readFileSync(
    join(__dirname, "../data/forecast-cells.ts"),
    "utf8",
  );
  const union = ts.match(
    /export type PredictionRunActivityArtifactType =([\s\S]*?);\n/,
  );
  expect(union).not.toBeNull();
  return [...union![1].matchAll(/"([^"]+)"/g)].map((match) => match[1]);
}

describe("System One activity artifact types", () => {
  it("are all nameable by PredictionRunActivityArtifactType", () => {
    const members = unionMembers();
    for (const artifactType of pythonArtifactTypes()) {
      expect(members).toContain(artifactType);
    }
  });

  it("covers the four System One artifacts and the sealed error", () => {
    const members = unionMembers();
    expect(members).toEqual(expect.arrayContaining([
      "system_one_state",
      "system_one_questions",
      "system_one_request",
      "system_one_response",
      "error",
    ]));
    // The runner's own inventory is the source of this list, not this test.
    expect(pythonArtifactTypes()).toEqual(
      expect.arrayContaining([
        "system_one_state",
        "system_one_questions",
        "system_one_request",
        "system_one_response",
        "error",
      ]),
    );
  });
});
