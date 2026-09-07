# Thesis core review status

Fable approved the implementation plan through Subfleet on September 4, 2026.
The main agent approved the same exact revision. Implementation began after agreement.

- Approved SHA-256: `3b566fa29473c1fc7119ec85380717fa7c0e53a1c0d6999c9692eba5d5954519`
- Gate: `20260904-183206-plan-34cfc839`
- Served model: `claude-fable-5-1`
- Result: approve, no actionable plan findings

The [plan](thesis-core-plan.md) retains its reviewed bytes, including its original
proposed-status header. This document records the later approval. The
[verdict](thesis-core-plan-verdict.json) and [responses](thesis-core-plan-review-response.md)
preserve the review history. The earlier gate reached its configured round limit;
the successor required fresh agreement on the revised plan before proceeding.

The first implementation is complete on `thesis-core-20260904`. Independent
code reviews found and resolved publication-input, queue-wiring, concurrent
resolution and ambiguous-outcome validation defects. The local acceptance path
uses real PostgreSQL, official source data, an actual model invocation and real
timestamp receipts. See the [verification report](thesis-core-verification.md)
for completed checks and limitations, and the [runbook](thesis-core-runbook.md)
for reproducible commands.

The branch has not been deployed. Production provisioning, historical migration
and publisher cutover remain outside this branch's scope. Verified receipts
without an accuracy bound remain unordered and cannot qualify a prospective rank.

Fable subsequently reviewed the code in PR #228 at
`025da734a7a3fa0a475c69aee22f2993ca1c76b3` through four Subfleet passes. The
execution/security pass requested changes; independent local reproductions
confirmed the substantive findings and rejected two scientific false positives.
The [PR review response](thesis-core-pr-review-response.md) records the fixes,
regression coverage and remaining deployment considerations.
