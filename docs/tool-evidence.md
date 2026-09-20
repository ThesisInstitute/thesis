# Captured tool evidence

Native Codex analyst runs configure the repository-owned
`thesis_tool_evidence` MCP server. It records actual tool requests and results,
including complete fetched response bodies, independently of the model's written
reasoning. Each draft, review, and final stage has its own call sequence.

The first version offers three tools:

- `fetch_source(url)` fetches an unauthenticated public HTTPS URL. The recorder
  retains the complete body as base64, SHA-256, byte count, response metadata,
  and the exact request URL. Its response to the model includes a bounded
  excerpt and the call ID. Oversized responses fail rather than silently
  becoming complete-looking truncated records. Redirects are refused; fetch
  the destination explicitly. Private addresses, URL credentials, and
  credential query parameters are refused. TLS authenticates the requested
  host during capture; this is a recorder's observation, not a publisher's
  cryptographic signature over its content.
- `extract_json(sourceCallId, pointer)` reads an RFC 6901 JSON Pointer from a
  captured response. Verification re-extracts the value from the preserved
  bytes. CSV, HTML, and PDF bodies can be preserved, but this version does not
  claim to replay extraction from those formats.
- `calculate(expression, inputs)` evaluates restricted arithmetic. Named inputs
  may be supplied numbers or numeric arrays, or refer to prior
  extraction/calculation call IDs. Referenced numeric strings are converted
  using strict JSON-number syntax; `resolvedInputs` records the converted
  values. `mean`, `median`, sample `stdev`, and successive `diff` support
  reproducible history and interval calculations.
  Verification evaluates the same expression again. This is not an arbitrary
  Python execution environment. Supplied inputs, including judgment
  adjustments, remain declarations even when arithmetic reproduces exactly.

Call IDs are stage-local. `draft_` call-0001 and final-stage call-0001 are
different calls. Dependencies must refer to successful earlier calls in the
same stage. A revised run may explain reliance on draft evidence; it must not
forge a new final-stage fetch for that evidence.

## Artifacts and verification

Each instrumented stage contributes two artifacts:

- `[prefix]tool_evidence.json` (`tool_evidence`) contains the
  `thesis_tool_evidence_v1` record, with capture method
  `thesis-controlled-tools-v1` and all terminal calls, including failures.
- `[prefix]tool_evidence_verification.json` (`tool_evidence_verification`)
  contains the offline replay verdict and SHA-256 of the exact evidence bytes.
  Its per-call checks distinguish captured response integrity, replayed
  extraction/calculation, and failed tools.

The recorder uses a private temporary directory outside the checkout. Once the
agent stage ends, the runner reads and verifies the evidence, archives both
files, and includes them in the normal manifest, complete custody inventory,
and activity log. `command.json` explicitly names both artifacts. Corrupt or
missing capture makes the stage fail; an empty valid capture means no tools
were recorded, not that the forecast's evidence was verified.

Rejected source URLs use a fixed redaction marker. Event matching applies the
same deterministic argument projection, so a rejected HTTP URL followed by a
successful HTTPS retry remains auditable. The runner separately redacts URL
credentials from native logs before sealing them; evidence sanitization alone
would not remove a secret from the model platform's original event stream.

When the stage ends, the runner also binds every recorded call to exactly one
native MCP completion event in the redacted stream it archives; a stage whose
stream does not account for a recorded call fails as one run instead of
blocking a whole docket publication. `scripts/verify_custody.py` recomputes
the report and repeats that binding from the archived stream, using the same
function, so the publication claim does not depend on the runner. The attested publisher also checks
the exact repository-owned server configuration. Changing a body, call result,
dependency, replay verdict, or artifact reference fails verification. A failed
stage may preserve an incomplete event stream without being promoted as a
successful run.

For a standalone evidence artifact:

```bash
uv run python scripts/tool_evidence.py --verify /path/to/tool_evidence.json
```

For a complete analyst run:

```bash
uv run python scripts/verify_custody.py /path/to/run
```

These artifacts feed Thesis's existing publication custody and Receipt-backed
snapshot signatures. This adds no signing keys to an agent process, no second
receipt protocol, and no new cryptographic dependency. Locally produced files
are not independently signed simply because they use this schema; publication
signatures and witnesses belong to the existing trusted workflow.

## Public report and limits

The report's Tool evidence section reads only artifact-backed records. It
shows captured requests/results, source hashes, calculation expressions and
inputs, and the runner's replay checks. The site verifies artifact integrity;
it does not claim to have independently rerun Python or contacted the original
website. The original model-authored tool blocks remain labeled Reported tool
use. Historical archives without these artifacts remain explicitly uncaptured.

Hosted web search, shell commands, custom `--command` agents, saved responses,
and mock cells do not automatically gain receipts. No-search/no-network native
stages, including the default reviewer, cannot use the source-fetch tool.

The capture process and agent share a host and user account. A compromised
operator or unrestricted process could fabricate a consistent prepublication
record. The temporary directory is outside the checkout, not an independent
security principal. Receipt protects published artifact custody and identity;
it does not prove model authorship, source truth, completeness of all tool
activity, or correctness of judgment. Stronger execution claims require an
isolated trusted recorder or externally attested execution environment.
