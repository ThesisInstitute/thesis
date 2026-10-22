"""Registered targets a recorded ruling voided: terminal, with their reasons.

A void is not a resolution. The forecast and its trace stay on the record
and the target never gets an outcome, so it is never scored. The resolver
never routes a voided reference (``pending_claims_refs`` and
``pending_adapter_refs`` skip it), and ``resolution_status.py`` reports it
as ``VOIDED`` with the ruling and the reason, in place of a refusal or a
missing route.

Each entry names the registration's ``targetContentHash``. A test requires it
to equal the hash on disk, so a void applies to exactly the contract the
ruling judged. Additions are reviewed commits that cite a ruling; nothing
lands here automatically.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VoidedTarget:
    target_content_hash: str
    ruling: str
    """The ruling that voided the target, as the decision record names it."""
    ruled_on: str
    reason: str
    """Why the registered contract cannot resolve as written: a fact about
    the contract or its source, checked by a test where the repository holds
    the evidence."""


_D1633 = "d1633"
_D1633_DAY = "2026-10-22"

_BEA_JUNE_FROZEN_VINTAGE = (
    "The registered source is the ALFRED vintage of 2026-06-25, a month "
    "before the release window the same registration names (2026-07-21 to "
    "2026-07-29), so it cannot hold the June 2026 first print."
)


def _no_custody(page: str, start: str, end: str) -> str:
    return (
        f"The registered page ({page}) has no Internet Archive capture dated "
        f"inside the registered release window ({start} to {end}, per the "
        "Archive's index read on 2026-10-22), so no record of the first print "
        "exists to resolve from."
    )


def _d1633(target_content_hash: str, reason: str) -> VoidedTarget:
    return VoidedTarget(target_content_hash, _D1633, _D1633_DAY, reason)


# Ruling d1633 (2026-10-22) resolves twelve legacy BLS cells from Archive
# captures and voids these thirteen generic-url cells: no custody record of
# the first print, or a contract that contradicts itself. Evidence, cell by
# cell: the d1633 record and thesis#355.
VOIDED_TARGETS: dict[str, VoidedTarget] = {
    "bea.disposable_personal_income.level.june_2026.first_print": _d1633(
        "123ce8782db84a3d7daf502c09b752d32f0756b451f512b2661b632666c8caf3",
        _BEA_JUNE_FROZEN_VINTAGE,
    ),
    "bea.government_social_benefits.level.june_2026.first_print": _d1633(
        "9ff32676acb57877e9b6c73c923544fceea7817cc4e300041781188cd157cc14",
        _BEA_JUNE_FROZEN_VINTAGE,
    ),
    "bea.government_social_benefits.medicaid.june_2026.first_print": _d1633(
        "62975454c04b5d6bf9b9c76239d4d6289d2ff47c42e835a321a73bc441c57acb",
        _BEA_JUNE_FROZEN_VINTAGE,
    ),
    "bea.government_social_benefits.medicare.june_2026.first_print": _d1633(
        "d9074bfce2314259e94b6212a4c40f3b45ecba5251b62858fc2cd2c4610df70e",
        _BEA_JUNE_FROZEN_VINTAGE,
    ),
    "bea.government_social_benefits.social_security.june_2026.first_print": _d1633(
        "71d5e19f498c3b8a7f2f80219ed03393c8f31b5957c6bbf65f107a42c96f6200",
        _BEA_JUNE_FROZEN_VINTAGE,
    ),
    "bea.pce.core_mom.june_2026.first_print": _d1633(
        "5839898680c429f390013595cf61531a7d62b72b9316886807d2aa9c05680b79",
        _BEA_JUNE_FROZEN_VINTAGE,
    ),
    "bea.pce_price_index.monthly_change.june_2026.first_print": _d1633(
        "3f121ef8159dd9e82324d35927f3da89eb6731dce7171364f190afb81d01f7ce",
        _BEA_JUNE_FROZEN_VINTAGE,
    ),
    "bea.personal_current_taxes.level.june_2026.first_print": _d1633(
        "d1c11d1dca6d4747e72624aa27b4adfe284e7962b4f1245f57fee44b2530ec36",
        _BEA_JUNE_FROZEN_VINTAGE,
    ),
    "ssa.ssi.total_recipients.2026-08.first_print": _d1633(
        "9e48da0da68cd2dfb368416d94e9714b1c294f8fcbee6ed27a1720e493ef0300",
        "The registered source is SSA's July 2026 table "
        "(ssi_monthly/2026-07/table02.html), so it cannot hold the August "
        "2026 figure this forecast names.",
    ),
    "bls.real_earnings.avg_hourly_mom.2026-07.first_print": _d1633(
        "8662209989befa5925d38419a847521e7a1076b91048aef177ca79c7544f4334",
        _no_custody("realer.t01.htm", "2026-08-10", "2026-08-18"),
    ),
    "bls.real_earnings.avg_hourly_mom.2026-08.first_print": _d1633(
        "d131156b732a5d2eeed80a873f599d8c0a54453f2c8eb3c2ce0d53822486ba73",
        _no_custody("realer.t01.htm", "2026-09-08", "2026-09-16"),
    ),
    "bls.cps.telework_share.2026-08.first_print": _d1633(
        "6cf0d9882448a529f400c8923c7c59cd04582d25bc948a6c7238eb38f11374f5",
        _no_custody("cpseea41.htm", "2026-09-03", "2026-09-11"),
    ),
    "bls.cps.telework_share.2026-09.first_print": _d1633(
        "0bc190e7fe95e2a7812ba70143f1394069f3cc59c61671e6021c2283181fc418",
        "On 2026-10-16 an agent building the resolver opened the live "
        "registered page, which showed this figure, before any resolution "
        "rule was committed, so the rule cannot be shown to have been set "
        "without sight of the figure.",
    ),
}
