#!/usr/bin/env node

import { readdir, readFile, stat } from "node:fs/promises";
import { dirname, join, relative, resolve, sep } from "node:path";

const site = process.cwd();
const build = resolve(site, ".next");
const archives = resolve(site, "../records");
const failures = [];
const within = (parent, file) => {
  const child = relative(parent, file);
  return (
    child === "" ||
    (!child.startsWith(`..${sep}`) && child !== ".." && !child.startsWith(sep))
  );
};

async function traces(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const found = await Promise.all(
    entries.map(async (entry) => {
      const file = join(directory, entry.name);
      if (entry.isDirectory()) return traces(file);
      return entry.isFile() && entry.name.endsWith(".nft.json") ? [file] : [];
    }),
  );
  return found.flat();
}

try {
  const files = [
    ...(await traces(join(build, "server"))),
    ...(await readdir(build))
      .filter((name) => name.endsWith(".nft.json"))
      .map((name) => join(build, name)),
  ];
  if (!files.length) throw new Error("No production file traces found");
  for (const file of files) {
    const trace = JSON.parse(await readFile(file, "utf8"));
    const archived = trace.files.filter((entry) =>
      within(archives, resolve(dirname(file), entry)),
    );
    if (archived.length)
      failures.push(
        `${relative(site, file)} includes ${archived.length} build-only archive files`,
      );
  }
  const manifest = JSON.parse(
    await readFile(join(build, "prerender-manifest.json"), "utf8"),
  );
  const routeNames = Object.keys(manifest.routes);
  const required = [
    "/forecasts",
    "/brier/reward.json",
    "/log.json",
    "/targets.json",
    "/uk-claimant-count-june-2026",
  ];
  for (const prefix of ["/log/", "/forecasts/targets/"]) {
    const chunk = routeNames.find((route) => route.startsWith(prefix));
    if (chunk) required.push(chunk);
    else failures.push(`${prefix} has no prerendered chunks`);
  }
  const routes = required.flatMap((route) => {
    if (Object.hasOwn(manifest.routes, route))
      return [[route, manifest.routes[route]]];
    failures.push(`${route} is missing from prerendered routes`);
    return [];
  });
  await Promise.all(
    routes.map(async ([route, metadata]) => {
      if (metadata.initialRevalidateSeconds !== false)
        failures.push(`${route} requires runtime regeneration`);
      const stem = join(
        build,
        "server/app",
        route === "/" ? "index" : route.slice(1),
      );
      const outputs = await Promise.all(
        [".html", ".body"].map(async (extension) => {
          try {
            return (await stat(stem + extension)).isFile();
          } catch {
            return false;
          }
        }),
      );
      if (!outputs.some(Boolean))
        failures.push(
          `${route} is missing its prerendered HTML or response body`,
        );
      if (metadata.dataRoute) {
        const data = join(build, "server/app", metadata.dataRoute.slice(1));
        try {
          if (!(await stat(data)).isFile()) throw new Error();
        } catch {
          failures.push(`${route} is missing its prerendered RSC payload`);
        }
      }
    }),
  );
  for (const route of [
    "/log/[collection]/[chunk]",
    "/forecasts/targets/[table]/[chunk]",
  ]) {
    if (manifest.dynamicRoutes[route]?.fallback !== false)
      failures.push(`${route} permits unbuilt chunks at runtime`);
  }
  if (failures.length) throw new Error(failures.join("\n"));
  console.log(
    `Archive boundary: ${files.length} traces exclude records; ${routes.length} prerendered routes retain their outputs.`,
  );
} catch (error) {
  console.error(`Archive boundary check failed: ${error.message}`);
  process.exitCode = 1;
}
