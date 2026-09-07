"""Code-pinned policy for Thesis record-snapshot producer signatures."""

from __future__ import annotations

# ``receipt`` is pinned by exact version and artifact hash in this repository.
# Any receipt upgrade must pass this repository's full suite and producer-signing
# tests at the new pin before the dependency bump lands.
SIGNATURE_DOMAIN = b"thesis-record-snapshot/v1\0"
SIGNATURE_SUFFIX = ".producer.sig"
PUBLIC_KEY_RELPATH = "records/trust/producer-ed25519.pem"

# Armed by the 2026-07-21 trust-root ceremony (Max-authorized). The private
# key exists only as the BRIER_PRODUCER_SIGNING_KEY Actions secret; the public
# key landed via the attested record-forecasts publish_trust_key dispatch
# (commit e6aa9000, records provenance OK). Every snapshot strictly after the
# activation boundary must carry a valid .producer.sig sibling.
PRODUCER_SPKI_SHA256: str | None = (
    "b96f4556ebe77bf97a1b7421a131ff49bec68b450bb92591cdf4b135c8d21e30"
)
ACTIVATION_SNAPSHOT: str | None = (
    "records/2026-07-21/digest-29850168611-1.json"
)


def producer_signing_active() -> bool:
    """Return whether the producer-signing policy is consistently armed."""

    if PRODUCER_SPKI_SHA256 is None and ACTIVATION_SNAPSHOT is None:
        return False
    if PRODUCER_SPKI_SHA256 is not None and ACTIVATION_SNAPSHOT is not None:
        return True
    raise ValueError("producer signing pins are half-armed")
