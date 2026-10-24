"""The prose readers for the Employment Situation and JOLTS summary pages.

empsit.nr0.htm and jolts.nr0.htm print no table: the release is one
preformatted block of prose (see the real captures in
tests/fixtures/release_capture/). These tests generate such releases from
the phrasings BLS uses, with decoys BLS prints beside the headline figure
(revised earlier months, the average monthly gain, private payrolls,
subgroup rates, industry changes), and check that the reader returns exactly
the headline figure or refuses. Values are synthetic; no target-month
release is quoted.

Invariants, for every generated release:
- the reader returns (release month, headline figure), exactly;
- no decoy changes what it returns, whatever its numbers and wherever it
  sits;
- one statement alone, two statements that disagree, a headline statement
  naming another month or year, a payroll verb that contradicts its printed
  sign, a title and heading that disagree, or a page without exactly one
  preformatted block is refused (None), never guessed.
"""

from __future__ import annotations

import pathlib
import re
import sys
from dataclasses import replace
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
_EMPSIT_IDS = ("empsit_unemployment_rate", "empsit_payroll_change")


def _page(title: str, pre: str, *, pres: int = 1) -> str:
    blocks = "".join(f"<pre>\n{pre}\n</pre>" for _ in range(pres))
    return (
        f"<html><head><title>{title}</title></head><body>"
        f"<div><p>Navigation</p></div>{blocks}<p>Footer</p></body></html>"
    )


def _signed(thousands: int) -> str:
    return f"{thousands * 1000:+,}"


def _count(thousands: int) -> str:
    return f"{abs(thousands) * 1000:,}"


# Sentences BLS prints beside the headline figures. None is a statement of
# this month's headline: each names a subgroup, an industry, private
# payrolls, an average, a revised earlier month, or its month only before
# its subject. Fields: name, prior (the month before), n (numbers), r (a rate).
_DECOYS = (
    "The unemployment rates for teenagers ({r} percent) and adult men "
    "({r} percent) showed little change.",
    "The unemployment rate for Black workers ({r} percent) changed little in "
    "{name}.",
    "In {prior}, the unemployment rate was {r} percent.",
    "Employment in health care continued its upward trend (+{n[0]:,},000).",
    "Retail trade lost {n[1]:,},000 jobs in {name}.",
    "Private nonfarm payroll employment rose by {n[2]:,},000 in {name}.",
    "Total nonfarm payroll employment rose by {n[3]:,},000 per month, on "
    "average, over the prior 12 months.",
    "Total nonfarm payroll employment has increased by an average of "
    "{n[4]:,},000 per month since January.",
    "The change in total nonfarm payroll employment for {prior} was revised "
    "down by {n[5]:,},000, from +{n[6]:,},000 to +{n[7]:,},000.",
)


@st.composite
def _empsit(draw: st.DrawFn) -> dict:
    return {
        "month": draw(st.integers(1, 12)),
        "rate": Decimal(draw(st.integers(20, 99))) / 10,
        "payroll": draw(st.integers(-999, 999).filter(lambda value: value != 0)),
        "lead": draw(st.integers(0, 3)),
        "rate_section": draw(st.integers(0, 5)),
        "payroll_section": draw(st.integers(0, 3)),
        "numbers": draw(st.lists(st.integers(1, 999), min_size=8, max_size=8)),
        "decoy_rate": Decimal(draw(st.integers(20, 199))) / 10,
        "order": draw(st.permutations(range(len(_DECOYS)))),
    }


