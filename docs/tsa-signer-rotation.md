# TSA signer rotation

The ledger release chain (`scripts/ledger_release_chain.py`) timestamps every
release manifest with two independent RFC 3161 authorities, FreeTSA and
DigiCert. For each one the verifier pins the root certificate's bytes, the
timestamping policy OID, and the responder certificates it will accept
(`ANCHORS[...].signers`, a tuple of `PinnedSigner` entries). A receipt passes
only if its certificate hash and SPKI hash both equal the same entry.

A TSA replaces its responder certificate about once a year. When it does, the
resolver mints a receipt the verifier refuses, and `resolve-and-rebuild.yml`
fails before appending anything. Nothing resolves until the new responder is
reviewed and pinned.

## How it presents

The step "Resolve pending cells against official prints" fails with:

```
ledger_release_chain.ReleaseChainError: RFC 3161 signer certificate is not
pinned for 0021-<digest>.digicert.tsr: <certificate sha256> (SPKI <spki
sha256>; subject=CN=...). If the TSA replaced its responder certificate,
follow docs/tsa-signer-rotation.md
```

This happened from 2026-09-09 to 2026-09-18, ten daily runs in a row, when
DigiCert moved `timestamp.digicert.com` to "DigiCert SHA256 RSA4096 Timestamp
Responder 2026 1". Releases 0000 to 0020 carry the previous responder.

The message appears only after `openssl cms -verify` has accepted the token
against the pinned root, with `-purpose timestampsign`, at the receipt's own
signed time. So the certificate in the message already chains to the pinned
root and was valid when it signed. What is missing is the review.

## Check the certificate before pinning it

Do not copy hashes from a failed run into the code. Get a receipt yourself and
confirm it carries the same certificate.

```sh
work="$(mktemp -d)" && cd "$work"
printf 'tsa pin probe %s' "$(date -u +%F)" > probe.txt
openssl ts -query -data probe.txt -sha256 -cert -no_nonce -out probe.tsq
curl -sS -H 'Content-Type: application/timestamp-query' \
  --data-binary @probe.tsq http://timestamp.digicert.com -o probe.tsr
openssl ts -reply -config /dev/null -in probe.tsr -token_out -out token.der
openssl pkcs7 -inform DER -in token.der -print_certs -out chain.pem
# First certificate in chain.pem is the responder.
awk '/BEGIN/{f=1} f{print} /END/{exit}' chain.pem > signer.pem
openssl x509 -in signer.pem -noout -subject -issuer -serial -dates \
  -ext extendedKeyUsage
openssl x509 -in signer.pem -outform DER | shasum -a 256          # certificate
openssl x509 -in signer.pem -pubkey -noout \
  | openssl pkey -pubin -outform DER | shasum -a 256               # SPKI
```

For FreeTSA use `https://freetsa.org/tsr`.

Pin the certificate only if all of these hold:

1. The certificate hash equals the one in the failing run's message.
2. The subject names the TSA's timestamp responder, and the issuer chain ends
   at the root already pinned for that slot. A new root is a different and
   larger decision: it changes `filename` and `pem_sha256`, and the anchor
   file in the ledger repository's `releases/anchors/`.
3. Extended key usage is `Time Stamping`, marked critical.
4. `notBefore` is earlier than the first refused receipt.
5. The TSA's own repository or release notes are consistent with a rotation,
   where they publish one.

## Make the change

1. Append a `PinnedSigner` to the slot in `ANCHORS`. Keep every earlier
   entry: releases already in the journal are signed by them, and removing one
   makes the whole journal unverifiable. Record the subject, serial, validity
   and the date you fetched the receipt in the comment above the entry.
2. Update `test_digicert_keeps_the_responder_that_signed_the_existing_journal`
   (or the FreeTSA equivalent) in `tests/test_tsa_signer_pins.py`.
3. Verify against real data. With a checkout of the ledger branch
   (`PolicyEngine/chronicle`, `codex/thesis-ledger-facts`):

   ```python
   import hashlib, pathlib, sys
   sys.path.insert(0, "scripts")
   import ledger_release_chain as chain
   ledger = pathlib.Path("<ledger checkout>")
   chain.verify_release_chain(ledger)          # every existing release
   chain.verify_receipt(                        # the new responder
       hashlib.sha256(pathlib.Path("probe.txt").read_bytes()).hexdigest(),
       pathlib.Path("probe.tsr"), "digicert",
       anchor_dir=ledger / "releases" / "anchors",
       enforce_production_pins=True)
   ```

   Both must pass. Then remove your new entry locally and confirm the second
   call fails again; that shows the entry, not something else, is what admits
   the receipt.
4. Open a pull request. A pin change is a trust decision and is reviewed as
   one.

## The second pin surface: the record chain

`scripts/verify_record_chain.py` pins responder identities a second time, per
trust bundle: `CODE_PINNED_TSA_IDENTITIES` in code, mirrored by
`allowedSigners` in `records/trust/tsa-anchors-v*.json`.
`scripts/witness_snapshot.py` asks every TSA in the newest active bundle to
timestamp each record digest, and a token whose signer is not in the bundle
is recorded as `unavailable` for that anchor. One available anchor is enough
for the snapshot to count as witnessed, so a rotation does not stop the
recorder. It does quietly halve the witnessing.

`tsa-anchors-v2` lists only DigiCert's previous responder. Every marker
witnessed under v2 from 2026-09-04 onward (for example
`records/2026-09-18/digest-35372147258-1.witness.json`) has the DigiCert
anchor `unavailable` with reason "RFC 3161 token signer is not pinned", naming
the same certificate, SPKI and serial as the 2026 responder above. Markers up
to 2026-09-03 carry DigiCert tokens from the previous responder. The records
therefore date the rotation to between those two days, independently of the
resolver's failures.

Restoring two-TSA witnessing means a new bundle, and `tsa-anchors-v3` is that
bundle for this rotation. `docs/tsa-trust-bundle-rotation.md` is the procedure:
approve the bundle in verifier code, stage its bytes, and let the recorder
workflow publish it and introduce it with a snapshot witnessed under the bundle
that is already active. The recorder also keeps an issue open while any anchor
is unavailable, so the next rotation is reported by the first recorder run
after it happens.
Pinning a responder in `ledger_release_chain.py` does not do any of this.
