import type { NextConfig } from "next";
import path from "node:path";

const CANONICAL_HOST = "thesisinstitute.org";
const APP_HOST = "app.thesisinstitute.org";
const LEGACY_HOSTS = ["www.thesisinstitute.org"];

const nextConfig: NextConfig = {
  // Keep the site and its sibling build inputs inside Turbopack’s root.
  // Next synchronizes turbopack.root to outputFileTracingRoot.
  outputFileTracingRoot: path.resolve(__dirname, ".."),
  // Archive verification runs while prerendering. Its filesystem reads must
  // not package the complete public archive into each deployment function.
  // Next resolves exclusion values relative to this site directory.
  outputFileTracingExcludes: { "/*": ["../records/**"] },
  async redirects() {
    return [
      // /about retired in the ledger migration; its successor is /thesis.
      // The apex landing and old links still point at /about.
      { source: "/about", destination: "/thesis", permanent: false },
      // Topic views retired 2026-07-21 (deterministic facets on the
      // forecasts browser replaced them); temporary in case a curated
      // collections product revives the path.
      { source: "/topics/:path*", destination: "/", permanent: false },
      // Challenge lane v1 withdrawn 2026-08-23 (rebuilt properly on branch
      // challenge-lane-v2); accepted v1 submissions stay published on their cells.
      { source: "/challenge", destination: "/", permanent: false },
      {
        source: "/markets/:path*",
        destination: "/forecasts/:path*",
        permanent: true,
      },
      {
        source: "/forecasts",
        has: [{ type: "host" as const, value: APP_HOST }],
        destination: `https://${APP_HOST}`,
        permanent: true,
      },
      {
        source: "/forecasts/:path*",
        has: [{ type: "host" as const, value: APP_HOST }],
        destination: `https://${APP_HOST}/:path*`,
        permanent: true,
      },
      ...LEGACY_HOSTS.map((host) => ({
        source: "/:path*",
        has: [{ type: "host" as const, value: host }],
        destination: `https://${CANONICAL_HOST}/:path*`,
        permanent: true,
      })),
    ];
  },
  async rewrites() {
    return {
      beforeFiles: [
        {
          source: "/",
          has: [{ type: "host" as const, value: APP_HOST }],
          destination: "/forecasts",
        },
        {
          source: "/ledger",
          has: [{ type: "host" as const, value: APP_HOST }],
          destination: "/forecasts/ledger",
        },
        {
          source: "/ledger.json",
          has: [{ type: "host" as const, value: APP_HOST }],
          destination: "/forecasts/ledger.json",
        },
        {
          source: "/judges.json",
          has: [{ type: "host" as const, value: APP_HOST }],
          destination: "/forecasts/judges.json",
        },
        // The target-architecture projection chunks live under
        // /forecasts/targets/*; the app-host redirect strips the /forecasts
        // prefix, so without this rewrite every chunk URL in the published
        // targets.json manifest 308s into a 404.
        {
          source: "/targets/:path*",
          has: [{ type: "host" as const, value: APP_HOST }],
          destination: "/forecasts/targets/:path*",
        },
      ],
    };
  },
};

export default nextConfig;
