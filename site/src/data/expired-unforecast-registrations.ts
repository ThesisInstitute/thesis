/**
 * Registrations that expired without a forecast — a terminal, explicit
 * record, never a silent exemption.
 *
 * A preregistered target gets TARGET_PREREGISTRATION_ORPHAN_GRACE_DAYS to
 * receive its forecast. When generation failed and the release window
 * passed, forecasting it afterward would fabricate chronology, so the
 * registration ends here instead: enumerated by exact dataPointId,
 * surfaced on the calibration page, and enforced exact by tests — every
 * listed id must truly be registered, unforecast, and out of grace, and an
 * id that ever gains a forecast must be removed. Additions to this list
 * are reviewed commits; nothing lands here automatically.
 */
export const EXPIRED_UNFORECAST_REGISTRATIONS = [
  // 2026-07-10 roll registrations whose generation leg failed before the
  // step-shape and publication fixes landed; their June 2026 first prints
  // (Statcan LFS July 10, ONS retail sales July 18) arrived unforecast.
  "ons.retail_sales.volume_mom.june_2026.first_print",
  "statcan.lfs.employment_change.canada.june_2026.first_print",
  "statcan.lfs.unemployment_rate.canada.june_2026.first_print",
  // 2026-07-22 prospect registrations (commit e6214345) whose analyst leg
  // never produced a cell. The BEA first print (July 29) has passed. The
  // JOLTS (Aug 3) and ONS vacancies (Aug 18) prints have not, but these end
  // here for the same reason: each registration pins ledger 02b1747916 and
  // an information set from July 22, and the docket no longer rolls them —
  // bls.jolts.job_openings_total, bea.wages_and_salaries.level, and
  // ons.vacancies.total_3m_sa are not the registry series/slugs the roll
  // advances. Forecasting them now would record a run against a ten-day
  // stale pin, which is the chronology the grace window exists to protect.
  "bea.wages_and_salaries.level.june_2026.first_print",
  "bls.jolts.job_openings_total.june_2026.first_print",
  "ons.vacancies.total_3m_sa.2026_06.first_print",
  // The 2026-07-29 UK PPI registration crossed its seven-day orphan grace
  // without a forecast. Its August 19 first print remains in the future, but
  // generating against the stale registration now would violate the same
  // chronology guarantee, so the registration terminates explicitly here.
  "ons.ppi.output_all_manufactured_yoy.2026_07.first_print",
  // The 2026-07-31 hackathon-day MTIS May and CES June seeds crossed the
  // seven-day orphan grace on 2026-08-07 without a forecast. Both first
  // prints are already public, so forecasting them now would be hindsight.
  "census.mtis.total_business_inventories_level.may_2026.first_print",
  "bls.ces.average_hourly_earnings_private.june_2026.first_print",
  // The ECI Q3 seed from that wave did terminate on the record, but the
  // 2026-08-14 auto-roll accidentally re-registered the same dataPointId
  // before the seed guard existed. That fresh registration is now the live
  // record, so the id no longer satisfies this list's own contract of being
  // genuinely unforecast and out of grace and is not an active entry here.
  // Ordinary rolls now refuse both terminal ids and ids with an existing
  // immutable registration. If the fresh registration lapses through grace
  // unforecast, a new terminal entry will be added.
  // That happened: the 2026-08-14T17:27Z re-registration crossed the
  // seven-day orphan grace on 2026-08-21 unforecast. Not ungenerated:
  // its registering roll (run 31824000315) generated a candidate cell,
  // but the publish leg failed the site suite on this list's own
  // exactness contract — the id was still a terminal entry from the
  // seed's 08-07 termination, and a terminal id gaining a forecast is
  // precisely what the contract refuses — so no cell or batch manifest
  // reached main, and the in-grace retry lane's committed-manifest
  // trust anchor could never reach the target (the 2026-08-05 AWE/PPI
  // failure mode below). Its October 30 first print is still in the future,
  // but forecasting it now would record a run against the nine-day-stale
  // 2026-08-14 pin — the same chronology violation the JOLTS and vacancies
  // entries above terminate on — so the accidental re-registration ends
  // here (added 2026-08-23, alongside the aging/disability resolver batch,
  // when the lapse surfaced as the first non-skip CI run since 08-18).
  "bls.eci.total_compensation_private_industry_qoq.2026_q3.first_print",
  // The 2026-08-03 Farm Bill CRP conditional-pair registrations
  // (ticket …7916cf57) could never be forecast: every documented
  // attempt failed closed and published nothing. The two August 3 rolls
  // made four generation attempts (runs 30783158439 and 30840402885:
  // two failed before producing run manifests, two produced candidate
  // cells that failed anchor validation), and the 2026-08-04 ticketed
  // local run refused when FSA's statistics site — the pair's sole
  // registered source — failed to serve the official summary. FSA was
  // unreachable that day and still unreachable at the published grace
  // deadline (2026-08-10 18:15 UTC). The minted ticket and the refusal
  // report on issue #128 are public; the raw refusal trace is retained
  // off-repo. The 2027-09 first print is far in the future, but the
  // registrations pin an information set from August 3 and their grace
  // has passed; both arms terminate together, honestly, on the record.
  // A fresh pair may be registered if the source recovers.
  "usda.fsa.crp.enrolled_acres_total.2027_09.first_print.ceiling_27_million",
  "usda.fsa.crp.enrolled_acres_total.2027_09.first_print.no_fy2027_31_ceiling",
  // The 2026-08-05 registrations for the UK AWE June regular-pay print
  // and the UK PPI July input-price print crossed their seven-day orphan
  // grace on 2026-08-12 16:45 UTC without a forecast. Their registering
  // roll (run 31026650852) generated candidate cells, but its publish
  // leg failed the site suite before committing anything, so no batch
  // manifest reached main and the in-grace retry lane's
  // committed-manifest trust anchor could not reach the pair. Their
  // prints arrive with the registrations already stale, and forecasting
  // after grace would break the chronology the window exists to protect
  // (the 2026-07-22 prospect precedent). Both terminate here
  // explicitly.
  "ons.awe.regular_pay_yoy_3m_avg.2026_06.first_print",
  "ons.ppi.input_manufacturing_index.2026_07.first_print",
  // The 2026-09-20T17:30:51Z registration of initial claims for the week
  // ending 2026-09-26 crossed its seven-day orphan grace on 2026-09-27
  // unforecast. Its registering roll (run 35526068252) generated a
  // candidate cell, but the publish leg refused it ("custody verification
  // failed: draft_tool evidence calls lack native completion events"), so
  // no cell or batch manifest reached main. The 2026-09-21 and 2026-09-25
  // rolls (runs 35651332378, 36183523886) skipped it as already
  // registered, and nothing retried the generation inside grace. DOL
  // prints that week on 2026-10-01, but a forecast now would run against
  // the eight-day-stale 2026-09-20 pin, the chronology violation the
  // entries above terminate on. The registered window (2026-10-13 to
  // 2026-10-17) is also one of the drifted weekly claims windows.
  "us.dol.initial_claims.sa.week_2026-09-26",
] as const;

export const EXPIRED_UNFORECAST_SET: ReadonlySet<string> = new Set(
  EXPIRED_UNFORECAST_REGISTRATIONS,
);
