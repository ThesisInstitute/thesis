# Thesis pre-submit forecast review

You are a reviewer for a forecast before publication. Review the draft forecast, the target spec, cited public evidence, and any relevant local repo context or prior traces if useful. This extra context is optional; do not require it when the draft is already clear. Do not use future outcomes, private knowledge, or hidden chain-of-thought. Do not produce a replacement forecast.

# Target
- series: ons.ppi.input_prices_yoy
- period: 2026-08
- conditional: null


# Canonical ledger target context
Use these ledger fields as the target contract for slug, unit, dataPointId, resolutionDate, and resolver text. The cell's unit must equal targetUnit below byte-for-byte, even when it is not a member of the contract's exploratory unit menu. If you find a concrete ledger error, keep the forecast tied to the same target and state the discrepancy in reasoning rather than silently changing the target.
- catalogSlug: "uk-ppi-input-prices-annual-rate-august-2026"
- country: "UK"
- targetUnit: "percent_growth"
- dataPointId: "ons.ppi.input_prices_yoy.2026_08.first_print"
- expectedReleaseWindow: {"end": "2026-09-16", "start": "2026-09-16"}
- resolutionSourceUrl: "https://www.ons.gov.uk/releases/producerpriceinflationukaugust2026timeseries"
- sourceBinding: {"adapter": "generic-url", "allowedHosts": ["www.ons.gov.uk"], "expectedReleaseWindow": {"end": "2026-09-16", "start": "2026-09-16"}, "field": "Total input producer prices, 12-month percentage change", "releasePolicy": "first_print", "sourceSeriesId": "PPI:GHIP", "sourceUrl": "https://www.ons.gov.uk/releases/producerpriceinflationukaugust2026timeseries", "table": "Producer price inflation time series", "transform": {"factor": 1, "operation": "identity"}}
- targetRegistrationPath: "records/targets/2026-08-26-2c4797e85af3bb173fcc595dd241efba3eea6d9f2c854085b8195f60588ba1b6.json"
- targetContentHash: "2c4797e85af3bb173fcc595dd241efba3eea6d9f2c854085b8195f60588ba1b6"
- registrationCommit: "b4f1d890f91c9ece5fc1e068a92fbe28ea25be43"
- registeredAtUtc: "2026-08-26T16:23:02Z"
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
7da8467a337a5d5a3d50903bccb82fb05185a39e431782dc1fe55c644ab39018

