# Packaged public TSA trust assets

Byte-for-byte copies of the immutable public trust assets under
`records/trust/`, shipped inside the distribution so
`thesis_core.tsa` can verify an RFC 3161 receipt without a records
checkout.  Each file's SHA-256 is checked against the verifier's code pins
(`thesis_core.record_chain.CODE_PINNED_TRUST_BUNDLES` and the
`rootCertificate` entries inside the bundles) before use, so a drifted copy
fails closed instead of widening trust.

These are copies, not the authority: `records/trust/` remains the published
location and is never modified from here.  Refresh a copy only when the
corresponding immutable `records/trust/` file is introduced, and never edit
one in place — trust bundles are versioned, never mutated.

`records/trust/producer-ed25519.pem` is deliberately absent: it authenticates
producer snapshot signatures against a records tree, which is outside the
standalone timestamp path.
