# TSA trust bundle rotation

The record chain (`scripts/verify_record_chain.py`) accepts an RFC 3161 token
only from a responder named in a trust bundle, `records/trust/tsa-anchors-vN.json`.
A bundle is immutable. When a timestamp authority replaces its responder
certificate, or when the chain adds or drops an authority, the chain moves to a
new bundle. This page is the procedure.

`docs/tsa-signer-rotation.md` covers the other pin surface, the ledger release
chain. The two are separate: a change to one does nothing for the other.

## How a rotation presents

One available anchor is enough for a snapshot to count as witnessed, so a
responder rotation never fails the recorder. The marker's top-level `status`
stays `available`. What changes is one entry in `anchorOutcomes`:

```sh
jq '{status, trustBundleId, anchorOutcomes: [.anchorOutcomes[] | {tsaAnchorId, status, reason}]}' \
  records/YYYY-MM-DD/digest-RUN.witness.json
```

```
"status": "unavailable",
"reason": "pinned timestamp verification failed: RFC 3161 token signer is not
           pinned for TSA anchor 'digicert-trusted-root-g4': {...}"
```

The reason carries the certificate hash, SPKI hash, serial and subject of the
responder that signed. The verifier reaches that message only after
`openssl cms -verify` has accepted the token against the pinned root with
`-purpose timestampsign`, so the certificate already chains to the root the
bundle trusts. What is missing is the review.

The step "Report degraded witnessing" in `.github/workflows/record-forecasts.yml`
runs `scripts/witness_health.py` after every recorder push. It opens one issue
titled "Record witness degraded" while any anchor is unavailable and closes it
on the first run where every anchor witnesses. The same issue reports a
snapshot that no anchor witnessed, and a pending bundle's new anchor that was
asked for a token and did not produce a verified one. DigiCert moved
`timestamp.digicert.com` to a new responder between the 2026-09-03 and
2026-09-04 recorder runs. Before this step existed, nothing reported it, and
the records carried one token instead of two until `tsa-anchors-v3`.

## Rotation or outage

Read the reason before acting.

- `token signer is not pinned`: the TSA answered with a valid token from a
  responder the bundle does not name. This is a rotation. It repeats on every
  run until a new bundle is active.
- `timestamp request failed: ...`: the request did not complete. Check the
  endpoint by hand with the probe below. A single failure needs no action. The
  next run asks again.
- Any other verification failure (policy OID, message imprint, certificate
  chain, time): do not pin anything. Get a receipt by hand and find out what
  changed first.

## Derive the responder identity yourself

Do not copy hashes from a marker or a failed run into the code. Get a fresh
receipt and let OpenSSL name the signer it verified against the pinned root.
The order of certificates inside a token is not evidence of which one signed.

```sh
repo="$(git rev-parse --show-toplevel)"
work="$(mktemp -d)" && cd "$work" && mkdir empty-ca
printf 'tsa bundle probe %s' "$(date -u +%FT%TZ)" > probe.txt
OPENSSL_CONF=/dev/null openssl ts -query -data probe.txt -sha256 -cert -out probe.tsq
curl -sS -m 60 -H 'Content-Type: application/timestamp-query' \
  --data-binary @probe.tsq http://timestamp.digicert.com -o probe.tsr
openssl ts -reply -config /dev/null -in probe.tsr -token_out -out token.der
# Verify against the pinned root only: no system store, no CA beside the token.
OPENSSL_CONF=/dev/null SSL_CERT_DIR="$work/empty-ca" SSL_CERT_FILE=/dev/null \
  openssl cms -verify -inform DER -in token.der \
  -CAfile "$repo/records/trust/digicert-trusted-root-g4.pem" \
  -no-CApath -no-CAstore -purpose timestampsign \
  -signer signer.pem -out tst.der
openssl x509 -in signer.pem -noout -subject -issuer -serial -dates \
  -ext extendedKeyUsage,keyUsage,basicConstraints
cd "$repo" && python3 - "$work/signer.pem" <<'EOF'
import json, sys
sys.path.insert(0, "scripts")
import verify_record_chain as rc
from pathlib import Path
print(json.dumps(rc._certificate_identity(Path(sys.argv[1])), indent=2))
EOF
```

For FreeTSA use `https://freetsa.org/tsr` and
`records/trust/freetsa-root-2016.pem`.

The last command prints the identity in the exact form a bundle stores it
(`certificateSha256`, `spkiSha256`, `serial`, `subject`). The verifier compares
the whole object, not only the SPKI hash, so use this output as it is.

Pin the responder only if all of these hold:

1. `openssl cms -verify` succeeded against the root file already in
   `records/trust/`. A new root is a different and larger decision.
2. The identity equals the one in the markers' `reason`.
3. The subject names the TSA's timestamp responder. Extended key usage is
   `Time Stamping`, marked critical, and `CA:FALSE`.
4. `notBefore` is earlier than the first marker that refused the responder.
5. The TSA's own repository or release notes are consistent with a rotation,
   where they publish one.

## What the new bundle contains

Copy the newest bundle, set `bundleId` to the next version, and change only
what the decision covers. For a responder rotation that is one anchor's
`allowedSigners`.

Leave the retired responder out. Replay verifies a marker's tokens under the
bundle the marker names, and a marker must name the newest bundle that was
active at that point of the chain. Tokens from the retired responder therefore
keep verifying under the old bundle for ever, and no witness made after the new
bundle activates can be signed by a retired key. Listing both responders would
only widen what the chain accepts from then on.

Write the file as canonical JSON with the same trailing newline as the earlier
bundles. The verifier accepts canonical JSON with or without that newline and
nothing else. The exact bytes are then fixed by the `sha256` and `size` in the
code pin.