# Draft forecast response
{"slug":"uk-ppi-input-prices-annual-rate-august-2026","country":"UK","type":"data","title":"UK PPI Input Prices Annual Rate, August 2026","question":"What will the Office for National Statistics first report for the UK Producer Price Inflation total input producer prices 12-month percentage change, All materials and fuels purchased (GHIP), for August 2026?","unit":"percent_growth","pointEstimate":5.1,"ciLow":0.6,"ciHigh":9.6,"confidence":0.8,"resolutionDate":"2026-09-16","resolutionSource":"Office for National Statistics Producer price inflation, UK: August 2026 time series","resolutionSourceUrl":"https://www.ons.gov.uk/releases/producerpriceinflationukaugust2026timeseries","resolutionRule":"Resolve to the first value published by ONS for August 2026 in Producer price inflation, UK: August 2026 time series for Total input producer prices, 12-month percentage change, All materials and fuels purchased (GHIP), in percent_growth and rounded as printed by ONS, normally one decimal place. Use the first official print only and ignore later revisions, corrections, and superseded versions.","dataPointId":"ons.ppi.input_prices_yoy.2026_08.first_print","historicalContext":[{"period":{"type":"month","value":"2025-08"},"label":"August 2025","value":0.3},{"period":{"type":"month","value":"2025-09"},"label":"September 2025","value":0.9},{"period":{"type":"month","value":"2025-10"},"label":"October 2025","value":0.9},{"period":{"type":"month","value":"2025-11"},"label":"November 2025","value":1.1},{"period":{"type":"month","value":"2025-12"},"label":"December 2025","value":0.5},{"period":{"type":"month","value":"2026-01"},"label":"January 2026","value":-0.2},{"period":{"type":"month","value":"2026-02"},"label":"February 2026","value":0.7},{"period":{"type":"month","value":"2026-03"},"label":"March 2026","value":5.5},{"period":{"type":"month","value":"2026-04"},"label":"April 2026","value":8.1},{"period":{"type":"month","value":"2026-05"},"label":"May 2026","value":9.2},{"period":{"type":"month","value":"2026-06"},"label":"June 2026","value":7.4},{"period":{"type":"month","value":"2026-07"},"label":"July 2026","value":4.9}],"drivers":["July GHIP annual rate fell to 4.9% after 7.4% in June","July GHIP index of 164.5 against August 2025 index of 156.8 implies about 4.9% year-over-year if August 2026 is flat on the month","Recent monthly input PPI momentum was negative at -1.9% in June and -1.7% in July","Crude oil drove the July decline with an 18.0% monthly fall but other input groups remained mostly positive on an annual basis","Metals and chemicals still supported the annual rate at 8.4% and 6.1% in July"],"sourceContext":["https://www.ons.gov.uk/releases/producerpriceinflationukaugust2026timeseries","https://www.ons.gov.uk/economy/inflationandpriceindices/bulletins/producerpriceinflation/july2026","https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/ghip/ppi"],"runAt":"2026-08-26T16:25:41Z","reasoning":[{"kind":"heading","text":"UK PPI Input Prices Annual Rate, August 2026"},{"kind":"text","text":"Framing and resolver: the target is the ONS first print for the August 2026 total input producer prices 12-month percentage change, All materials and fuels purchased, series/table GHIP, in percent_growth. The registered August 2026 release page says this not-yet-published time series release is scheduled for 16 September 2026 at 7:00am, so I keep the ledger resolutionDate and first-print-only rule."},{"kind":"tool","tool":"official.lookup","call":"Open ONS August 2026 PPI time series release placeholder","result":"Fetched ONS release page for Producer price inflation, UK: August 2026 time series: release date 16 September 2026 7:00am; page status says not yet published; registered target field remains GHIP August 2026 first print."},{"kind":"tool","tool":"official.lookup","call":"Read ONS Producer price inflation, UK: July 2026 Table 1 for GHIP annual rates","result":"Fetched GHIP annual inflation rates from ONS Table 1: August 2025 0.3, September 2025 0.9, October 2025 0.9, November 2025 1.1, December 2025 0.5, January 2026 -0.2, February 2026 0.7, March 2026 5.5, April 2026 8.1, May 2026 9.2, June 2026 7.4, July 2026 4.9 percent."},{"kind":"tool","tool":"official.lookup","call":"Read ONS Producer price inflation, UK: July 2026 Table 1 for GHIP index and monthly-rate mechanics","result":"Fetched GHIP index and monthly rates: July 2025 index 156.7 with monthly rate 0.6 and annual rate -0.1; August 2025 index 156.8 with monthly rate 0.0 and annual rate 0.3; June 2026 index 167.3 with monthly rate -1.9 and annual rate 7.4; July 2026 index 164.5 with monthly rate -1.7 and annual rate 4.9."},{"kind":"tool","tool":"official.lookup","call":"Read ONS July 2026 input-price component discussion for current-release drivers","result":"Fetched component drivers from ONS July 2026 release: crude oil input prices fell 18.0% on the month and were up 10.6% on the year; metals and non-metallic mineral products were up 8.4% on the year; chemicals were up 6.1%; domestic food was down 1.6%; imported food was up 1.0%."},{"kind":"text","text":"Base rate / reference class: for the same GHIP annual-rate variant, the latest 12 official monthly annual rates average 3.275 percentage points, but that mixes a low-inflation period through February with a March-May jump and a June-July unwind. A persistence base rate from the July 2026 annual rate of 4.9% is more targeted for a one-month-ahead first print, while the 12-month sample controls the interval width."},{"kind":"math","text":"Prior/update/interval: persistence prior = July 2026 GHIP annual rate 4.9%; historical sample = August 2025 through July 2026 annual rates [0.3, 0.9, 0.9, 1.1, 0.5, -0.2, 0.7, 5.5, 8.1, 9.2, 7.4, 4.9]; adjustment components = +0.2 percentage point because July's index 164.5 over the August 2025 base index 156.8 mechanically gives 4.9% if August is flat, while non-oil inputs still show positive annual pressure despite negative recent crude-oil momentum. Interval method = sample dispersion of recent annual-rate values, sigma = 3.49 percentage points, and 80% half-width = 1.28*sigma = 1.28*3.49 = 4.47 percentage points. Point = 4.9 + 0.2 = 5.1; interval = 5.1 +/- 4.5 = [0.6, 9.6] after one-decimal rounding."},{"kind":"text","text":"Counter-considerations: downside risk outside the interval would require another large August fall in crude oil or imported input prices plus weaker metals and chemicals, pushing the annual rate below 0.6%. Upside risk outside the interval would require a renewed energy or precious-metals shock that lifts August input prices sharply enough to land above 9.6%. The central case is a near-flat to modestly positive August index after two sharp monthly declines."},{"kind":"forecast","point":5.1,"ciLow":0.6,"ciHigh":9.6}]}
