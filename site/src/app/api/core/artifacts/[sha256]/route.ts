import { handleArtifactProxyRequest } from "@/lib/artifact-proxy";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const fetchCache = "force-no-store";
export const revalidate = 0;
export async function GET(request: Request): Promise<Response> {
  return handleArtifactProxyRequest(request);
}
