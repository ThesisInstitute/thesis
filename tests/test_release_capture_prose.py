"""The prose readers for the Employment Situation and JOLTS summary pages.

empsit.nr0.htm and jolts.nr0.htm print no table: the release is one
preformatted block of prose (see the real captures in
tests/fixtures/release_capture/). These tests generate such releases from
the phrasings BLS uses, with decoys BLS prints beside the headline figure
(revised earlier months, the average monthly gain, subgroup rates, industry
changes), and check that the reader returns exactly the headline figure or
refuses. Values are synthetic; no target-month release is quoted.

Invariants, for every generated release:
- the reader returns (release month, headline figure), exactly;
- no decoy number ever changes what it returns;
- one statement alone, two statements that disagree, a statement naming
  another month, a title and heading that disagree, or a page without
  exactly one preformatted block is refused (None), never guessed.
"""

from __future__ import annotations

import pathlib
import sys
from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from legacy_release_parsers import PROSE_PARSERS, parse_release  # noqa: E402

MONTHS = (
    "January February March April May June July August September October "
    "November December"
).split()


def _page(title: str, pre: str, *, pres: int = 1) -> str:
    blocks = "".join(f"<pre>\n{pre}\n</pre>" for _ in range(pres))
    return (
        f"<html><head><title>{title}</title></head><body>"
        f"<div><p>Navigation</p></div>{blocks}<p>Footer</p></body></html>"
    )


def _signed(thousands: int) -> str:
    return f"{thousands * 1000:+,}"


def _rate_text(rate: Decimal) -> str:
    return f"{rate:.1f}"


@st.composite
def _empsit(draw: st.DrawFn) -> dict:
    month = draw(st.integers(1, 12))
    rate = Decimal(draw(st.integers(20, 99))) / 10
    payroll = draw(st.integers(-999, 999).filter(lambda value: value != 0))
    return {
        "month": month,
        "rate": rate,
        "payroll": payroll,
        "rate_lead": draw(st.integers(0, 2)),
        "rate_section": draw(st.integers(0, 2)),
        "payroll_lead": draw(st.integers(0, 1)),
        "payroll_section": draw(st.integers(0, 2)),
        "decoys": draw(st.lists(st.integers(1, 999), min_size=6, max_size=6)),
        "decoy_rate": Decimal(draw(st.integers(20, 199))) / 10,
    }


def _empsit_text(case: dict, *, keep: str = "both") -> tuple[str, str]:
    name = MONTHS[case["month"] - 1]
    prior = MONTHS[case["month"] - 2]
    following = MONTHS[case["month"] % 12]
    rate = _rate_text(case["rate"])
    payroll = case["payroll"]
    up = payroll > 0
    a, b, c, d, e, f = case["decoys"]
    rate_lead = (
        f"the unemployment rate ({rate} percent)",
        f"the unemployment rate was unchanged at {rate} percent",
        f"the unemployment rate {'rose' if up else 'edged down'} to {rate} percent",
    )[case["rate_lead"]]
    payroll_lead = (
        f"Both nonfarm payroll employment ({_signed(payroll)}) and",
        f"Total nonfarm payroll employment "
        f"{'increased' if up else 'declined'} by {abs(payroll) * 1000:,} in "
        f"{name}, and",
    )[case["payroll_lead"]]
    rate_section = (
        f"Both the unemployment rate, at {rate} percent, and the number of "
        f"unemployed people, at 6.9 million, changed little in {name}.",
        f"The unemployment rate changed little at {rate} percent in {name}.",
        f"The unemployment rate increased by 0.2 percentage point to {rate} "
        f"percent in {name}.",
    )[case["rate_section"]]
    payroll_section = (
        f"Total nonfarm payroll employment changed little in {name} "
        f"({_signed(payroll)}), following an average monthly gain of {a:,},000 "
        "over the prior 12 months.",
        f"Total nonfarm payroll employment {'rose' if up else 'fell'} by "
        f"{abs(payroll) * 1000:,} in {name}, following an average monthly "
        f"gain of {a:,},000 over the prior 12 months.",
        f"Total nonfarm payroll employment edged {'up' if up else 'down'} in "
        f"{name} ({_signed(payroll)}).",
    )[case["payroll_section"]]
    if keep == "rate_lead_only":
        rate_section = "Household survey measures changed little."
    if keep == "payroll_lead_only":
        payroll_section = "Establishment survey measures changed little."
    lead = f"{payroll_lead} {rate_lead} changed little in {name}."
    decoys = (
        f"The unemployment rates for teenagers ({case['decoy_rate']:.1f} percent) "
        f"and adult men ({_rate_text(case['rate'] + Decimal('0.3'))} percent) "
        f"showed little change. Employment in health care continued its upward "
        f"trend (+{b:,},000). Retail trade lost {c:,},000 jobs in {name}.\n"
        f"The change in total nonfarm payroll employment for {prior} was "
        f"revised down by {d:,},000, from +{e:,},000 to +{f:,},000.\n"
        f"The Employment Situation for {following} is scheduled to be published."
    )
    pre = (
        f"THE EMPLOYMENT SITUATION -- {name.upper()} 2026\n\n"
        f"{lead}\n\nHousehold Survey Data\n\n{rate_section}\n\n"
        f"Establishment Survey Data\n\n{payroll_section}\n\n{decoys}"
    )
    title = f"Employment Situation Summary - 2026 M{case['month']:02d} Results"
    return title, pre


