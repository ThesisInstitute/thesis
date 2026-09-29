# Codex events for tool calls the recorder never answered

`refused_and_closed_calls.jsonl` holds four verbatim lines of `codex exec --json`
stdout, recorded on 2026-09-29 from the real Codex CLI binaries 0.144.0 (the
version CI installs) and 0.158.0. Both versions wrote byte-identical lines.

Each run drove the real `scripts/tool_evidence_mcp.py`, configured with the
runner's own `tool_evidence_mcp_config` overrides, from a local mock OpenAI
Responses API provider (`-c model_provider=mock` with a `model_providers.mock`
base URL on 127.0.0.1) that returned scripted function calls. Its SSE shape
follows `codex-rs/core/tests/common/responses.rs` at `rust-v0.144.0`.

- `item_129` is the 129th `calculate` call of one session. The recorder had
  already recorded `MAX_CALLS` (128) calls, so the server answered with JSON-RPC
  error -32602 and recorded nothing. Arguments over `MAX_ARGUMENT_BYTES` (32 KiB)
  get the same reply and the same event shape (that run's 40 KiB arguments are
  not kept here).
- `item_2` is a call made after the server exited. The previous call's request
  line exceeded 64 KiB, so `serve()` stopped. Codex reports `Transport closed`
  for the pending call and for every later one.

In each case Codex writes `status: "failed"`, `result: null` and
`error: {"message": ...}`. This matches `notify_mcp_tool_call_completed` in
`codex-rs/core/src/mcp_tool_call.rs` at `rust-v0.144.0`, which maps
`Err(message)` to `(Failed, None, Some(McpToolCallError { message }))`.
The message comes from `format!("tool call error: {e:?}")` in the same file,
wrapping the "tool call failed for {server}/{tool}" context added in
`codex-rs/codex-mcp/src/connection_manager.rs`.