def _empsit_text(case: dict, *, keep: str = "both") -> tuple[str, str]:
    name = MONTHS[case["month"] - 1]
    prior = MONTHS[case["month"] - 2]
    following = MONTHS[case["month"] % 12]
    rate = f"{case['rate']:.1f}"
    payroll = case["payroll"]
    up = payroll > 0
    signed, count = _signed(payroll), _count(payroll)
    lead = (
        f"Both nonfarm payroll employment ({signed}) and the unemployment rate "
        f"({rate} percent) changed little in {name}, the U.S. Bureau of Labor "
        "Statistics reported today.",
        f"Total nonfarm payroll employment {'increased' if up else 'declined'} "
        f"by {count} in {name}, and the unemployment rate changed little at "
        f"{rate} percent, the U.S. Bureau of Labor Statistics reported today.",
        f"Total nonfarm payroll employment changed little in {name} ({signed}), "
        f"and the unemployment rate was little changed at {rate} percent.",
        f"Total nonfarm payroll employment edged {'up' if up else 'down'} by "
        f"{count} in {name}, while the unemployment rate "
        f"{'edged down' if up else 'rose'} to {rate} percent.",
    )[case["lead"]]
    rate_section = (
        f"Both the unemployment rate, at {rate} percent, and the number of "
        f"unemployed people, at 6.9 million, changed little in {name}.",
        f"The unemployment rate changed little at {rate} percent in {name}.",
        f"The unemployment rate increased by 0.2 percentage point to {rate} "
        f"percent in {name}.",
        f"The unemployment rate and the number of unemployed people were little "
        f"changed at {rate} percent and 6.9 million, respectively, in {name}.",
        f"The unemployment rate, at {rate} percent, changed little in {name}.",
        f"The unemployment rate ({rate} percent) and the number of unemployed "
        f"people (6.9 million) changed little in {name}.",
    )[case["rate_section"]]
    a = case["numbers"][0]
    payroll_section = (
        f"Total nonfarm payroll employment changed little in {name} ({signed}), "
        f"following an average monthly gain of {a:,},000 over the prior 12 "
        "months.",
        f"Total nonfarm payroll employment {'rose' if up else 'fell'} by {count} "
        f"in {name}, following an average monthly gain of {a:,},000 over the "
        "prior 12 months.",
        f"Total nonfarm payroll employment edged {'up' if up else 'down'} in "
        f"{name} ({signed}).",
        f"Total nonfarm payroll employment ({signed}) was little changed in "
        f"{name}.",
    )[case["payroll_section"]]
    if keep == "rate_lead_only":
        rate_section = "Household survey measures changed little."
    if keep == "payroll_lead_only":
        payroll_section = "Establishment survey measures changed little."
    decoys = " ".join(
        _DECOYS[i].format(
            name=name, prior=prior, n=case["numbers"], r=f"{case['decoy_rate']:.1f}"
        )
        for i in case["order"]
    )
    pre = (
        f"THE EMPLOYMENT SITUATION -- {name.upper()} 2026\n\n"
        f"{lead}\n\nHousehold Survey Data\n\n{rate_section}\n\n"
        f"Establishment Survey Data\n\n{payroll_section}\n\n{decoys}\n\n"
        f"The Employment Situation for {following} is scheduled to be released."
    )
    title = f"Employment Situation Summary - 2026 M{case['month']:02d} Results"
    return title, pre


def _readings(case: dict) -> dict[str, tuple[str, float]]:
    period = f"2026-{case['month']:02d}"
    return {
        "empsit_unemployment_rate": (period, float(case["rate"])),
        "empsit_payroll_change": (period, float(case["payroll"])),
    }


_JULY = {
    "month": 7,
    "rate": Decimal("4.1"),
    "payroll": -23,
    "lead": 0,
    "rate_section": 0,
    "payroll_section": 0,
    "numbers": [34, 22, 19, 41, 30, 66, 129, 63],
    "decoy_rate": Decimal("12.1"),
    "order": list(range(len(_DECOYS))),
}


@settings(max_examples=300, deadline=None)
@given(case=_empsit())
def test_empsit_readers_return_exactly_the_headline_figures(case: dict) -> None:
    html = _page(*_empsit_text(case))
    for parser_id, reading in _readings(case).items():
        assert parse_release(html, parser_id) == reading


@settings(max_examples=150, deadline=None)
@given(case=_empsit(), other=_empsit())
def test_no_decoy_changes_what_the_empsit_readers_return(
    case: dict, other: dict
) -> None:
    moved = {
        **case,
        "numbers": other["numbers"],
        "decoy_rate": other["decoy_rate"],
        "order": other["order"],
    }
    for parser_id in _EMPSIT_IDS:
        assert parse_release(_page(*_empsit_text(case)), parser_id) == parse_release(
            _page(*_empsit_text(moved)), parser_id
        )


@settings(max_examples=150, deadline=None)
@given(case=_empsit(), at=st.integers(0, 3))
def test_a_decoy_anywhere_never_changes_what_the_empsit_readers_return(
    case: dict, at: int
) -> None:
    title, pre = _empsit_text(case)
    paragraphs = pre.split("\n\n")
    decoys = paragraphs.pop(-2)
    # After the heading, before each section's heading, or at the end.
    paragraphs.insert((1, 2, 4, len(paragraphs))[at], decoys)
    moved = _page(title, "\n\n".join(paragraphs))
    for parser_id, reading in _readings(case).items():
        assert parse_release(moved, parser_id) == reading


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
    rate = f"{case['rate']:.1f}"
    other_rate = f"{case['rate'] + Decimal(shift) / 10:.1f}"
    changed = pre.replace(
        f"rate, at {rate} percent,", f"rate, at {other_rate} percent,"
    )
    assert changed != pre
    assert parse_release(_page(title, changed), "empsit_unemployment_rate") is None
    name = MONTHS[case["month"] - 1]
    payroll = _signed(case["payroll"])
    other = _signed(case["payroll"] + shift or shift + 1)
    changed = pre.replace(
        f"in {name} ({payroll}), following", f"in {name} ({other}), following"
    )
    assert changed != pre
    assert parse_release(_page(title, changed), "empsit_payroll_change") is None


