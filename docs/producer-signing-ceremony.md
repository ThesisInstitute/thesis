# Producer-signing ceremony

Producer signing is armed: `scripts/producer_signing_pins.py` sets both
activation constants, with the activation boundary at
`records/2026-07-21/digest-29850168611-1.json`. This page records the ceremony
that armed it. Neither constant changes outside this path: every prerequisite
below must be on `main` and the change must have an allowlisted, attested
publication path (see Rotation).

## Before the ceremony

- Give every workflow process that calls `verify_record_chain.py` Python 3.11+
  and the locked `custody` extra. This includes the recorder *before* it creates
  a snapshot, the wave-reproducibility job, and the prospect, roll, and strategy
  dockets. An active verifier deliberately refuses if `receipt` is absent.
- Provide a reviewed publisher path whose push is attested by an allowlisted
  workflow. Provided: the `publish_trust_key` input on the record-forecasts
  dispatch writes the key from the `BRIER_PRODUCER_PUBLIC_KEY_PEM` repository
  variable into the run's attested records push. The public key lives under `records/trust/`, so adding it in an
  ordinary local or PR-merge records commit would fail records provenance.
- Confirm that `records/CHAIN_HEAD.json` names the current reachable chain
  head and that the full suite is green at the locked `receipt==0.6.0` pin.

## Generate and pin the key

On a trusted workstation, generate the Ed25519 keypair locally and send the
private PEM directly to the Actions secret over standard input. The generator
makes no network call; only `gh secret set` transports the secret to GitHub.
This command writes only the public PEM to the checkout and does not print
either key:

```bash
uv run --locked --extra custody python -c 'from pathlib import Path; import subprocess; from receipt.sign import generate_signing_keypair; private_pem, public_pem = generate_signing_keypair(); subprocess.run(["gh", "secret", "set", "BRIER_PRODUCER_SIGNING_KEY", "--repo", "ThesisInstitute/thesis"], input=private_pem, check=True); Path("records/trust/producer-ed25519.pem").write_bytes(public_pem)'
```

The private key must exist only as the
`BRIER_PRODUCER_SIGNING_KEY` Actions secret: never in a file, commit, shell
argument, log, or artifact.

Compute the public-key SPKI pin from the locked package:

```bash
uv run --locked --extra custody python -c 'from pathlib import Path; from receipt.sign import spki_sha256; print(spki_sha256(Path("records/trust/producer-ed25519.pem").read_bytes()))'
```

Read the exact activation boundary:

```bash
python -c 'import json; print(json.load(open("records/CHAIN_HEAD.json"))["snapshotPath"])'
```

Publish one reviewed, workflow-attested activation commit that:

1. adds `records/trust/producer-ed25519.pem`;
2. sets `PRODUCER_SPKI_SHA256` in `scripts/producer_signing_pins.py` to the
   printed SPKI digest; and
3. sets `ACTIVATION_SNAPSHOT` to the printed logical snapshot path.

The activation snapshot itself remains unsigned. Every snapshot strictly
after it must have a 64-byte `.producer.sig` sibling. Before publication, run:

```bash
uv run --locked --extra custody python scripts/verify_record_chain.py records
uv run --locked --extra custody --extra dev pytest -q
```

## Rotation

Rotation is a new human-reviewed trust-root ceremony, never an unreviewed
Actions-secret replacement. The v1 policy records one key epoch, so an
in-place pin replacement would invalidate signed history. Before rotating,
land a reviewed verifier migration that preserves the old epoch and introduces
the new pins and boundary; then use the same attested ceremony path. The new
private key again exists only in the Actions secret.
