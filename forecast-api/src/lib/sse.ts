import { corsHeaders } from "@/lib/cors";

export type SendEvent = (event: string, data: unknown) => void;

export function createSseResponse(
  request: Request,
  run: (send: SendEvent) => Promise<void>,
) {
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      const send: SendEvent = (event, data) => {
        controller.enqueue(
          encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`),
        );
      };

      try {
        await run(send);
      } catch (error) {
        send("failure", {
          message:
            error instanceof Error ? error.message : "Forecast stream failed.",
        });
        send("done", { ok: false });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      ...corsHeaders(request),
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}

export function pause(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}