def _section_month(pre: str, name: str, other: str, section: str) -> str:
    """The release with one section's statement moved to another month."""
    head, rest = pre.split(f"\n\n{section}\n\n", 1)
    statement, tail = rest.split("\n\n", 1)
    moved = re.sub(rf"\bin {name}\b", f"in {other}", statement, count=1)
    assert moved != statement
    return f"{head}\n\n{section}\n\n{moved}\n\n{tail}"


@settings(max_examples=200, deadline=None)
@given(case=_empsit(), offset=st.integers(1, 11))
def test_a_headline_statement_naming_another_month_is_refused(
    case: dict, offset: int
) -> None:
    title, pre = _empsit_text(case)
    name = MONTHS[case["month"] - 1]
    other = MONTHS[(case["month"] - 1 + offset) % 12]
    rate = _section_month(pre, name, other, "Household Survey Data")
    assert parse_release(_page(title, rate), "empsit_unemployment_rate") is None
    payroll = _section_month(pre, name, other, "Establishment Survey Data")
    assert parse_release(_page(title, payroll), "empsit_payroll_change") is None


@settings(max_examples=100, deadline=None)
@given(case=_empsit(), year=st.integers(2000, 2030).filter(lambda y: y != 2026))
def test_a_headline_statement_naming_another_year_is_refused(
    case: dict, year: int
) -> None:
    title, pre = _empsit_text(case)
    name = MONTHS[case["month"] - 1]
    for section, parser_id in (
        ("Household Survey Data", "empsit_unemployment_rate"),
        ("Establishment Survey Data", "empsit_payroll_change"),
    ):
        moved = _section_month(pre, name, f"{name} {year}", section)
        assert parse_release(_page(title, moved), parser_id) is None
        same = _section_month(pre, name, f"{name} 2026", section)
        assert parse_release(_page(title, same), parser_id) == _readings(case)[
            parser_id
        ]


def test_previous_month_statements_never_supply_the_rate() -> None:
    """Round-2 review, finding 1: June statements in a July release."""
    title = "Employment Situation Summary - 2026 M07 Results"
    pre = (
        "THE EMPLOYMENT SITUATION -- JULY 2026\n"
        "The unemployment rate and the number of unemployed people were "
        "unchanged at 4.1 percent and 6.9 million, respectively, in July.\n"
        "The unemployment rate (4.8 percent) changed little in June.\n"
        "The unemployment rate, at 4.8 percent, was unchanged in June."
    )
    assert parse_release(_page(title, pre), "empsit_unemployment_rate") is None
    july = pre.replace("in June", "in July").replace("4.8", "4.1")
    assert parse_release(_page(title, july), "empsit_unemployment_rate") == (
        "2026-07",
        4.1,
    )


@pytest.mark.parametrize(
    "subject",
    (
        "Private nonfarm payroll employment",
        "Private-sector nonfarm payroll employment",
        "In July, total nonfarm payroll employment",
        "Employment in total nonfarm payroll employment",
    ),
)
def test_a_payroll_measure_other_than_the_total_is_never_a_statement(
    subject: str,
) -> None:
    """Round-2 review, finding 2: the subject must be the total, whole."""
    title = "Employment Situation Summary - 2026 M07 Results"
    pre = (
        "THE EMPLOYMENT SITUATION -- JULY 2026\n"
        f"{subject} rose by 123,000 in July. "
        f"{subject} increased by 123,000 in July."
    )
    assert parse_release(_page(title, pre), "empsit_payroll_change") is None
    total = pre.replace(subject, "Total nonfarm payroll employment")
    assert parse_release(_page(title, total), "empsit_payroll_change") == (
        "2026-07",
        123.0,
    )


def test_a_page_without_exactly_one_preformatted_block_is_refused() -> None:
    title, pre = _empsit_text(_JULY)
    assert parse_release(_page(title, pre), "empsit_payroll_change") == (
        "2026-07",
        -23.0,
    )
    for pres in (0, 2):
        for parser_id in PROSE_PARSERS:
            assert parse_release(_page(title, pre, pres=pres), parser_id) is None


@settings(max_examples=50, deadline=None)
@given(case=_empsit(), offset=st.integers(1, 11))
def test_a_heading_month_the_title_does_not_name_is_refused(
    case: dict, offset: int
) -> None:
    title, pre = _empsit_text(case)
    name = MONTHS[case["month"] - 1].upper()
    other = MONTHS[(case["month"] - 1 + offset) % 12].upper()
    changed = pre.replace(f"-- {name} 2026", f"-- {other} 2026")
    for parser_id in _EMPSIT_IDS:
        assert parse_release(_page(title, changed), parser_id) is None


