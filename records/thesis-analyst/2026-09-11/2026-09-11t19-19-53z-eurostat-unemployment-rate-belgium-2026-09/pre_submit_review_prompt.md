# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: eurostat.unemployment_rate.belgium
- period: 2026-09
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "belgium-unemployment-rate-september-2026"
- country: "BE"
- targetUnit: "percent"
- dataPointId: "eurostat.une_rt_m.unemployment_rate.belgium.2026_09.first_print"
- expectedReleaseWindow: {"end": "2026-11-09", "start": "2026-11-01"}
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["ec.europa.eu"], "expectedReleaseWindow": {"end": "2026-11-09", "start": "2026-11-01"}, "field": "eurostat.unemployment_rate.belgium", "releasePolicy": "first_print", "sourceSeriesId": "eurostat.unemployment_rate.belgium", "sourceUrl": "https://ec.europa.eu/eurostat/databrowser/view/une_rt_m/default/table?lang=en", "table": "Eurostat monthly unemployment euro-indicators release / une_rt_m data page", "transform": {"factor": 1, "operation": "multiply"}}
- targetRegistrationPath: "records/targets/2026-09-11-2a2e910a9190e434ae3320828c92ff9333ea94033678800a7900d94687de0d26.json"
- targetContentHash: "2a2e910a9190e434ae3320828c92ff9333ea94033678800a7900d94687de0d26"
- registrationCommit: "f527f4e54f1df0156366f87eeb5dd630eeb66fe4"
- registeredAtUtc: "2026-09-11T19:13:41Z"
# Rubric
Check these items and name concrete fixes when needed:
1. Exact resolver, source, first-print rule, and resolution date.
2. Base-rate or persistence prior stated before inside-view updates.
3. Time-series/model prior used or explicitly ruled out.
4. Current evidence justifies material movement from the prior.
5. Interval size comes from realized volatility or explicit uncertainty.
6. A compact Prior/update/interval step names the prior, historical sample, adjustment components, interval method, and implied bounds.
7. Tail scenarios are concrete and tied to the target.
8. Point, interval, final forecast step, and JSON fields are coherent.
9. No leakage, catalog point/interval circularity, subjective resolver, or unit ambiguity.

# Required response
Return JSON only, with this shape:
{
  "summary": "one sentence",
  "requiredFixes": [
    {
      "rubricItem": "resolver|base_rate|model_prior|update|interval|prior_update_interval|tails|coherence|leakage",
      "severity": "warning|blocking",
      "summary": "specific issue",
      "actionRequested": "specific change requested"
    }
  ],
  "optionalSuggestions": ["short suggestions"]
}

# Original forecaster prompt hash material
bc0a3e755a4fa228b53355f8fc039f48e164e595465cecc0b85bfa8c6400e61c

