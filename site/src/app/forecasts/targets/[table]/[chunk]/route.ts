import {
  buildTargetArchitectureChunkExport,
  buildTargetArchitectureTableExport,
  isTargetArchitectureTableKey,
} from "@/data/thesis-target-architecture-export";
import {
  loadTargetArchitectureManifest,
  loadTargetArchitectureProjection,
} from "@/data/thesis-target-architecture-runtime";

export const dynamic = "force-static";
export const dynamicParams = false;

// Standard dynamic segments expose params to Next's static generator; the
// .json extension is part of each generated value, preserving published URLs.
export async function generateStaticParams() {
  const manifest = await loadTargetArchitectureManifest();
  return manifest.tables.flatMap(({ table, chunks }) => [
    { table, chunk: "manifest.json" },
    ...chunks.map(({ index }) => ({ table, chunk: `${index}.json` })),
  ]);
}

interface TargetChunkRouteContext {
  params: Promise<{ table: string; chunk: string }>;
}

export async function GET(_request: Request, context: TargetChunkRouteContext) {
  const { table, chunk } = await context.params;
  if (!isTargetArchitectureTableKey(table)) {
    return Response.json(
      {
        error: "unknown_target_architecture_table",
        table,
      },
      { status: 404 },
    );
  }

  const [projection, manifest] = await Promise.all([
    loadTargetArchitectureProjection(),
    loadTargetArchitectureManifest(),
  ]);

  if (chunk === "manifest.json") {
    return Response.json(
      buildTargetArchitectureTableExport(projection, table, manifest),
    );
  }

  const chunkIndex = /^(0|[1-9]\d*)\.json$/.test(chunk)
    ? Number(chunk.slice(0, -5))
    : NaN;
  if (!Number.isInteger(chunkIndex) || chunkIndex < 0) {
    return Response.json(
      {
        error: "unknown_target_architecture_chunk",
        table,
        chunk,
      },
      { status: 404 },
    );
  }

  const tableManifest = manifest.tables.find(
    (candidate) => candidate.table === table,
  );
  if (!tableManifest || chunkIndex >= tableManifest.chunkCount) {
    return Response.json(
      {
        error: "unknown_target_architecture_chunk",
        table,
        chunk,
      },
      { status: 404 },
    );
  }

  return Response.json(
    buildTargetArchitectureChunkExport(projection, table, chunkIndex, manifest),
  );
}