@settings(max_examples=200, deadline=None)
@given(case=_empsit())
def test_empsit_readers_return_exactly_the_headline_figures(case: dict) -> None:
    html = _page(*_empsit_text(case))
    period = f"2026-{case['month']:02d}"
    assert parse_release(html, "empsit_unemployment_rate") == (
        period,
        float(case["rate"]),
    )
    assert parse_release(html, "empsit_payroll_change") == (
        period,
        float(case["payroll"]),
    )


@settings(max_examples=100, deadline=None)
@given(case=_empsit(), other=_empsit())
def test_no_decoy_changes_what_the_empsit_readers_return(
    case: dict, other: dict
) -> None:
    moved = {**case, "decoys": other["decoys"], "decoy_rate": other["decoy_rate"]}
    for parser_id in ("empsit_unemployment_rate", "empsit_payroll_change"):
        assert parse_release(_page(*_empsit_text(case)), parser_id) == parse_release(
            _page(*_empsit_text(moved)), parser_id
        )


@settings(max_examples=100, deadline=None)
@given(case=_empsit())
def test_one_statement_alone_is_refused(case: dict) -> None:
    rate_only = _page(*_empsit_text(case, keep="rate_lead_only"))
    assert parse_release(rate_only, "empsit_unemployment_rate") is None
    payroll_only = _page(*_empsit_text(case, keep="payroll_lead_only"))
    assert parse_release(payroll_only, "empsit_payroll_change") is None


@settings(max_examples=100, deadline=None)
@given(case=_empsit(), shift=st.integers(1, 9))
def test_statements_that_disagree_are_refused(case: dict, shift: int) -> None:
    title, pre = _empsit_text({**case, "rate_section": 0, "payroll_section": 0})
    rate = _rate_text(case["rate"])
    other_rate = _rate_text(case["rate"] + Decimal(shift) / 10)
    changed = pre.replace(
        f"rate, at {rate} percent,", f"rate, at {other_rate} percent,"
    )
    assert changed != pre
    assert parse_release(_page(title, changed), "empsit_unemployment_rate") is None
    name = MONTHS[case["month"] - 1]
    payroll = _signed(case["payroll"])
    other = _signed(case["payroll"] + shift or shift + 1)
    changed = pre.replace(f"in {name} ({payroll})", f"in {name} ({other})")
    assert changed != pre
    assert parse_release(_page(title, changed), "empsit_payroll_change") is None


@settings(max_examples=100, deadline=None)
@given(case=_empsit(), offset=st.integers(1, 11))
def test_a_statement_naming_another_month_is_refused(case: dict, offset: int) -> None:
    title, pre = _empsit_text({**case, "rate_section": 1, "payroll_section": 0})
    name = MONTHS[case["month"] - 1]
    other = MONTHS[(case["month"] - 1 + offset) % 12]
    rate = _rate_text(case["rate"])
    changed = pre.replace(
        f"at {rate} percent in {name}.", f"at {rate} percent in {other}."
    )
    assert changed != pre
    assert parse_release(_page(title, changed), "empsit_unemployment_rate") is None
    changed = pre.replace(f"changed little in {name} (", f"changed little in {other} (")
    assert changed != pre
    assert parse_release(_page(title, changed), "empsit_payroll_change") is None