# Draft forecast response
{"slug":"belgium-unemployment-rate-september-2026","country":"BE","type":"data","title":"Belgium unemployment rate, September 2026","question":"What will Eurostat first print for Belgium's seasonally adjusted total unemployment rate, age 15-74, unit PC_ACT, in une_rt_m for September 2026?","unit":"percent","pointEstimate":6.1,"ciLow":5.9,"ciHigh":6.3,"confidence":0.8,"resolutionDate":"2026-11-09","resolutionSource":"Eurostat monthly unemployment euro-indicators release / une_rt_m data page","resolutionSourceUrl":"https://ec.europa.eu/eurostat/databrowser/view/une_rt_m/default/table?lang=en","resolutionRule":"Resolve to the first Eurostat print in table une_rt_m for geo=BE, s_adj=SA, sex=T, age=Y15-74, unit=PC_ACT, time=2026-09, reported in percent to one decimal. Use the first official value published for that monthly observation; do not substitute later revisions. The registered ledger target expectedReleaseWindow is 2026-11-01 to 2026-11-09, and this cell uses the target's 2026-11-09 contractual resolutionDate.","dataPointId":"eurostat.une_rt_m.unemployment_rate.belgium.2026_09.first_print","historicalContext":[{"period":{"type":"month","value":"2026-02"},"label":"2026-02","value":6.4},{"period":{"type":"month","value":"2026-03"},"label":"2026-03","value":6.3},{"period":{"type":"month","value":"2026-04"},"label":"2026-04","value":6.2},{"period":{"type":"month","value":"2026-05"},"label":"2026-05","value":6.3},{"period":{"type":"month","value":"2026-06"},"label":"2026-06","value":6.3},{"period":{"type":"month","value":"2026-07"},"label":"2026-07","value":6.0}],"drivers":["Latest first-print Belgium unemployment rate was 6.0 percent for July 2026 after several months near 6.2 to 6.4 percent.","Belgium monthly unemployment in Eurostat's seasonally adjusted total age 15-74 series is persistent, but recent first prints include a 0.3 percentage point July drop.","Two unreleased months remain before the September target, so I partly mean-revert the July low rather than fully carry it forward.","Euro area and EU unemployment rates were stable around 6.4 percent and 6.1 percent in the latest Eurostat release, limiting the case for a sharp Belgian break."],"sourceContext":["https://ec.europa.eu/eurostat/web/products-euro-indicators/w/3-01092026-bp","https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/3-30072026-bp","https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/3-01042026-ap","https://ec.europa.eu/eurostat/en/web/products-euro-indicators/w/3-30042026-cp","https://ec.europa.eu/eurostat/news/euro-indicators/release-calendar","https://ec.europa.eu/eurostat/databrowser/view/une_rt_m/default/table?lang=en"],"runAt":"2026-09-11T19:20:13Z","reasoning":[{"kind":"heading","text":"Belgium unemployment rate, September 2026"},{"kind":"text","text":"Framing and exact resolver: this is Eurostat table une_rt_m, Belgium geo=BE, seasonally adjusted s_adj=SA, total sex sex=T, age 15-74, unit PC_ACT, for period 2026-09. The settlement value is the first official print only, rounded to one decimal percentage point, with later revisions ignored."},{"kind":"tool","tool":"official.lookup","call":"Checked Eurostat's euro-indicators release calendar page and the registered target timing for the September 2026 unemployment release.","result":"Eurostat's release-calendar page is the official schedule source; the registered public target window is 2026-11-01 to 2026-11-09, and the ledger resolutionDate is 2026-11-09. The same Eurostat unemployment sequence showed the July 2026 release on 2026-09-01 and the prior June 2026 release on 2026-07-30."},{"kind":"tool","tool":"official.lookup","call":"Fetched the latest Eurostat euro-indicators unemployment release for July 2026, seasonally adjusted unemployment totals.","result":"Eurostat's 2026-09-01 July 2026 release printed Belgium rates of 6.1 for Jul-25, 6.3 for Apr-26, 6.3 for May-26, 6.3 for Jun-26, and 6.0 for Jul-26; the same table printed euro area 6.4 and EU 6.1 for Jul-26."},{"kind":"tool","tool":"official.lookup","call":"Fetched prior Eurostat unemployment releases to build the recent same-variant first-print reference class.","result":"Eurostat releases printed Belgium total unemployment rates of 6.4 for Feb-26 in the 2026-04-01 release, 6.3 for Mar-26 in the 2026-04-30 release, 6.2 for Apr-26 in the 2026-06-01 release, 6.3 for May-26 in the 2026-07-02 release, and 6.3 for Jun-26 in the 2026-07-30 release."},{"kind":"tool","tool":"official.lookup","call":"Checked Eurostat release notes and methodology fields for variant control.","result":"Eurostat states the unemployment rate is unemployed persons as a percentage of the labour force and that rates in the news release cover persons aged 15 to 74; the July 2026 Belgium total table also printed 329 thousand unemployed persons and 6.0 percent for Jul-26."},{"kind":"text","text":"Base rate / reference class: the recent same-variant first-print reference class is 6.4, 6.3, 6.2, 6.3, 6.3, and 6.0 percent for February through July 2026. That centers near 6.25 percent but ends at 6.0 percent, so persistence alone points around 6.0 to 6.1 while the broader six-month base rate argues against treating July as a permanent collapse."},{"kind":"text","text":"Variant control: all anchors use Eurostat seasonally adjusted unemployment totals for Belgium, age 15-74, percent of active population, matching une_rt_m and the target's first-print variant; I am not mixing youth, sex-specific, unadjusted, national-register, or revised settlement definitions."},{"kind":"math","text":"Prior/update/interval: persistence prior = latest same-series first print, July 2026 at 6.0; historical sample = Feb-Jul 2026 first prints 6.4, 6.3, 6.2, 6.3, 6.3, 6.0; adjustment components = +0.05 for mean reversion from the isolated July drop, +0.03 for stable euro area/EU labor-market backdrop, +0.02 for two-month horizon rounding uncertainty, giving point 6.1 after one-decimal rounding. For the level/rate interval I used successive changes -0.1, -0.1, +0.1, 0.0, -0.3; sigma = 0.15, so 80% half-width = 1.28*sigma = 1.28*0.15 = 0.19; rounded one-decimal bounds around 6.1 are 5.9 to 6.3."},{"kind":"text","text":"Counter-considerations: upside risk is a reversal of the July drop, weaker employment survey inputs, or upward first-print seasonal adjustment that would land above the interval; downside risk is continued labor-force absorption or another unemployment-count fall that would land below the interval. A sudden Belgium-specific survey rebenchmark or data-processing revision would be outside the interval risk in either direction."},{"kind":"forecast","point":6.1,"ciLow":5.9,"ciHigh":6.3}]}
