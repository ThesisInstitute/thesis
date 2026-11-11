# Challenge-signing test fixtures

- `records-push-cd6fb721.dsse.sigstore.json` — this repository's own
  records-push attestation bundle for commit cd6fb721, fetched verbatim
  from the GitHub attestation store on 2026-07-31. Real Fulcio
  certificate (the record-forecasts workflow identity) and real
  transparency-log entry; its Rekor entry UUID was cross-checked against
  the live Rekor API the same day.
- `bundle_v3.txt`, `bundle_v3.txt.sigstore`,
  `bundle_v3_no_signed_time.txt`,
  `bundle_v3_no_signed_time.txt.sigstore.json` — vendored unmodified from
  [sigstore/sigstore-python](https://github.com/sigstore/sigstore-python)
  v4.5.0 `test/assets/` (Apache-2.0; license text in
  `LICENSE-Apache-2.0`). Staging-signed; verified in tests
  with `Verifier.staging(offline=True)`, the same offline pattern
  sigstore's own suite uses, so no network or OIDC flow is needed.