@settings(max_examples=50, deadline=None)
@given(case=_empsit(), offset=st.integers(1, 11))
def test_a_heading_month_the_title_does_not_name_is_refused(
    case: dict, offset: int
) -> None:
    title, pre = _empsit_text(case)
    name = MONTHS[case["month"] - 1].upper()
    other = MONTHS[(case["month"] - 1 + offset) % 12].upper()
    changed = pre.replace(f"-- {name} 2026", f"-- {other} 2026")
    for parser_id in ("empsit_unemployment_rate", "empsit_payroll_change"):
        assert parse_release(_page(title, changed), parser_id) is None


@pytest.mark.parametrize("pres", (0, 2))
def test_a_page_without_exactly_one_preformatted_block_is_refused(pres: int) -> None:
    case = {
        "month": 7,
        "rate": Decimal("4.1"),
        "payroll": -23,
        "rate_lead": 0,
        "rate_section": 0,
        "payroll_lead": 0,
        "payroll_section": 0,
        "decoys": [34, 22, 19, 66, 129, 63],
        "decoy_rate": Decimal("12.1"),
    }
    title, pre = _empsit_text(case)
    assert parse_release(_page(title, pre), "empsit_payroll_change") == (
        "2026-07",
        -23.0,
    )
    for parser_id in PROSE_PARSERS:
        assert parse_release(_page(title, pre, pres=pres), parser_id) is None


def test_a_duplicated_title_or_another_release_title_is_refused() -> None:
    case = {
        "month": 7,
        "rate": Decimal("4.1"),
        "payroll": -23,
        "rate_lead": 0,
        "rate_section": 0,
        "payroll_lead": 0,
        "payroll_section": 0,
        "decoys": [34, 22, 19, 66, 129, 63],
        "decoy_rate": Decimal("12.1"),
    }
    title, pre = _empsit_text(case)
    html = _page(title, pre)
    doubled = html.replace("</head>", f"<title>{title}</title></head>")
    other = html.replace("Employment Situation Summary", "Real Earnings Summary")
    for parser_id in ("empsit_unemployment_rate", "empsit_payroll_change"):
        assert parse_release(html, parser_id) is not None
        assert parse_release(doubled, parser_id) is None
        assert parse_release(other, parser_id) is None


@pytest.mark.parametrize("printed", ("23,500", "23,000.5", "1.1 million", "23000"))
def test_a_payroll_change_not_printed_to_the_thousand_is_not_a_statement(
    printed: str,
) -> None:
    pre = (
        "THE EMPLOYMENT SITUATION -- JULY 2026\n"
        f"Total nonfarm payroll employment rose by {printed} in July. "
        f"Total nonfarm payroll employment changed little in July (+{printed})."
    )
    html = _page("Employment Situation Summary - 2026 M07 Results", pre)
    assert parse_release(html, "empsit_payroll_change") is None


@pytest.mark.parametrize("printed", ("143,000,500", "143,000.5", "143,0001"))
def test_a_longer_number_is_never_read_as_its_thousands_prefix(printed: str) -> None:
    # Two agreeing statements, so only the number's own shape can refuse.
    pre = (
        "THE EMPLOYMENT SITUATION -- JULY 2026\n"
        f"Total nonfarm payroll employment rose by {printed} in July. "
        f"Total nonfarm payroll employment increased by {printed} in July."
    )
    html = _page("Employment Situation Summary - 2026 M07 Results", pre)
    assert parse_release(html, "empsit_payroll_change") is None
    whole = html.replace(printed, "143,000")
    assert parse_release(whole, "empsit_payroll_change") == ("2026-07", 143.0)


