# Conditional reviews and app publication

The conditional views show the recorded forecast, requested model, provider-reported
identity where available, source reviews and revision history together. A successful
execution means that the response passed the contract checks. It does not mean the
reasoning passed source review or that a forecast is calibrated or causally identified.

The visual hierarchy keeps the existing lab shell and distribution chart. Model
identity and unresolved review findings appear before the chart. Revision history
compares recorded medians and central 80% intervals and links to each complete run;
review reports and feedback open inline. The model selector filters all stored
attempts before pagination. Share copies the current app URL. No domain taxonomy,
new model generation or numerical repair is involved.

## Reviews and revision history

Migration 009 adds two append-only indexes. Their content-addressed records live
in the same CAS as the original prompts and responses. `create_review` requires
the exact response artifact hash, a reviewer label, structured findings and the
original report. A finding can reference only source IDs in the frozen contract.
The assessment is explicitly operator-recorded, rather than independent attestation.

`link_revision` requires the same contract and evidence, a completed parent before
the child starts, a review of that parent and the exact feedback bytes in the
child's archived prompt. The association is retrospective: the index timestamp
describes when it was recorded, not proof that a review existed before the model
call. Neither endpoint changes the original forecast or creates HTTP write access.

For the existing Gemini operator adapter, provider metadata is derived from the
archived command and provider envelope. A single completed candidate must match
the exact recorded response bytes and parsed response before its model version,
response ID and token counts are displayed. `observed_model` remains null. This
verifies consistency of operator-recorded artifacts, not their independent origin.

## Public snapshot

`thesis_core.lab_publication.export_conditionals(store, attempt_ids, destination,
code_revision=...)` exports selected real read projections, closes over their
revision histories and verifies every reachable CAS artifact. It never enumerates
unrelated CAS contents or copies the operational database. The code revision is a
full Git commit naming the exporter/projection implementation. The export time is
an operator publication time, separate from original attempt and source times.

The committed public export lives under `site/lab-publication/`, outside the
workflow-owned `records/` namespace. Its manifest binds each projection and raw
artifact by SHA-256 and byte length. The source packet, original model outputs,
provider envelopes, prompts, code captures, review reports and revision feedback
remain downloadable. An export refuses missing/corrupt artifacts, inconsistent
lineage, oversized input or an existing destination; installation is atomic.

The app defaults to `THESIS_LAB_DATA_MODE=snapshot` at **build time**. To run the
operational app, set `THESIS_LAB_DATA_MODE=live` when starting development or
building, alongside the server-only `THESIS_CORE_API_URL`. Changing the mode of a
production build requires rebuilding. The Next configuration uses direct env
references in its reader so this default survives server bundling.

Snapshot mode uses the same conditional views and same-origin API routes. It
serves only conditionals and allowlisted artifacts from this publication; other
core routes return unavailable and never fall back to a private backend. The lab
navigation reflects that scope. Each page displays the publication date and
attempt count. Original forecast dates, execution states and review findings remain
unchanged. The older public forecast archive is still linked separately.

The server checks manifest bounds, projection hashes and wire contracts before
responding. Artifact downloads verify length and hash before returning any bytes,
use attachment disposition and `nosniff`, and expose no source filesystem paths.
JSON projection blobs cannot be downloaded through the raw artifact allowlist.

## Release and verification

Publish through the existing app's Git-integrated preview workflow. Do not link a
worktree to the production Vercel project or use a CLI production deployment.
Production remains governed by the normal reviewed Git release process.

Verification covers real PostgreSQL review/revision behavior, immutable source
bytes, revision closure, atomic export, browser contract validation, model filters
and pagination, publication integrity and allowlist failures. The built app must
also be checked with snapshot mode's default and a local live-mode development
server, including both real Gemini attempts and raw artifact downloads.
