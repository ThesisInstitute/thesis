import {
  buildThesisLogChunk,
  buildThesisLogManifest,
  isThesisLogChunkCollection,
  THESIS_LOG_CHUNK_SIZE,
  THESIS_LOG_CHUNK_COLLECTIONS,
} from "@/data/thesis-log";
import { loadThesisLogData } from "@/data/thesis-log-runtime";

export const dynamic = "force-static";
export const dynamicParams = false;

// Materialize every advertised chunk while the verified archive is available
// during the build. Deployed requests must not reconstruct from absent records.
export async function generateStaticParams() {
  const manifest = buildThesisLogManifest(await loadThesisLogData());
  return THESIS_LOG_CHUNK_COLLECTIONS.flatMap((collection) =>
    manifest.collections[collection].chunks.map(({ index }) => ({
      collection,
      chunk: `${index}.json`,
    })),
  );
}

interface ThesisLogChunkRouteContext {
  params: Promise<{ collection: string; chunk: string }>;
}

export async function GET(
  _request: Request,
  context: ThesisLogChunkRouteContext,
) {
  const { collection, chunk } = await context.params;
  if (!isThesisLogChunkCollection(collection)) {
    return Response.json(
      { error: "unknown_thesis_log_collection", collection },
      { status: 404 },
    );
  }

  const chunkIndex = /^(0|[1-9]\d*)\.json$/.test(chunk)
    ? Number(chunk.slice(0, -5))
    : NaN;
  const data = await loadThesisLogData();
  const chunkCount = Math.ceil(data[collection].length / THESIS_LOG_CHUNK_SIZE);
  if (
    !Number.isInteger(chunkIndex) ||
    chunkIndex < 0 ||
    chunkIndex >= chunkCount
  ) {
    return Response.json(
      { error: "unknown_thesis_log_chunk", collection, chunk },
      { status: 404 },
    );
  }

  return Response.json(buildThesisLogChunk(data, collection, chunkIndex));
}
