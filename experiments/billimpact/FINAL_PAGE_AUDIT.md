# FINAL_PAGE_AUDIT — demo_page.html

Audited: 14:49 snapshot (full content read), re-checked by targeted grep against the 15:04 snapshot
(1,634,902 bytes, md5 e1faddbc77767de3298b33dcb3b8681b). Designer restyling is concurrent; anything
after 15:04 is unaudited. Recalibrated bar applied mid-audit per owner: strategy + slop primary;
claim items only where unambiguous.

## A. Found → verified applied in the 15:04 bytes

1. "Result 4 · changes shipped" contradicted its own H2 ("two are open PRs") and status column → now "pipeline changes". ✓
2. "costs −0.034 nCRPS" sign inversion (Result 4 row + calibration appendix; a cost stated as a gain under lower-is-better) → now +0.034, both sites. ✓
3. "registered S.3596" (TL;DR) vs "recorded" (H2) vocabulary split → harmonized to "recorded" incl. the Result 3 tag; "already-registered targets" retained where legitimate. ✓
4. Footer "44 retrospective units" irreconcilable with N=36 / 12 / 28 on-page → now 48 with decomposition + independence note. ✓ (old string gone; decomposition prose not re-read)
5. Result 3 stated no runs-per-cell (SENSE_CHECK.md item 8 had pinned the exact wording) → "(medians of 3 repeats; one cell n=2)" present. ✓
6. Result 1 table denominators (0/3, 0/4, 3/3, 6/6) mixed cells with effort levels, unexplained → figcaption clause present ("effort levels" ×2). ✓
7. "What's here:" ×4 ("Here's what" family tic) → gone. ✓
8. "Two failure modes, two fixes; neither substitutes for the other." (aphorism restating its own row) → gone. ✓
9. "What the measurements add is the map" / "leads the board" / "on the board" flexes → gone. ✓
10. TL;DR tools bullet: obvious half (tools→100%) led; trap (incomplete text degrades tooled runs) buried → flipped trap-first, moved below envelope bullet. ✓

## B. Remaining (unambiguous under the recalibrated bar; all small)

1. **Duplicate case, adjacent collapsibles (admission).** medicaid.us.2024-01 (793.7→783.0, print 866.7; 835/795/865) is told nearly verbatim in both "Case study: one unit, three behaviors…" and "Case notes: five units worth reading individually." Not in the applied list. **Fix:** cut the medicaid paragraph from Case notes; retitle "…four units worth reading individually."
2. **TL;DR bullet order (ordering).** Envelope bullet ("The recorded S.3596 poverty delta holds in 14/16…") now sits 4th, below the calibration bullet ("At default effort, bill text narrowed intervals in 12/12…"). Owner priority ranks the envelope third; calibration is not in the stated top four. **Fix:** swap bullets 3↔4.
3. **PRs absent from TL;DR (ordering/admission).** The shipped-artifact story (owner priority #4) never reaches a TL;DR-only reader. **Fix:** append a short final bullet: "Three pipeline changes follow directly: PRs #78 and #79 filed, a third proposed in review."
4. **Residual quip (slop).** "Nothing here asks anyone to take today's word for it" (forward-program collapsible) — still present at 15:04. **Fix:** "None of this depends on trusting today's claims: the lab scores these mechanically as targets resolve."
5. **Unconfirmed: findings-table row swap.** Reported applied (significant bill×effort row to position 1; harness-dependence row, which quotes only zero-spanning CIs, to position 2); my markup probe didn't parse the table, so unverified either way. **Fix:** one glance in the pre-demo visual pass; if the harness-dependence row still opens the table, swap, and consider inserting "(−0.094 [−0.174, −0.022] vs its naive)" after "significantly best system measured" so the word "significantly" sits next to a zero-excluding CI.

## C. CLEAN (checked, passes)

- **Cross-page number consistency.** Pooling arithmetic reproduces (−0.094 single-run + −0.013 pooling = −0.107 headline); relative claims reproduce from the page's own values (26% vs naive, 66% vs persistence); TL;DR ↔ findings table ↔ forest figcaption ↔ glossary agree on every shared number (−0.094 [−0.174,−0.022]; −0.518 [−0.863,−0.228]; −0.013 [−0.022,−0.005]; 0.264→0.251; 0.77→0.81); fable·bill·max-vs-persistence is arithmetically coherent with persistence +0.48 vs opus·naive; calibration 12/12 and 0.50→0.33 match TL;DR↔appendix; mechanical-leg 4/100/50/94/86 consistent everywhere quoted.
- **Against source records.** −0.094, −0.518, 26/36, 29/36, 17/17, 16/17, −1.016, −0.225, nCRPS 0.08 (ctcadv) match RESULTS.md; envelope 14/16 band, outliers (−1.5 / 0.00), CTC 16/16 (+0.3–1.2M) match SENSE_CHECK's independent recomputation from runs_envelope.jsonl; "−0.20pp absolute (−1.2% relative)" carries SENSE_CHECK item 1's units fix; mechanical −0.20pp stays out of Result 3 (item 8's separation preserved). Pooling/exclusion numbers (0.264/0.251, −0.367, −0.194) verified page-internally; per coordinator they are CHECK2-lineage, computed in-session — not findable in results/*.md, as expected.
- **Statistical hygiene.** Every directional claim I checked carries a zero-excluding CI; every null is labeled (n.s., "indistinguishable", "null", "not significant", "clustering-fragile"). Ex-post constructions are disclosed as ex-post (stratifier "locates the skill after the fact… not an ex-ante selection rule"; retrospective accuracy "treated as an upper bound"; explorer marked exploratory vs the authoritative forest plot). Best-unit exclusion robustness present (−0.367; −0.194, n=32).
- **Ordering.** Section sequence = owner's four priorities in exact order (R1 recall → R2 N=36 config → R3 envelope → R4 PRs); within R2, validated headline → explorer → margin decomposition is right; the 17/17-on-moved-units paragraph is prominent, not buried.
- **Slop sweep.** Zero em-dashes in prose (the 3 `&mdash;` are explorer readout placeholders — allowed UI); no "It's worth noting"/"Crucially"/"At its core"/"Here's why"; no exclamation-mark enthusiasm; no tripartite rhetorical lists; no "not X, it's Y" formulas; no first-person swagger. Dense compressions ("the added context made the models more certain of less accurate answers"; "which is what bill tools do") are earning their keep, not flexing.
- **Admission.** Corpus-A dispersion correctly demoted to a collapsed appendix (tier dispersion 12.4× is the expected result; its value is foreshadowing Result 3's name-channel outliers — keep as is). Case-study and mechanism collapsibles are strong first drill-downs. Glossary closed by default with the elicitation-vs-harness terminology note — right call for this audience. Appendix contains nothing that demands promotion beyond items B2–B3 above.

## D. Checked and deliberately not actioned (recalibrated bar; recorded for transparency, not as findings)

- Two-legs attenuation attribution ("the recall mechanism predicts") sat in mild tension with Result 1's future-periods-track finding; TWO_LEGS_S3596.md itself hedges it. Coordinator reports it softened to "consistent with the under-response…" — not re-verified.
- "Nine enacted laws" vs §301 tariff notices (administrative actions) — defensible as written; not flagged.
- "Pooling improves every arm it applies to" (glossary) — direction-only claim, buried, one CI given for the leading config; left alone.
