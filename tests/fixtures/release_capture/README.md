# Release capture fixtures

`*.raw` files are exact bodies the Internet Archive stores for one capture
(its `id_` form, before BLS's gzip is removed). Beside each is a `.json`
sidecar with the capture URL, the index row's digest, the page title and a
note. Every sidecar but CPI's also records the figure an independent source
(an ALFRED first-print vintage) gives for the same cell.
`tests/test_release_capture_real_fixtures.py` checks each body against its
index digest and refuses any fixture whose month a reviewed contract
forecasts. It compares each pinned figure with a second source: the
release's own prose for CPI, and the ALFRED vintage for the rest.

| Fixture | Page | Release |
|---|---|---|
| `cpi.nr0-20260720045436` | CPI summary, HTML Table A | June 2026 |
| `empsit.nr0-20260810222604` | Employment Situation summary, prose only | July 2026 |
| `jolts.nr0-20260810093236` | JOLTS summary, prose only | June 2026 |
| `jolts.t04-20260816021553` | JOLTS Table 4, HTML table | June 2026 |

The CPI fixture was fetched 2026-10-16. The other three were fetched
2026-10-22, once the TLS filter that blocked web.archive.org on 10-16 was
gone. All four came over verified TLS. Each capture was selected from the
Archive's index alone (timestamp, status, digest), dated before every target
window for its page. Never fetch a capture dated inside a target window.

`corpus/` holds 50 more captures, one per release month: the Employment
Situation for 21 months from July 2024 to June 2026, CPI for 12 from May
2025 to May 2026, the JOLTS summary for 9 from August 2025 to May 2026,
and JOLTS Table 4 for 8 from August 2025 to April 2026. Each was chosen
from the Archive's index alone (the earliest status-200 capture from a
fixed day of each calendar month), with the index queried only up to a
cutoff at least a month before every target window for its page, and
fetched 2026-10-23 from the `id_` form over verified TLS. Each sidecar
records the ALFRED vintage dated the capture day
(`alfredgraph.csv?id=...&vintage_date=...`): UNRATE; PAYEMS less the prior
month; CPIAUCSL and CPILFESL as a one-month percent change, which the page
prints to 0.1; JTSJOL in millions, printed to 0.1; JTSQUR. The tests read
every capture with every parser, through the leg's own discovery, and
check that each figure equals its first print, that no other parser reads
the page, and that each capture predates every reviewed window for its
page.

The corpus is where the readers met BLS's real wording. Before it, 18 of
its 83 reader-capture pairs deferred (2 rightly, the November 2025 CPI
below); every reading that returned was right. The forms it added:
"roughly in line with" and "but has ..." tails; a rate lead carrying the
payroll clause ("The unemployment rate rose to 4.3 percent in July, and
nonfarm payroll employment edged up by 114,000"); a statement that leaves
its month unsaid ("held at 4.3 percent", "over the month"), which only
corroborates a dated one and never refuses the page; the JOLTS tail "but
was down by 885,000 over the year"; a heading month not in capitals
("March 2026"); the December release titled "M13"; and JOLTS's "continued
to trend down" and "6.5 million (-386,000)". One capture is an expected
refusal, with its reason in the sidecar: the November 2025 CPI release
prints "-" for the one-month changes, as BLS collected no October 2025
data. The September 2024 Employment Situation, titled "2024 Q03", is not
in the corpus; its title dates no month, so the reader refuses it.

A tail is one of a few closed forms (`_TAILS` in the parser), chosen by
the clause the statement ends with, and each of the corpus's 23 tails is
one of them: a comparison, naming what it compares with (a figure, a
change, an average or a trend) and then that operand's own period
("following an average monthly gain of 194,000 over the prior 12
months"); the trend since another period ("and has shown little change
since April"); after a rate, the number unemployed or the
population-control note; after the openings level, "but was down by
885,000 over the year". Anything else after the month ("compared with a
year earlier", "compared with the U.S. rate of 4.1 percent", "after
including discouraged workers", ", and by 120,000 for the month") makes
the sentence no statement, because it can say the statement's own figure
is of another basis, scope or period. A comparison or trend naming the
release month itself is no tail either. Some captures name the bureau "the
U.S. Bureau of Labor Statistics (BLS)" before "reported today". The
statements that leave their month unsaid count only when every one of
them states the dated figure.

In every capture, where the release first names the measure after its
heading ("unemployment rate", "nonfarm payroll employment", "job
openings"), a dated statement of the month holds that mention: the lead
paragraph. The readers require it, so the figure read is always the one
the lead states. Three 2025 Employment Situations state the rate in the
lead's second sentence ("The unemployment rate, at 4.2 percent, also
changed little in July."), after a first sentence about payrolls alone.

The Employment Situation and JOLTS summaries print no table. Their figures
are read from the release's prose (`PROSE_PARSERS` in
`scripts/legacy_release_parsers.py`). The JOLTS summary states total job
openings only to 0.1 million: "7.4 million" for June 2026, where ALFRED's
first-print vintage has 7,359 thousand. Both openings contracts read a
thousands figure, so the resolver holds them
(`LEGACY_RELEASE_PRECISION_HELD`) until ruling d1856.

`cdx/` holds the Archive's index for each no-custody void of ruling d1633
(`scripts/voided_targets.py`): the registered page and release window, the
exact query the leg sends, and the body served on 2026-10-24 (an empty
index, `[]`). An index read lists timestamps, statuses and digests; no
capture was opened. `tests/test_voided_targets.py` replays each read through
the leg's own discovery.
