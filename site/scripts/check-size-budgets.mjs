#!/usr/bin/env node

import { stat } from "node:fs/promises";
import { resolve } from "node:path";

const budgets = [
  {
    label: "forecasts.html",
    path: ".next/server/app/forecasts.html",
    maxBytes: 12 * 1024 * 1024,
  },
  {
    label: "log.json",
    path: ".next/server/app/log.json.body",
    maxBytes: 8 * 1024 * 1024,
  },
];

let failed = false;
for (const budget of budgets) {
  const file = resolve(process.cwd(), budget.path);
  let bytes;
  try {
    bytes = (await stat(file)).size;
  } catch (error) {
    console.error(`size budget: missing ${budget.path}: ${error.message}`);
    failed = true;
    continue;
  }
  const mebibytes = (bytes / (1024 * 1024)).toFixed(2);
  const maxMebibytes = (budget.maxBytes / (1024 * 1024)).toFixed(0);
  console.log(
    `${budget.label}: ${bytes} bytes (${mebibytes} MiB), budget ${maxMebibytes} MiB`,
  );
  if (bytes > budget.maxBytes) {
    console.error(
      `size budget exceeded: ${budget.label} is ${bytes} bytes; maximum is ${budget.maxBytes}`,
    );
    failed = true;
  }
}

// Also enforce the archive/runtime boundary on the real production build.
await import("./check-archive-traces.mjs");

if (failed) process.exit(1);