def test_a_duplicated_title_or_another_release_title_is_refused() -> None:
    title, pre = _empsit_text(_JULY)
    html = _page(title, pre)
    doubled = html.replace("</head>", f"<title>{title}</title></head>")
    other = html.replace("Employment Situation Summary", "Real Earnings Summary")
    for parser_id in _EMPSIT_IDS:
        assert parse_release(html, parser_id) is not None
        assert parse_release(doubled, parser_id) is None
        assert parse_release(other, parser_id) is None


def test_two_forms_matching_one_sentence_count_as_one_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = PROSE_PARSERS["empsit_payroll_change"]
    doubled = replace(spec, statements=spec.statements + spec.statements[:1])
    monkeypatch.setitem(PROSE_PARSERS, "empsit_payroll_change", doubled)
    title = "Employment Situation Summary - 2026 M07 Results"
    once = (
        "THE EMPLOYMENT SITUATION -- JULY 2026\n"
        "Total nonfarm payroll employment changed little in July (-23,000)."
    )
    assert parse_release(_page(title, once), "empsit_payroll_change") is None
    twice = f"{once} Total nonfarm payroll employment fell by 23,000 in July."
    assert parse_release(_page(title, twice), "empsit_payroll_change") == (
        "2026-07",
        -23.0,
    )


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


@pytest.mark.parametrize(
    ("verb", "sign"),
    (
        ("rose", 1),
        ("increased", 1),
        ("grew", 1),
        ("edged up", 1),
        ("declined", -1),
        ("decreased", -1),
        ("fell", -1),
        ("edged down", -1),
    ),
)
def test_the_sign_of_a_payroll_change_follows_its_verb_or_its_printed_sign(
    verb: str, sign: int
) -> None:
    title = "Employment Situation Summary - 2026 M09 Results"
    printed = f"{'+' if sign > 0 else '-'}41,000"
    pre = (
        "THE EMPLOYMENT SITUATION -- SEPTEMBER 2026\n"
        f"Total nonfarm payroll employment {verb} by 41,000 in September. "
        f"Total nonfarm payroll employment {verb} in September ({printed})."
    )
    assert parse_release(_page(title, pre), "empsit_payroll_change") == (
        "2026-09",
        41.0 * sign,
    )
    # A verb that contradicts its printed sign says two things: refused.
    flipped = pre.replace(f"({printed})", f"({'-' if sign > 0 else '+'}41,000)")
    assert parse_release(_page(title, flipped), "empsit_payroll_change") is None


def test_a_unicode_minus_is_a_minus() -> None:
    title = "Employment Situation Summary - 2026 M07 Results"
    pre = (
        "THE EMPLOYMENT SITUATION -- JULY 2026\n"
        "Total nonfarm payroll employment changed little in July (−23,000). "
        "Total nonfarm payroll employment (&#8722;23,000) was little changed "
        "in July."
    )
    assert parse_release(_page(title, pre), "empsit_payroll_change") == (
        "2026-07",
        -23.0,
    )


@st.composite
def _jolts(draw: st.DrawFn) -> dict:
    return {
        "month": draw(st.integers(1, 12)),
        "openings": Decimal(draw(st.integers(30, 150))) / 10,
        "rate": Decimal(draw(st.integers(20, 80))) / 10,
        "revised": Decimal(draw(st.integers(30, 150))) / 10,
        "lead": draw(st.integers(0, 3)),
        "dash": draw(st.sampled_from(("-", "--", "—", "�"))),
    }


def _jolts_page(case: dict, *, second: bool = True, month: str | None = None) -> str:
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
        f"The number of job openings was little changed at {openings} million "
        f"on the last business day of {name}, the U.S. Bureau of Labor "
        "Statistics reported today.",
    )[case["lead"]]
    section = (
        f"The number and rate of job openings were little changed at {openings} "
        f"million and {case['rate']:.1f} percent, respectively, in "
        f"{month or name}."
        if second
        else "Job openings changed little in most industries."
    )
    pre = (
        f"JOB OPENINGS AND LABOR TURNOVER {case['dash']} {name.upper()} 2026\n\n"
        f"{lead} Hires were unchanged at 5.3 million. Within separations, quits "
        "(3.2 million) were unchanged.\n\nJob Openings\n\n"
        f"{section} The number of job openings increased in federal government "
        f"(+39,000).\n\n{prior} 2026 Revisions\n\n"
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
@given(case=_jolts(), offset=st.integers(1, 11))
def test_jolts_openings_statement_naming_another_month_is_refused(
    case: dict, offset: int
) -> None:
    other = MONTHS[(case["month"] - 1 + offset) % 12]
    assert parse_release(_jolts_page(case, month=other), "jolts_job_openings") is None


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
    for parser_id in _EMPSIT_IDS:
        assert parse_release(jolts, parser_id) is None
    empsit = _page(*_empsit_text(_JULY))
    assert parse_release(empsit, "jolts_job_openings") is None
