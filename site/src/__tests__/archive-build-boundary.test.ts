import { afterEach, describe, expect, it } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import nextConfig from "../../next.config";

const require = createRequire(import.meta.url);
const picomatch = require("next/dist/compiled/picomatch");
const script = path.resolve(process.cwd(), "scripts/check-archive-traces.mjs");
const roots: string[] = [];
afterEach(() =>
  roots
    .splice(0)
    .forEach((root) => fs.rmSync(root, { recursive: true, force: true })),
);

function buildFixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "thesis-build-boundary-"));
  roots.push(root);
  const site = path.join(root, "site");
  const build = path.join(site, ".next");
  const write = (name: string, content: string) => {
    const file = path.join(build, name);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, content);
    return file;
  };
  const routes = Object.fromEntries(
    [
      "/forecasts",
      "/brier/reward.json",
      "/log.json",
      "/targets.json",
      "/uk-claimant-count-june-2026",
      "/log/runs/0001.json",
      "/forecasts/targets/refs/0001.json",
    ].map((route) => [
      route,
      { initialRevalidateSeconds: false, dataRoute: null },
    ]),
  );
  const manifest = {
    routes,
    dynamicRoutes: {
      "/log/[collection]/[chunk]": { fallback: false },
      "/forecasts/targets/[table]/[chunk]": { fallback: false },
    },
  };
  const manifestFile = write(
    "prerender-manifest.json",
    JSON.stringify(manifest),
  );
  Object.keys(routes).forEach((route) =>
    write(`server/app${route}.body`, "{}"),
  );
  const traceFile = write(
    "server/app/brier/reward.json/route.js.nft.json",
    JSON.stringify({ version: 1, files: ["route.js"] }),
  );
  return {
    root,
    site,
    build,
    write,
    traceFile,
    manifest,
    manifestFile,
    check: () =>
      spawnSync(process.execPath, [script], { cwd: site, encoding: "utf8" }),
  };
}

describe("production archive boundary", () => {
  it("keeps project-relative archive exclusions inside the explicit Turbopack root", () => {
    expect(nextConfig.outputFileTracingRoot).toBe(
      path.resolve(process.cwd(), ".."),
    );
    const archive = path.resolve(process.cwd(), "../records");
    const relative = path.relative(nextConfig.outputFileTracingRoot!, archive);
    expect(relative).toBe("records");
  });

  it("uses Next's route and project-relative matching to exclude archive inputs only", () => {
    for (const route of [
      "/brier/reward.json",
      "/forecasts/[slug]",
      "/[slug]",
      "/log/runs/0001.json",
    ]) {
      const patterns = Object.entries(nextConfig.outputFileTracingExcludes!)
        .filter(([key]) => picomatch(key, { dot: true, contains: true })(route))
        .flatMap(([, values]) =>
          values.map((value) => path.join(process.cwd(), value)),
        );
      const excludes = picomatch(patterns, { dot: true, contains: true });
      expect(
        excludes(
          path.resolve(
            "../records/thesis-analyst/2026-09-20/run/tool_evidence.json",
          ),
        ),
      ).toBe(true);
      expect(
        excludes(path.resolve(".next/server/app/brier/reward.json.body")),
      ).toBe(false);
    }
  });

  it("accepts archive-free traces with complete immutable prerender outputs", () => {
    const result = buildFixture().check();
    expect(result.status, result.stderr).toBe(0);
    expect(result.stdout).toContain(
      "7 prerendered routes retain their outputs",
    );
  });

  it("fails when any trace pulls records back into a deployment function", () => {
    const fixture = buildFixture();
    fs.writeFileSync(
      fixture.traceFile,
      JSON.stringify({
        version: 1,
        files: [
          path.relative(
            path.dirname(fixture.traceFile),
            path.join(
              fixture.root,
              "records/thesis-analyst/run/tool_evidence.json",
            ),
          ),
        ],
      }),
    );
    const result = fixture.check();
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("includes 1 build-only archive files");
  });

  it("fails when required static outputs disappear or become runtime-dependent", () => {
    const fixture = buildFixture();
    fs.unlinkSync(
      path.join(fixture.build, "server/app/brier/reward.json.body"),
    );
    fixture.manifest.routes["/forecasts"].initialRevalidateSeconds =
      60 as unknown as false;
    fixture.manifest.dynamicRoutes["/log/[collection]/[chunk]"].fallback =
      null as unknown as boolean;
    fs.writeFileSync(fixture.manifestFile, JSON.stringify(fixture.manifest));
    const result = fixture.check();
    expect(result.status).toBe(1);
    expect(result.stderr).toContain(
      "missing its prerendered HTML or response body",
    );
    expect(result.stderr).toContain("requires runtime regeneration");
    expect(result.stderr).toContain("permits unbuilt chunks at runtime");
  });
});
