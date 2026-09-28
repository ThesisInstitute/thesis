import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

/**
 * Slice full section text for a provision out of the cached raw bill
 * text (bills/raw/<slug>.txt). Interim implementation: keyed on the
 * federal "SEC. NNNN." headings and the section numbers named in the
 * provision heading; replaced by ingest-emitted provision spans once
 * the chunker lands (issue #43). Returns null rather than guessing —
 * never show the wrong text. Flattened XML can use reviewed exact spans in
 * bills/raw/<slug>.sections.json, bound to the raw source bytes' SHA-256.
 */

const RAW_DIR = path.join(process.cwd(), "..", "bills", "raw");

// Small-caps extraction splits a word's first letter off ("A UTHORIZATION");
// joining is safe unless the remainder is itself a real word that
// legitimately follows a single-letter word in caps headings.
const CAPS_WORDS = new Set([
  "AND", "OR", "OF", "THE", "TO", "IN", "ON", "BY", "FOR", "AS", "AT",
  "AN", "IS", "ARE", "BE", "NO", "NOT", "ACT", "BILL", "LAW", "USE",
  "PROGRAM", "PROGRAMS", "PLAN", "REPORT", "STATE", "NEW",
]);

/** A line that begins a new structural unit of statutory text. */
function startsUnit(line: string): boolean {
  return /^(?:[‘'"“]{1,2})?\(|^(?:[‘'"“]{1,2})?SEC(?:TION)?\.?\s/i.test(line);
}

// Reflow committee-print typography into readable paragraphs: drop page
// furniture ("RYA26731 1TW [file 1 of 2]  S.L.C.", bare page numbers),
// strip line-number gutters (including the "CYBERSECU -5 / RITY" form
// where the gutter lands after a typesetting hyphen), rejoin
// hyphenated word breaks, and merge lines so text wraps naturally,
// breaking only at SEC. headings and quoted designators like ''(23),
// ''(A), ''(i).
export function cleanForDisplay(slice: string): string {
  const lines = slice
    .split("\n")
    .filter((line) => !/^\s*\d+\s*$/.test(line))
    .filter((line) => !/\[file \d+ of \d+\]|S\.L\.C\./.test(line))
    .map((line) =>
      line
        .replace(/\s?[-–]\s?\d{1,3}\s*$/, "-")
        .replace(/\s+\d{1,3}\s*$/, "")
        .trim(),
    )
    .filter((line) => line !== "");

  const paragraphs: string[] = [];
  let buffer = "";
  for (const line of lines) {
    if (buffer === "") {
      buffer = line;
    } else if (startsUnit(line)) {
      paragraphs.push(buffer);
      buffer = line;
    } else if (buffer.endsWith("-")) {
      buffer = buffer.slice(0, -1) + line;
    } else {
      buffer += " " + line;
    }
  }
  if (buffer) paragraphs.push(buffer);

  return paragraphs
    .map((p) =>
      p
        .replace(/\b([A-Z]) ([A-Z])\b(?=[ .])/g, "$1$2")
        .replace(/\b([A-Z]) ([A-Z]{2,})\b/g, (match, first, rest) =>
          CAPS_WORDS.has(rest) ? match : first + rest,
        )
        .replace(/\s+(?=\.—)/g, "")
        .replace(/\s{2,}/g, " "),
    )
    .join("\n\n");
}

export function loadRawBillText(slug: string): string | null {
  const file = path.join(RAW_DIR, `${slug}.txt`);
  if (!fs.existsSync(file)) return null;
  return fs.readFileSync(file, "utf-8");
}

/** Section numbers named in a provision heading, e.g. "§§2101, 2105, and 2401(1)" → ["2101","2105","2401"]. */
export function parseSectionNumbers(heading: string, title: string): string[] {
  const source = `${title} ${heading}`;
  const cited = source.match(/§§?[\d\s,()–\-and]+/g)?.join(" ") ?? "";
  // Negative lookbehind/ahead drop parenthesized subsection designators
  // — the (1) in "2401(1)" is not a section number.
  const numbers = [...cited.matchAll(/(?<!\()\b(\d{1,4})\b(?!\))/g)].map(
    (m) => m[1],
  );
  const unique = [...new Set(numbers)];
  if (unique.length > 0) return unique;
  const plain = title.match(/^Section\s+(\d{1,4})$/i);
  return plain ? [plain[1]] : [];
}

export function extractSections(
  rawText: string,
  sectionNumbers: string[],
): string | null {
  const slices: string[] = [];
  for (const num of sectionNumbers) {
    const start = rawText.search(
      new RegExp(`^SEC(?:TION)?\\.?\\s*${num}\\.`, "m"),
    );
    if (start === -1) continue;
    const rest = rawText.slice(start);
    const next = rest.slice(6).search(/^SEC(?:TION)?\.?\s*\d{1,4}\./m);
    const slice = next === -1 ? rest : rest.slice(0, next + 6);
    slices.push(cleanForDisplay(slice));
  }
  // Partial coverage is fine (a provision citing §§2101 and 2105 shows
  // both found sections); zero coverage means our slicer failed — show
  // nothing rather than something wrong.
  return slices.length > 0 ? slices.join("\n\n· · ·\n\n") : null;
}

/**
 * A reviewed sidecar identifies whole sections when extraction lost headings.
 * The review establishes section boundaries; these checks only authenticate
 * the source version and require every supplied span to remain verbatim.
 */
export function reviewedSections(
  rawBytes: Uint8Array,
  sectionNumbers: string[],
  sidecar: unknown,
): string | null {
  if (!sidecar || typeof sidecar !== "object" || Array.isArray(sidecar)) {
    return null;
  }
  const value = sidecar as Record<string, unknown>;
  if (
    Object.keys(value).sort().join(",") !== "sections,sourceTextSha256" ||
    typeof value.sourceTextSha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(value.sourceTextSha256) ||
    createHash("sha256").update(rawBytes).digest("hex") !== value.sourceTextSha256 ||
    !value.sections ||
    typeof value.sections !== "object" ||
    Array.isArray(value.sections)
  ) {
    return null;
  }
  const rawText = Buffer.from(rawBytes).toString("utf8");
  const sections = value.sections as Record<string, unknown>;
  if (
    Object.entries(sections).some(([number, text]) =>
      !/^[1-9][0-9]{0,3}$/.test(number) ||
      typeof text !== "string" ||
      !text.trim() ||
      !rawText.includes(text),
    ) ||
    sectionNumbers.length === 0 ||
    sectionNumbers.some((number) => !Object.hasOwn(sections, number))
  ) {
    return null;
  }
  return sectionNumbers.map((number) => sections[number] as string).join("\n\n· · ·\n\n");
}

export function fullSectionText(
  slug: string,
  heading: string,
  title: string,
): string | null {
  const numbers = parseSectionNumbers(heading, title);
  if (numbers.length === 0) return null;
  const rawPath = path.join(RAW_DIR, `${slug}.txt`);
  if (!fs.existsSync(rawPath)) return null;
  const rawBytes = fs.readFileSync(rawPath);
  const parsed = extractSections(rawBytes.toString("utf8"), numbers);
  if (parsed !== null) return parsed;
  const sidecarPath = path.join(RAW_DIR, `${slug}.sections.json`);
  if (!fs.existsSync(sidecarPath)) return null;
  try {
    return reviewedSections(
      rawBytes,
      numbers,
      JSON.parse(fs.readFileSync(sidecarPath, "utf8")),
    );
  } catch {
    return null;
  }
}
