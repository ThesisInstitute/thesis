import { handleCoreProxyRequest } from "@/lib/core-proxy";

/**
 * Same-origin read proxy for the Thesis core API.
 *
 * The catch-all segment is validated inside `handleCoreProxyRequest` against a
 * fixed allowlist; the browser picks an endpoint name, never a destination.
 * Dynamic rendering and the Node runtime are required: the upstream base URL
 * is a server-only secret read per request, and the body cap streams bytes.
 */
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const fetchCache = "force-no-store";
export const revalidate = 0;

export async function GET(request: Request): Promise<Response> {
  return handleCoreProxyRequest(request);
}