Run this from the repository root with
`uv run --locked --extra custody python`.

```python
import copy, hashlib, json, sys
sys.path.insert(0, "scripts")
from pathlib import Path
from canonical_json import canonical_bytes, canonical_sha256
import verify_record_chain as rc

# Until the recorder publishes a bundle it exists only as the staged copy.
published = Path("records/trust/tsa-anchors-v3.json")
staged = Path("scripts/staged_trust_bundles/tsa-anchors-v3.json")
old = json.loads((published if published.is_file() else staged).read_text())
new = copy.deepcopy(old)
new["bundleId"] = "tsa-anchors-v4"
anchor = next(a for a in new["anchors"] if a["id"] == "digicert-trusted-root-g4")
anchor["allowedSigners"] = [rc._certificate_identity(Path("<work>/signer.pem"))]
out = Path("scripts/staged_trust_bundles/tsa-anchors-v4.json")
out.write_bytes(canonical_bytes(new) + b"\n")
raw = out.read_bytes()
print(json.dumps({
    "bundleId": new["bundleId"],
    "path": "records/trust/tsa-anchors-v4.json",
    "sha256": hashlib.sha256(raw).hexdigest(),
    "size": len(raw),
    "canonicalJsonSha256": canonical_sha256(new),
}, indent=2))
```

## The pull request

`records/**` belongs to the allowlisted workflows, so the pull request never
writes `records/trust/`. It carries:

1. The bundle bytes in `scripts/staged_trust_bundles/`.
2. The printed reference as a new entry in `CODE_PINNED_TRUST_BUNDLES`.
3. A new entry in `CODE_PINNED_TSA_IDENTITIES` with each anchor's root SPKI and
   its set of signer SPKIs. The verifier requires this set to equal the
   bundle's `allowedSigners`, so the two must agree.
4. A real token from the new responder as a test fixture, and tests in the
   style of `tests/test_tsa_anchors_v3.py`: the staged bytes equal the pin, the
   bundle differs from its predecessor only where intended, a real token from
   the new responder verifies under the new bundle and is refused under the
   old one, and a real token from the retired responder in `records/` verifies
   under the old bundle and is refused under the new one.

A pin change is a trust decision. Get an independent review before opening the
pull request, and do not merge your own.

That review is the only gate. The publishing step below is unconditional on
purpose: once a pull request that changes the code pin and the staged bytes is
merged, the next recorder run publishes the bundle under a workflow
attestation, with no dispatch input and no second party. The step cannot
publish bytes that differ from the merged pin, but it cannot tell a reviewed
merge from an unreviewed one. `AGENTS.md` names required review or CODEOWNERS
on the workflows and provenance scripts as the containment for this class and
as a repository-settings decision. `scripts/verify_record_chain.py`,
`scripts/publish_trust_bundles.py` and `scripts/staged_trust_bundles/` belong
in that set. Until the repository has it, treat a merge that touches them as
the ceremony.

## How the bundle reaches the chain

Nothing else is needed after the merge. The next recorder run does this, in
one attested push:

1. "Publish code-approved TSA trust bundles" runs
   `scripts/publish_trust_bundles.py`. It copies a staged bundle into
   `records/trust/` only when its hash and size equal the code pin. It never
   rewrites a published bundle, and it refuses a staged file that code does not
   pin. Publishing grants no authority.
2. The recorder mints the snapshot. Because the bundle is code-pinned and the
   chain has not seen it, the snapshot names it in `trustBundleUpdates`. The
   recorder stops before writing anything if the file is not published.
3. `scripts/witness_snapshot.py` witnesses that snapshot under the bundle that
   is already active. This is the transition snapshot. For a responder
   rotation the rotated anchor is still `unavailable` here, and the other
   anchor authorizes the transition alone.
4. On replay, the first available witness made under an active bundle
   activates every pending bundle. From the next snapshot on, markers must
   name the new bundle, and both anchors witness again. The "Record witness
   degraded" issue closes on that run.

If every anchor of the active bundle fails on the transition snapshot, its
marker is `unavailable` and the bundle stays pending. The next snapshot with an
available witness under the old bundle activates it. No snapshot can authorize
the bundle its own token is verified under.

A rotation transition therefore carries no proof in the chain that the new pin
admits the token the TSA serves today. The proof is outside it: the real-token
test in the pull request, which verifies a receipt fetched from the live
endpoint under the new bundle and refuses it under the old one, and then the
second recorder run. If the pin is wrong, the new bundle still activates, its rotated anchor never witnesses,
the "Record witness degraded" issue stays open, and the repair is another
bundle.

A bundle that adds an authority differs in step 3. An anchor ID that no active
bundle contains is asked for a token too, and the marker records the result
under `supplementalOutcomes` with role `pending_trust_bundle`. A supplemental
token is verified but never makes a snapshot witnessed. A rotation of an anchor
that is already active has no supplemental outcomes, and the verifier rejects a
marker that lists one.

## After the merge

Check the two recorder runs that follow.

```sh
git pull && uv run --locked --extra custody python scripts/verify_record_chain.py records
```

Use the `uv` form. Producer signing is active, so a bare `python3` without the
`custody` extra stops with "CHAIN BROKEN: producer signing is active but the
receipt package is not installed". That message is about the local
environment, not the chain.

- First run: `records/trust/tsa-anchors-vN.json` exists and is byte-identical
  to the staged copy. The snapshot lists the bundle in `trustBundleUpdates`.
  Its marker names the old bundle. The verifier prints the new bundle among
  the active ones.
- Second run: the marker names the new bundle and every anchor is `available`.
  If the rotated anchor is still `unavailable` here, the new pin is wrong.

The staged copy stays in the repository so a fresh clone can compare it with
the published file.
