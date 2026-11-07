import { execFileSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import { canonicalStringify, sha256Hex } from "@/data/canonical-json";

describe("Python/TypeScript canonical JSON parity", () => {
  it("matches for UTF-16-sensitive keys, astral text, escapes, and numbers", () => {
    const value = {
      "\ue000": 3,
      "😀": 2,
      "\ud7ff": 1,
      nested: {
        quote: 'a"b\\c\n',
        controls: "\u0000\u001f\b\t\n\f\r\u007f",
        loneSurrogates: "\ud83d \udfff \ud7ff \ue000",
        negativeZero: -0,
        fixedSmall: 1e-6,
        scientificSmall: 1e-7,
        fixedLarge: 1e20,
        scientificLarge: 1e21,
        roundedUnsafeInteger: 9007199254740993,
      },
    };
    const input = JSON.stringify(value);
    const pythonCanonical = execFileSync(
      "python3",
      ["../scripts/canonical_json.py"],
      { input, encoding: "utf8" },
    ).trimEnd();
    const pythonSha = execFileSync(
      "python3",
      ["../scripts/canonical_json.py", "--sha256"],
      { input, encoding: "utf8" },
    ).trim();

    expect(pythonCanonical).toBe(canonicalStringify(value));
    expect(pythonSha).toBe(sha256Hex(value));
  });
});
