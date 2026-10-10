# Colorado HCPF Monthly Premiums Report fixtures

Responses fetched from the official Colorado Department of Health Care Policy
and Financing site on 2026-10-09 (19:38 UTC), for the
`co.hcpf.medicaid.total_caseload` resolver leg.

## Byte-for-byte official responses

| Fixture | Official URL | HTTP Last-Modified | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| `landing_2026-10-09.html` | `https://hcpf.colorado.gov/budget/FY-Premiums-Expenditures-Caseload-Reports` | not recorded | 33,279 | `72c24222f9e82d461f9781689905b6f26a2b18141254a3e0c1a14aa8458a0699` |
| `report_2026-09.xlsx` | `https://hcpf.colorado.gov/sites/hcpf/files/2026%20September%2C%20Joint%20Budget%20Committee%20Monthly%20Premiums%20Report.xlsx` | Mon, 14 Sep 2026 17:35:17 GMT | 447,580 | `ac0f211eb5ce892340db35f5ae371636a399a9758980810407a0550a2a8fc56f` |

## One page of each official report PDF

The report PDFs are 1.4 to 2.0 MB and stay out of the repo. Each
`report_<YYYY-MM>_caseload_page.pdf` is page 4 of the official file, the page
that carries the table "MEDICAID CASELOAD WITHOUT RETROACTIVITY", cut out
with `pdfseparate -f 4 -l 4` (poppler 26.09.0). It is not the official file
and does not hash to it; the table below records the file it came from.
`<YYYY-MM>` is the month the report is dated.

| Fixture | Official file (`/sites/hcpf/files/…`) | HTTP Last-Modified | Official bytes | Official SHA-256 | PDF CreationDate | Newest caseload month | TOTAL |
| --- | --- | --- | ---: | --- | --- | --- | ---: |
| `report_2026-06_caseload_page.pdf` | `2026 June, Joint Budget Committee Monthly Premiums Report.pdf` | Mon, 15 Jun 2026 20:20:16 GMT | 1,596,164 | `75d80effcf78f6b77846eb772b419cd0c7393f3e2513815658591b23cb3c40a6` | 2026-06-15 09:46:39 -06:00 | May 2026 | 1,238,720 |
| `report_2026-07_caseload_page.pdf` | `2026 July, Joint Budget Committee Monthly Premiums Report.pdf` | Wed, 15 Jul 2026 18:53:51 GMT | 2,040,809 | `82af6af443a55615e5b050c866f35a19f0fc55fa52766afcf9d30015061eec99` | 2026-07-14 15:26:43 -06:00 | June 2026 | 1,237,772 |
| `report_2026-08_caseload_page.pdf` | `2026 August, Joint Budget Committee Monthly Premiums Report.pdf` | Mon, 17 Aug 2026 18:00:45 GMT | 1,418,024 | `f83cfbb7ac9922b8025289133294510a94a19aa14d53c3bbd379e295d640c30b` | 2026-08-14 11:10:56 -06:00 | July 2026 | 1,242,335 |
| `report_2026-09_caseload_page.pdf` | `2026 September, Joint Budget Committee Monthly Premiums Report.pdf` | Mon, 14 Sep 2026 17:35:17 GMT | 1,426,626 | `8c3f7731a35d6babfa0f6da2d2208cbe20bdedcf7fe530e426c7f23071fdc60b` | 2026-09-11 11:42:55 -06:00 | August 2026 | 1,247,588 |

Each `report_<YYYY-MM>_caseload_page.pdftotext.txt` is
`pdftotext -layout -enc UTF-8` of the page fixture beside it, rendered by
poppler 26.09.0. The tests read the table from that text, and, where
`pdftotext` is installed, render the page again and require the same table,
so a different poppler build is checked against this one.

## What the files show

- The month in a report's file name is the month the report is dated; its
  newest caseload month is the month before. The page's own note says the
  opposite ("a report with the link August will reference August activity"),
  which is why the reader checks the report's content and never its name.
- The workbook and the PDF of the September 2026 report agree on every month
  the PDF prints (July 2022 to August 2026), category by category.
- Reports restate earlier months: the June 2026 report prints 1,236,285 for
  January 2026, where the February 2026 report had first printed 1,236,302
  (the value the forecast recorded as history).
- The workbook's history before the PDF's range holds three months
  (September to November 2014) with a figure that is not a whole count.