def test_the_sign_of_a_payroll_change_follows_its_verb_or_its_printed_sign() -> None:
    title = "Employment Situation Summary - 2026 M09 Results"
    for verb, sign in (
        ("rose", 1),
        ("increased", 1),
        ("grew", 1),
        ("edged up", 1),
        ("declined", -1),
        ("decreased", -1),
        ("fell", -1),
        ("edged down", -1),
    ):
        pre = (
            "THE EMPLOYMENT SITUATION -- SEPTEMBER 2026\n"
            f"Total nonfarm payroll employment {verb} by 41,000 in September. "
            f"Total nonfarm payroll employment {verb} in September "
            f"({'+' if sign > 0 else '-'}41,000)."
        )
        assert parse_release(_page(title, pre), "empsit_payroll_change") == (
            "2026-09",
            41.0 * sign,
        )


@st.composite
def _jolts(draw: st.DrawFn) -> dict:
    return {
        "month": draw(st.integers(1, 12)),
        "openings": Decimal(draw(st.integers(30, 150))) / 10,
        "rate": Decimal(draw(st.integers(20, 80))) / 10,
        "revised": Decimal(draw(st.integers(30, 150))) / 10,
        "lead": draw(st.integers(0, 2)),
        "dash": draw(st.sampled_from(("-", "--", "—", "�"))),
    }


def _jolts_page(case: dict, *, second: bool = True) -> str:
    name = MONTHS[case["month"] - 1]
    prior = MONTHS[case["month"] - 2]
    openings = f"{case['openings']:.1f}"
    lead = (
        f"The number of job openings was little changed at {openings} million "
        f"in {name}, the U.S. Bureau of Labor Statistics reported today.",
        f"The number of job openings {'rose' if case['month'] % 2 else 'fell'} "
        f"to {openings} million in {name}.",
        f"The number of job openings decreased by 300,000 to {openings} million "
        f"in {name}.",
    )[case["lead"]]
    section = (
        f"The number and rate of job openings were little changed at {openings} "
        f"million and {case['rate']:.1f} percent, respectively, in {name}."
        if second
        else "Job openings changed little in most industries."
    )
    pre = (
        f"JOB OPENINGS AND LABOR TURNOVER {case['dash']} {name.upper()} 2026\n\n"
        f"{lead} Hires were unchanged at 5.3 million. Within separations, quits "
        "(3.2 million) were unchanged.\n\nJob Openings\n\n"
        f"{section}\n\n{prior} 2026 Revisions\n\n"
        f"The number of job openings for {prior} was revised down by 57,000 to "
        f"{case['revised']:.1f} million."
    )
    title = (
        f"Job Openings and Labor Turnover Summary - 2026 M{case['month']:02d} Results"
    )
    return _page(title, pre)


@settings(max_examples=200, deadline=None)
@given(case=_jolts())
def test_jolts_openings_reader_returns_the_printed_millions_figure(case: dict) -> None:
    assert parse_release(_jolts_page(case), "jolts_job_openings") == (
        f"2026-{case['month']:02d}",
        float(case["openings"]),
    )


@settings(max_examples=100, deadline=None)
@given(case=_jolts())
def test_jolts_openings_one_statement_or_a_disagreement_is_refused(
    case: dict,
) -> None:
    assert parse_release(_jolts_page(case, second=False), "jolts_job_openings") is None
    openings = f"{case['openings']:.1f}"
    other = f"{case['openings'] + Decimal('0.1'):.1f}"
    html = _jolts_page(case).replace(
        f"changed at {openings} million and", f"changed at {other} million and"
    )
    assert parse_release(html, "jolts_job_openings") is None


@settings(max_examples=100, deadline=None)
@given(case=_jolts(), other=_jolts())
def test_jolts_openings_revised_month_never_leaks(case: dict, other: dict) -> None:
    assume(case["revised"] != other["revised"])
    moved = {**case, "revised": other["revised"]}
    assert parse_release(_jolts_page(case), "jolts_job_openings") == parse_release(
        _jolts_page(moved), "jolts_job_openings"
    )


def test_each_prose_reader_refuses_the_other_summary_page() -> None:
    jolts = _jolts_page(
        {
            "month": 6,
            "openings": Decimal("7.4"),
            "rate": Decimal("4.4"),
            "revised": Decimal("7.5"),
            "lead": 0,
            "dash": "�",
        }
    )
    assert parse_release(jolts, "jolts_job_openings") == ("2026-06", 7.4)
    for parser_id in ("empsit_unemployment_rate", "empsit_payroll_change"):
        assert parse_release(jolts, parser_id) is None
