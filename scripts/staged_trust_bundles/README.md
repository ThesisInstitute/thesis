# Staged TSA trust bundles

Each file here is the exact byte content of a `records/trust/tsa-anchors-vN.json`
bundle that verifier code has approved
(`CODE_PINNED_TRUST_BUNDLES` in `scripts/verify_record_chain.py`).

Only allowlisted workflows write `records/**`, so a pull request cannot add a
bundle there. It adds the bytes here and pins their hash in code. The step
"Publish code-approved TSA trust bundles" in
`.github/workflows/record-forecasts.yml` runs `scripts/publish_trust_bundles.py`,
which copies a staged bundle into `records/trust/` only when its hash and size
equal the code pin. The same recorder run names the bundle in its snapshot's
`trustBundleUpdates`.

A staged file has no authority of its own. The verifier reads bundles only from
`records/trust/`, and replay activates one only after a witness made under an
already active bundle covers the snapshot that introduces it.

`scripts/publish_trust_bundles.py` refuses any file here, other than this
README, that verifier code does not pin. Once a bundle is published the staged
copy stays, byte-identical, so a fresh clone can check one against the other.

See `docs/tsa-trust-bundle-rotation.md` for the full procedure.
