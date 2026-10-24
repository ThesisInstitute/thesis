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
- where the release first names the measure after its heading (its lead),
  a dated statement of the month must hold that mention, and every other
  dated statement must agree with it: so whatever else a page holds, the
  reader returns the lead's figure or nothing;
- the release opens with that statement: between the heading and it lie
  only the release's other dated statements of the month, so a label or
  any other text there ("Not seasonally adjusted:") refuses the page;
- no decoy after the lead changes what it returns, whatever its numbers
  and wherever it sits;
- after its month a statement holds only a tail, then optionally "the U.S.
  Bureau of Labor Statistics reported today", then its full stop. A tail
  is one of a few closed forms, by the clause the statement ends with: a
  comparison, opening with a comma and naming what it compares with (a
  figure, a change, an average or a trend) and then that operand's own
  period ("following a gain of 166,000 in June", never "compared with a
  year earlier"); the trend since another period ("and has shown little
  change since April"); after a rate, the number unemployed or the
  population-control note; after a rate or the openings level, its change
  over the year. A comparison or trend naming the release month itself is
  no tail;
- every comparison, trend or change that the 32 real Employment Situation
  and JOLTS summary captures print after any measure's month is a tail, or
  is listed as excluded with its reason;
- anything else after the month (another period, subgroup, basis or
  measure: ", a year earlier", "after seasonal adjustment", "the U.S.
  rate", "after including discouraged workers", ", and by 120,000 for the
  month") makes the sentence no statement, which neither supplies the
  figure nor refuses the page;
- the parser reads a tail exactly when a second, plain-Python reading of
  the closed forms does;
- no tail, whatever other figures, months or years it holds, changes what
  a statement says;
- a statement that leaves its month unsaid only corroborates: the undated
  statements count only when every one states the figure the dated
  statements state, so what is read is always what a dated statement says,
  and no undated statement (an annual average, a revision note) refuses
  the page;
- one statement alone, two dated statements that disagree, a headline
  statement naming another month or year, a payroll verb that contradicts
  its printed sign (in the payroll statement or in the payroll clause a
  rate statement leans on, or one leaning on a rate statement), a title and
  heading that disagree, or a page without exactly one preformatted block
  (one inside a comment is none) is refused (None), never guessed.
"""

from __future__ import annotations

import gzip
import pathlib
import re
import sys
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import assume, event, given, settings
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import legacy_release_parsers  # noqa: E402
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
# payrolls, an average, a revised earlier month, a qualifier after its month
# (another period, subgroup or basis), its subject only in lower case, or no
# verb (a caption). Fields: name, prior (the month before), n (numbers), r
# (a rate).
_DECOYS = (
    "The unemployment rates for teenagers ({r} percent) and adult men "
    "({r} percent) showed little change.",
    "The unemployment rate for Black workers ({r} percent) changed little in {name}.",
    "In {prior}, the unemployment rate for teenagers was {r} percent.",
    "In {prior}, total nonfarm payroll employment rose by {n[3]:,},000.",
    "Employment in health care continued its upward trend (+{n[0]:,},000).",
    "Retail trade lost {n[1]:,},000 jobs in {name}.",
    "Private nonfarm payroll employment rose by {n[2]:,},000 in {name}.",
    "Total nonfarm payroll employment rose by {n[3]:,},000 per month, on "
    "average, over the prior 12 months.",
    "Total nonfarm payroll employment has increased by an average of "
    "{n[4]:,},000 per month since January.",
    "The change in total nonfarm payroll employment for {prior} was revised "
    "down by {n[5]:,},000, from +{n[6]:,},000 to +{n[7]:,},000.",
    "Total nonfarm payroll employment rose by {n[2]:,},000 in {name} of last year.",
    "The unemployment rate was {r} percent in {name} a year earlier.",
    "Nonfarm payroll employment in {name} (+{n[1]:,},000) by industry is "
    "shown in table B-1.",
    # Round-3 review, finding 1.
    "The unemployment rate was {r} percent in {name}, a year earlier.",
    "The unemployment rate ({r} percent) was unchanged in {name} (2025).",
    "The unemployment rate ({r} percent) changed little in {name} (among teenagers).",
    "The unemployment rate ({r} percent) was little changed in {name} (not "
    "seasonally adjusted).",
    "Total nonfarm payroll employment rose by {n[2]:,},000 in {name}, a year earlier.",
    "Total nonfarm payroll employment changed little in {name} (+{n[3]:,},000) "
    "(not seasonally adjusted).",
    "Total nonfarm payroll employment rose by {n[4]:,},000 in {name}, and the "
    "unemployment rate was little changed at {r} percent in {prior}.",
    "The unemployment rate was {r} percent in {name}, before seasonal adjustment.",
    "Chart 1. The unemployment rate ({r} percent) in {name}.",
    "Chart 2. Total nonfarm payroll employment (+{n[5]:,},000) in {name}.",
)


@st.composite
def _empsit(draw: st.DrawFn) -> dict:
    return {
        "month": draw(st.integers(1, 12)),
        "rate": Decimal(draw(st.integers(20, 99))) / 10,
        "payroll": draw(st.integers(-999, 999).filter(lambda value: value != 0)),
        "lead": draw(st.integers(0, 6)),
        "rate_section": draw(st.integers(0, 11)),
        "payroll_section": draw(st.integers(0, 10)),
        "heading_upper": draw(st.booleans()),
        "m13": draw(st.booleans()),
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
        f"Total nonfarm payroll employment changed little ({signed}) in {name}, "
        f"and the unemployment rate rose 0.1 percentage point to {rate} percent, "
        "the U.S. Bureau of Labor Statistics reported today.",
        f"The unemployment rate {'edged down' if up else 'rose'} to {rate} percent "
        f"in {name}, and nonfarm payroll employment edged "
        f"{'up' if up else 'down'} by {count}, the U.S. Bureau of Labor "
        "Statistics reported today.",
        f"The unemployment rate was little changed at {rate} percent in {name}, "
        f"while nonfarm payroll employment changed little ({signed}), the U.S. "
        "Bureau of Labor Statistics reported today.",
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
        f"In {name}, the unemployment rate was unchanged at {rate} percent.",
        f"The unemployment rate was {rate} percent in {name} and has remained in "
        f"a narrow range of 4.0 percent to 4.2 percent since {prior} 2024.",
        f"In {name}, the unemployment rate, at {rate} percent, changed little, "
        "and the number of unemployed people was little changed at 6.9 million.",
        f"The unemployment rate stood at {rate} percent in {name}, compared with "
        f"{case['decoy_rate']:.1f} percent a year earlier.",
        f"The unemployment rate was {rate} percent in {name} and has remained at "
        f"either {case['decoy_rate']:.1f} percent or {rate} percent since {prior}.",
        # The month unsaid: a supporting statement.
        f"The unemployment rate held at {rate} percent and has remained in a "
        f"narrow range of 4.0 percent to 4.5 percent since {prior} 2025.",
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
        f"Total nonfarm payroll employment ({signed}) was little changed in {name}.",
        f"Total nonfarm payroll employment changed little ({signed}) in {name} "
        f"and has shown little change since {prior}.",
        f"Total nonfarm payroll employment {'increased' if up else 'decreased'} "
        f"by {count} in {name} and continued to trend {'up' if up else 'down'}.",
        f"Total nonfarm payroll employment changed little in {name} ({signed}), "
        f"following little change in {prior} (+{a:,},000).",
        f"Total nonfarm payroll employment {'rose' if up else 'fell'} {count} in "
        f"{name}, compared with an average monthly gain of {a:,},000 in 2025.",
        # The month unsaid: a supporting statement.
        f"Total nonfarm payroll employment {'increased' if up else 'decreased'} "
        f"by {count} over the month.",
        f"Total nonfarm payroll employment changed little in {name} ({signed}), "
        "roughly in line with the average monthly change over the prior 12 "
        f"months (+{a:,},000).",
        f"Total nonfarm payroll employment edged {'up' if up else 'down'} by "
        f"{count} in {name} but has shown little change since {prior}.",
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
    # BLS prints the heading's month in capitals, once ("March 2026") not.
    heading = name.upper() if case["heading_upper"] else name
    pre = (
        f"THE EMPLOYMENT SITUATION -- {heading} 2026\n\n"
        f"{lead}\n\nHousehold Survey Data\n\n{rate_section}\n\n"
        f"Establishment Survey Data\n\n{payroll_section}\n\n{decoys}\n\n"
        f"The Employment Situation for {following} is scheduled to be released."
    )
    # The December release is titled "M13".
    code = 13 if case["month"] == 12 and case["m13"] else case["month"]
    title = f"Employment Situation Summary - 2026 M{code:02d} Results"
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
    "heading_upper": True,
    "m13": False,
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
    # After the lead, after each section's heading, or at the end.
    moved = paragraphs.copy()
    moved.insert((2, 3, 5, len(moved))[at], decoys)
    for parser_id, reading in _readings(case).items():
        assert parse_release(_page(title, "\n\n".join(moved)), parser_id) == reading
    # Before the lead, a decoy is where the release first names the measure,
    # and it is no statement of the month: refused.
    first = paragraphs.copy()
    first.insert(1, decoys)
    for parser_id in _EMPSIT_IDS:
        assert parse_release(_page(title, "\n\n".join(first)), parser_id) is None


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


def _section_month(pre: str, name: str, other: str, section: str) -> str | None:
    """The release with one section's statement moved to another month.

    None when the statement leaves its month unsaid.
    """
    head, rest = pre.split(f"\n\n{section}\n\n", 1)
    statement, tail = rest.split("\n\n", 1)
    moved = re.sub(rf"\b([Ii]n) {name}\b", rf"\1 {other}", statement, count=1)
    if moved == statement:
        return None
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
    payroll = _section_month(pre, name, other, "Establishment Survey Data")
    assume(rate is not None and payroll is not None)
    assert parse_release(_page(title, rate), "empsit_unemployment_rate") is None
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
        same = _section_month(pre, name, f"{name} 2026", section)
        if moved is None or same is None:
            continue
        assert parse_release(_page(title, moved), parser_id) is None
        assert (
            parse_release(_page(title, same), parser_id) == _readings(case)[parser_id]
        )


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


@pytest.mark.parametrize(
    "qualifier",
    (
        ", a year earlier",
        " (2025)",
        " (among teenagers)",
        " (not seasonally adjusted)",
        " of last year",
        ", before seasonal adjustment",
        ", a year earlier, compared with 3.9 percent",
        " for the second consecutive month among adult women",
        # Round-5 review, finding 1: "and/but was" opens no tail unless the
        # clause is a change ("but was down by ..."), and no tail may speak
        # to the statement's own basis, scope or revision.
        " but was 4.0 percent a year earlier",
        " and is 4.0 percent for adults",
        " and were 4.0 percent",
        " and was not seasonally adjusted",
        ", after seasonal adjustment",
        ", compared with 3.9 percent on a seasonally adjusted basis",
        ", following 3.9 percent before seasonal adjustment",
        ", above the national rate",
        ", similar to the rate among adults",
        ", compared with 3.9 percent overall",
        ", following revisions to May and June",
        " and has remained unchanged after revision",
        ", up from 3.9 percent unadjusted",
        # "Before" opens no tail: the figure before an adjustment is another.
        ", before the annual population control adjustments",
        ", after excluding the population control adjustments",
        " and has remained there for adult men since May",
        # Round-6 review: an abbreviation ends no tail early, and a tail is a
        # closed form, so no measure, period or scope follows.
        ", compared with the U.S. rate of 4.1 percent on a seasonally adjusted basis",
        ", compared with the U.S. rate of 4.1 percent",
        ", after including discouraged workers in the labor force",
        ", after averaging the latest three months",
        " and is 4.1 percent",
        ", the U.S. Bureau of Labor Statistics reported today on an adjusted basis",
        # "Before" opens no tail even when what follows is a comparison's:
        # the figure before a change is another figure.
        ", before a change of 0.3 percentage point",
        ", before the change",
        # Round-7 review, finding 1: a comparison with a bare period.
        ", compared with a year earlier",
        " compared with the previous year",
        ", up from a year earlier",
    ),
)
def test_a_statement_qualified_after_its_month_is_not_read(qualifier: str) -> None:
    """Round-3 review, finding 1: the qualifier is part of the statement."""
    title = "Employment Situation Summary - 2026 M07 Results"
    pre = (
        "THE EMPLOYMENT SITUATION -- JULY 2026\n"
        f"The unemployment rate was 4.8 percent in July{qualifier}. "
        f"The unemployment rate (4.8 percent) was unchanged in July{qualifier}. "
        f"Total nonfarm payroll employment rose by 123,000 in July{qualifier}. "
        "Total nonfarm payroll employment changed little in July (+123,000)"
        f"{qualifier}."
    )
    for parser_id in _EMPSIT_IDS:
        assert parse_release(_page(title, pre), parser_id) is None
    bare = pre.replace(qualifier, "")
    assert parse_release(_page(title, bare), "empsit_unemployment_rate") == (
        "2026-07",
        4.8,
    )
    assert parse_release(_page(title, bare), "empsit_payroll_change") == (
        "2026-07",
        123.0,
    )


# What a comparison may compare with, and the words before it, as reviewed:
# the parser's lists must be exactly these, so one is added only with a test.
_COMPARATORS = tuple(
    (
        "change changes gain gains loss losses increase increases decrease "
        "decreases decline declines movement average trend"
    ).split()
)
_MODIFIERS = (
    "little",
    "no",
    "net",
    "average",
    "monthly",
    "large",
    "larger",
    "job",
    "employment",
)


def test_the_comparators_and_modifiers_are_the_reviewed_ones() -> None:
    assert legacy_release_parsers._COMPARATORS == _COMPARATORS
    assert legacy_release_parsers._MODIFIERS == _MODIFIERS


# The tails, written a second time and independently of the parser's
# regular expressions: plain Python over words. A tail is one of these
# closed forms, by the clause its statement ends with.
# - A comparison, after any clause: a comma and an opener; what it compares
#   with (a figure that is not a year, "changing little", or a change, an
#   average or a trend, after an article, "showing" and modifiers, with an
#   "of" figure); then that operand's own period or periods, with a change
#   in parentheses. A second operand, with its own period, may follow
#   "and". Or the average over the prior months, which names its own period
#   ("above the prior 12-month average gain (+5,000)").
# - The trend since another period, after any clause: " and has shown
#   little change since April", " and has remained in a narrow range of 4.0
#   percent to 4.2 percent since May 2024", " and continued its recent
#   upward trend", " and has shown little change in recent months".
# - After a rate or the openings level: its change over the year (" but was
#   down by 885,000 over the year", " and is little different from a year
#   earlier").
# - After a rate: ", and the number of unemployed people ..." and the
#   January note on the population controls, whole.
# A comparison or trend that names the release month itself (alone or in
# the release year) is no tail. "Reported today" may follow any tail. Every
# word of a tail stands apart: "4.2percent" is neither a figure nor a unit.
_OPENERS = tuple(
    tuple(opener.split())
    for opener in (
        "following",
        "after",
        "compared with",
        "compared to",
        "similar to",
        "in line with",
        "close to",
        "the same as",
        "up from",
        "down from",
        "higher than",
        "lower than",
        "less than",
        "more than",
        "above",
        "below",
        "half",
        "double",
        "offsetting",
    )
)
_ADVERBS = (
    "roughly",
    "about",
    "nearly",
    "slightly",
    "somewhat",
    "well",
    "much",
    "far",
    "largely",
    "mostly",
)
_PRIOR = ("prior", "previous", "preceding", "past", "last")
# One month is only the prior one: "the past month" may be the release month.
_PRIOR_MONTH = ("prior", "previous", "preceding")
_SPAN_WORDS = tuple(
    "two three four five six seven eight nine ten eleven twelve".split()
)
# Every count of months a period may name.
_SPANS = (*(str(count) for count in range(1, 100)), *_SPAN_WORDS)
_UNITS = (
    ("percent",),
    ("million",),
    ("percentage", "point"),
    ("percentage", "points"),
    ("jobs",),
)
_RISES = ("increased", "decreased", "rose", "fell", "declined")
_BE = ("is", "are", "was", "were")
_GREW = ("increased", "decreased", "declined", "risen", "fallen", "grown")
_REPORTED_WORDS = ("the", "U.S.", "Bureau", "of", "Labor", "Statistics")
_POPULATION_WORDS = (
    tuple(
        "after accounting for the annual adjustments to the population controls".split()
    ),
    tuple("after accounting for annual population control adjustments".split()),
)
# Words: a parenthesized word, a figure (a count may carry "-month"), a
# comma, a lone parenthesis, or a run of other characters. Every character
# but a space is in one.
_TOKEN = re.compile(
    r"\([^()\s]*\)|[+\-−]?[0-9](?:[0-9]|[,.](?=[0-9]))*(?:-month)?|,|[()]"
    r"|[^\s,()]+"
)


def _words_of(tail: str) -> list[str]:
    return _TOKEN.findall(tail)


def _render(words: list[str]) -> str:
    return "".join("," if word == "," else f" {word}" for word in words)


def _is_figure(word: str) -> bool:
    return re.fullmatch(r"[+\-−]?[0-9](?:[0-9]|[,.](?=[0-9]))*", word) is not None


def _is_year(word: str) -> bool:
    return re.fullmatch(r"(?:19|20)[0-9]{2}", word) is not None


def _is_span(word: str) -> bool:
    return re.fullmatch(r"[1-9][0-9]?", word) is not None or word in _SPAN_WORDS


def _at(words: list[str], i: int, *options: tuple[str, ...]) -> set[int]:
    """Where each of `options`, a run of words, ends if it starts at i."""
    return {
        i + len(option)
        for option in options
        if tuple(words[i : i + len(option)]) == option
    }


def _then(words: list[str], starts: set[int], *options: tuple[str, ...]) -> set[int]:
    return {end for start in starts for end in _at(words, start, *options)}


def _maybe(words: list[str], starts: set[int], *options: tuple[str, ...]) -> set[int]:
    return starts | _then(words, starts, *options)


def _figure_at(words: list[str], starts: set[int], *, year: bool = True) -> set[int]:
    return {
        start + 1
        for start in starts
        if start < len(words)
        and _is_figure(words[start])
        and (year or not _is_year(words[start]))
    }


def _operand(words: list[str], i: int) -> set[int]:
    figure = _figure_at(words, {i}, year=False)
    ends = _maybe(words, figure, *_UNITS) | _at(words, i, ("changing", "little"))
    starts = _maybe(words, {i}, ("a",), ("an",), ("the",))
    starts = _maybe(words, starts, ("showing",))
    while True:
        more = starts | _then(words, starts, *((m,) for m in _MODIFIERS))
        if more == starts:
            break
        starts = more
    heads = _then(words, starts, *((c,) for c in _COMPARATORS))
    of = _figure_at(words, _then(words, heads, ("of",)), year=False)
    return ends | heads | _maybe(words, of, *_UNITS)


def _period(words: list[str], i: int) -> set[int]:
    after = _at(words, i, ("in",), ("since",))
    months = {s + 1 for s in after if s < len(words) and words[s] in MONTHS}
    years = {s + 1 for s in months | after if s < len(words) and _is_year(words[s])}
    ends = months | years
    for preposition in ("over", "for", "during", "in"):
        ends |= _at(
            words, i, *((preposition, "the", prior, "month") for prior in _PRIOR_MONTH)
        )
        the = _at(words, i, *((preposition, "the", prior) for prior in _PRIOR))
        ends |= _then(words, the, ("year",))
        spans = {s + 1 for s in the if s < len(words) and _is_span(words[s])}
        ends |= _then(words, spans, ("months",))
    ends |= _at(
        words,
        i,
        ("over", "the", "year"),
        ("a", "year", "earlier"),
        ("a", "month", "earlier"),
        ("per", "month"),
        ("so", "far", "this", "year"),
        ("thus", "far", "this", "year"),
    )
    return ends


def _trend_period(words: list[str], i: int) -> set[int]:
    return _period(words, i) | _at(words, i, ("in", "recent", "months"))


def _parenthesized(words: list[str], i: int) -> set[int]:
    word = words[i] if i < len(words) else ""
    return (
        {i + 1}
        if word[:1] == "(" and word[-1:] == ")" and _is_figure(word[1:-1])
        else set()
    )


def _periods(
    words: list[str],
    i: int,
    *,
    changes: bool = True,
    least: int = 1,
    period: Callable[[list[str], int], set[int]] = _period,
) -> set[int]:
    starts = {i} | (_parenthesized(words, i) if changes else set())
    ends: set[int] = set()
    frontier = {e for s in starts for e in period(words, s)} if least else set(starts)
    while frontier:
        ends |= frontier
        frontier = {e for s in frontier for e in period(words, s)}
        if changes:
            frontier |= {e for s in ends for e in _parenthesized(words, s)}
        frontier -= ends
    return ends


def _span_average(words: list[str], i: int) -> set[int]:
    the = _at(words, i, *(("the", prior) for prior in _PRIOR))
    month = {
        s + 1
        for s in the
        if s < len(words)
        and words[s].endswith("-month")
        and _is_span(words[s][: -len("-month")])
    }
    heads = _maybe(
        words, _then(words, month, ("average",)), *((c,) for c in _COMPARATORS)
    )
    of = _figure_at(words, _then(words, heads, ("of",)), year=False)
    ends = heads | _maybe(words, of, *_UNITS)
    return ends | {e for s in ends for e in _parenthesized(words, s)}


def _comparison(words: list[str], i: int) -> set[int]:
    starts = _at(words, i, (",",))
    starts = _maybe(words, starts, *((adverb,) for adverb in _ADVERBS))
    opened = _then(words, starts, *_OPENERS)
    operands = {e for s in opened for e in _operand(words, s)}
    first = {e for s in operands for e in _periods(words, s)}
    second = {e for s in _then(words, first, ("and",)) for e in _operand(words, s)}
    return (
        first
        | {e for s in second for e in _periods(words, s)}
        | {e for s in opened for e in _span_average(words, s)}
    )


def _amount(words: list[str], starts: set[int]) -> set[int]:
    return _maybe(words, _figure_at(words, starts), ("percent",), ("million",))


def _trend(words: list[str], i: int) -> set[int]:
    joined = _at(words, i, ("and",), ("but",))
    has = _then(words, joined, ("has",), ("have",), ("had",))
    shown = _maybe(words, _then(words, has, ("shown", "little")), ("or", "no"))
    shown = _maybe(words, _maybe(words, shown, ("net",)), ("employment",))
    bodies = _then(words, shown, ("change",), ("movement",))
    bodies |= _then(
        words, has, ("changed", "little"), ("trended", "up"), ("trended", "down")
    )
    stayed = _then(words, has, ("been",), ("remained",))
    bodies |= _then(
        words,
        stayed,
        ("essentially", "unchanged"),
        ("little", "changed"),
        ("unchanged",),
    )
    ranged = _amount(words, _then(words, stayed, ("in", "a", "narrow", "range", "of")))
    bodies |= _amount(words, _then(words, ranged, ("to",)))
    either = _amount(words, _then(words, stayed, ("at", "either")))
    bodies |= _amount(words, _then(words, either, ("or",)))
    ends = {e for s in bodies for e in _periods(words, s, period=_trend_period)}
    continued = _then(
        words, _maybe(words, joined, ("has",), ("have",), ("had",)), ("continued",)
    )
    trends = _then(
        words,
        _maybe(words, _then(words, continued, ("its",), ("the",)), ("recent",)),
        ("upward", "trend"),
        ("downward", "trend"),
    ) | _then(words, continued, ("to", "trend", "up"), ("to", "trend", "down"))
    return ends | {
        e
        for s in trends
        for e in _periods(words, s, changes=False, least=0, period=_trend_period)
    }


def _over_the_year(words: list[str], i: int) -> set[int]:
    joined = _at(words, i, ("and",), ("but",))
    moved = _then(words, joined, *((be, way) for be in _BE for way in ("up", "down")))
    moved = _maybe(words, moved, ("by",))
    moved |= _then(
        words,
        joined,
        *((have, grew, "by") for have in ("has", "have", "had") for grew in _GREW),
    )
    counted = _maybe(
        words,
        _figure_at(words, moved),
        ("million",),
        ("percentage", "point"),
        ("percentage", "points"),
    )
    held = _then(
        words,
        joined,
        *(
            (be, *state)
            for be in _BE
            for state in (
                ("little", "changed"),
                ("little", "different"),
                ("unchanged",),
                ("essentially", "unchanged"),
            )
        ),
        ("showed", "little", "change"),
    )
    level = _then(
        words, joined, *((be, way, "from") for be in _BE for way in ("up", "down"))
    )
    level = _maybe(words, _figure_at(words, level), ("million",), ("percent",))
    return _then(
        words, counted | held, ("over", "the", "year"), ("from", "a", "year", "earlier")
    ) | _then(words, level, ("a", "year", "earlier"))


def _unemployed(words: list[str], i: int) -> set[int]:
    def counted(starts: set[int]) -> set[int]:
        return _maybe(words, _figure_at(words, starts), ("million",))

    subject = _then(
        words,
        _at(words, i, (",", "and"), (",", "while")),
        ("the", "number", "of", "unemployed", "people"),
        ("the", "number", "of", "unemployed", "persons"),
    )
    subject |= _then(words, counted(_then(words, subject, (",", "at"))), (",",))
    verbs = _then(
        words,
        subject,
        ("changed", "little"),
        *(
            (be, *state)
            for be in ("was", "were")
            for state in (
                ("little", "changed"),
                ("essentially", "unchanged"),
                ("unchanged",),
            )
        ),
    )
    moved = _then(
        words,
        subject,
        *((rise,) for rise in _RISES),
        ("edged", "up"),
        ("edged", "down"),
    )
    verbs |= moved | counted(_then(words, moved, ("by",)))
    verbs |= counted(_then(words, verbs, ("at",), ("to",)))
    return verbs | {
        s + 1
        for s in _then(words, verbs, ("in",))
        if s < len(words) and words[s] in MONTHS
    }


def _names_the_month(words: list[str], month: str, year: str) -> bool:
    return any(
        word == month
        and (i + 1 == len(words) or words[i + 1] == year or not _is_year(words[i + 1]))
        for i, word in enumerate(words)
    )


def _reference(tail: str, clause: str, month: str = "July", year: str = "2026") -> bool:
    """Whether `tail` may end a statement whose last clause is `clause`."""
    words = _words_of(tail)
    # Every word stands apart ("4.2percent" is two run together); the page
    # reads any run of spaces as one.
    if _render(words) != re.sub(r"\s+", " ", tail):
        return False
    ends = {0}
    compared = (_comparison(words, 0) | _trend(words, 0)) if words else set()
    ends |= {e for e in compared if not _names_the_month(words[:e], month, year)}
    if clause in ("rate", "openings"):
        ends |= _over_the_year(words, 0)
    if clause == "rate":
        ends |= _unemployed(words, 0) | _at(
            words, 0, *((",", *w) for w in _POPULATION_WORDS)
        )
    reported = _then(words, ends, (",", *_REPORTED_WORDS))
    reported = _then(words, _maybe(words, reported, ("(BLS)",)), ("reported", "today"))
    return len(words) in ends | reported


def _admitted(tail: str, clause: str) -> bool:
    """Whether the parser reads a July 2026 statement whose last clause is
    `clause` and ends in `tail`: beside two statements of the headline, it
    then disagrees with them, and the page refuses. The probe names its
    year, so no tail can supply one."""
    if clause == "rate":
        title, head = _EMPSIT_JULY
        headline = (
            "The unemployment rate was 4.1 percent in July. "
            "The unemployment rate changed little at 4.1 percent in July. "
        )
        probe = f"The unemployment rate was 4.8 percent in July 2026{tail}."
        parser_id, reading = "empsit_unemployment_rate", ("2026-07", 4.1)
    elif clause == "payroll":
        title, head = _EMPSIT_JULY
        headline = (
            "Total nonfarm payroll employment rose by 123,000 in July. "
            "Total nonfarm payroll employment changed little in July (+123,000). "
        )
        probe = f"Total nonfarm payroll employment rose by 999,000 in July 2026{tail}."
        parser_id, reading = "empsit_payroll_change", ("2026-07", 123.0)
    else:
        title = "Job Openings and Labor Turnover Summary - 2026 M07 Results"
        head = "JOB OPENINGS AND LABOR TURNOVER -- JULY 2026\n"
        headline = (
            "The number of job openings was 7.4 million in July. "
            "The number of job openings was little changed at 7.4 million in July. "
        )
        probe = f"The number of job openings was 9.9 million in July 2026{tail}."
        parser_id, reading = "jolts_job_openings", ("2026-07", 7.4)
    got = parse_release(_page(title, f"{head}{headline}{probe}"), parser_id)
    assert got in (None, reading), (tail, got)
    return got is None


_EMPSIT_JULY = (
    "Employment Situation Summary - 2026 M07 Results",
    "THE EMPLOYMENT SITUATION -- JULY 2026\n",
)
_CLAUSES = ("rate", "payroll", "openings")


def _check(tail: str, clause: str, expected: bool) -> None:
    assert _reference(tail, clause) is expected, (tail, clause)
    assert _admitted(tail, clause) is expected, (tail, clause)


# Months and years another period may name in a July 2026 release.
_OTHER_MONTHS = tuple(month for month in MONTHS if month != "July")
_FIGURES = ("4.2", "166,000", "-13,000", "−41,000", "+36,000", "7.4", "885,000")


@st.composite
def _operand_words(draw: st.DrawFn) -> list[str]:
    kind = draw(st.integers(0, 4))
    if kind == 0:
        return [draw(st.sampled_from(_FIGURES)), *draw(st.sampled_from(((), *_UNITS)))]
    if kind == 1:
        return ["changing", "little"]
    words = list(draw(st.sampled_from(((), ("a",), ("an",), ("the",)))))
    words += draw(st.sampled_from(((), ("showing",))))
    words += draw(st.lists(st.sampled_from(_MODIFIERS), max_size=3))
    words.append(draw(st.sampled_from(_COMPARATORS)))
    if draw(st.booleans()):
        words += [
            "of",
            draw(st.sampled_from(_FIGURES)),
            *draw(st.sampled_from(((), *_UNITS))),
        ]
    return words


@st.composite
def _period_words(draw: st.DrawFn, *, trend: bool = False) -> list[str]:
    prior = draw(st.sampled_from(_PRIOR))
    month = draw(st.sampled_from(_OTHER_MONTHS))
    preposition = draw(st.sampled_from(("over", "for", "during", "in")))
    periods = [
        ("in", month),
        ("since", month),
        ("in", month, "2024"),
        ("since", "July", "2025"),
        ("in", "2025"),
        (preposition, "the", draw(st.sampled_from(_PRIOR_MONTH)), "month"),
        (preposition, "the", prior, draw(st.sampled_from(_SPANS)), "months"),
        (preposition, "the", prior, "year"),
        ("over", "the", "year"),
        ("a", "year", "earlier"),
        ("a", "month", "earlier"),
        ("per", "month"),
        (draw(st.sampled_from(("so", "thus"))), "far", "this", "year"),
    ]
    if trend:
        periods.append(("in", "recent", "months"))
    return list(draw(st.sampled_from(periods)))


@st.composite
def _periods_words(draw: st.DrawFn, *, trend: bool = False) -> list[str]:
    words = ["(+36,000)"] if draw(st.integers(0, 4)) == 0 else []
    for _ in range(draw(st.integers(1, 3))):
        words += draw(_period_words(trend=trend))
        if draw(st.integers(0, 4)) == 0:
            words.append(
                draw(st.sampled_from(("(+36,000)", "(-133,000)", "(−133,000)")))
            )
    return words


@st.composite
def _span_average_words(draw: st.DrawFn) -> list[str]:
    span = draw(st.sampled_from(_SPANS))
    words = ["the", draw(st.sampled_from(_PRIOR)), f"{span}-month", "average"]
    words += draw(st.sampled_from(((), *((c,) for c in _COMPARATORS))))
    if draw(st.booleans()):
        words += [
            "of",
            draw(st.sampled_from(_FIGURES)),
            *draw(st.sampled_from(((), *_UNITS))),
        ]
    if draw(st.booleans()):
        words.append(draw(st.sampled_from(("(+5,000)", "(-12,000)", "(−12,000)"))))
    return words


@st.composite
def _tail_words(draw: st.DrawFn, clause: str) -> list[str]:
    """A tail in one of the closed forms for `clause`, as words."""
    forms = ["comparison", "trend"]
    forms += {
        "rate": ["year", "unemployed", "population"],
        "payroll": [],
        "openings": ["year"],
    }[clause]
    form = draw(st.sampled_from(forms))
    if form == "comparison":
        words = [","]
        words += draw(st.sampled_from(((), *((adverb,) for adverb in _ADVERBS))))
        words += draw(st.sampled_from(_OPENERS))
        if draw(st.integers(0, 4)) == 0:
            words += draw(_span_average_words())
        else:
            words += draw(_operand_words()) + draw(_periods_words())
            if draw(st.integers(0, 3)) == 0:
                words += ["and", *draw(_operand_words()), *draw(_periods_words())]
    elif form == "trend":
        amount = [
            draw(st.sampled_from(_FIGURES)),
            *draw(st.sampled_from(((), ("percent",), ("million",)))),
        ]
        other = [draw(st.sampled_from(_FIGURES)), "percent"]
        stayed = draw(st.sampled_from(("been", "remained")))
        words = [draw(st.sampled_from(("and", "but")))]
        if draw(st.integers(0, 3)):
            words.append(draw(st.sampled_from(("has", "have", "had"))))
            words += draw(
                st.sampled_from(
                    (
                        (
                            "shown",
                            "little",
                            *draw(st.sampled_from(((), ("or", "no")))),
                            *draw(st.sampled_from(((), ("net",)))),
                            *draw(st.sampled_from(((), ("employment",)))),
                            draw(st.sampled_from(("change", "movement"))),
                        ),
                        ("changed", "little"),
                        (stayed, "essentially", "unchanged"),
                        (stayed, "little", "changed"),
                        (stayed, "unchanged"),
                        ("trended", draw(st.sampled_from(("up", "down")))),
                        (
                            stayed,
                            "in",
                            "a",
                            "narrow",
                            "range",
                            "of",
                            *amount,
                            "to",
                            *other,
                        ),
                        (stayed, "at", "either", *amount, "or", *other),
                    )
                )
            )
            words += draw(_periods_words(trend=True))
        else:
            words += draw(st.sampled_from(((), ("has",), ("have",), ("had",))))
            words += ["continued"]
            words += draw(
                st.sampled_from(
                    (
                        ("its", "recent", "upward", "trend"),
                        ("the", "downward", "trend"),
                        ("to", "trend", draw(st.sampled_from(("up", "down")))),
                    )
                )
            )
            for _ in range(draw(st.integers(0, 2))):
                words += draw(_period_words(trend=True))
    elif form == "year":
        be = draw(st.sampled_from(_BE))
        way = draw(st.sampled_from(("up", "down")))
        figure = draw(st.sampled_from(_FIGURES))
        unit = draw(
            st.sampled_from(
                ((), ("million",), ("percentage", "point"), ("percentage", "points"))
            )
        )
        ago = draw(
            st.sampled_from((("over", "the", "year"), ("from", "a", "year", "earlier")))
        )
        have = draw(st.sampled_from(("has", "have", "had")))
        level = draw(st.sampled_from(((), ("million",), ("percent",))))
        held = draw(
            st.sampled_from(
                (
                    ("little", "changed"),
                    ("little", "different"),
                    ("unchanged",),
                    ("essentially", "unchanged"),
                )
            )
        )
        words = [draw(st.sampled_from(("and", "but")))]
        words += draw(
            st.sampled_from(
                (
                    (be, way, figure, *unit, *ago),
                    (be, way, "by", figure, *unit, *ago),
                    (have, draw(st.sampled_from(_GREW)), "by", figure, *unit, *ago),
                    (be, way, "from", figure, *level, "a", "year", "earlier"),
                    (be, *held, *ago),
                    ("showed", "little", "change", *ago),
                )
            )
        )
    elif form == "unemployed":
        counted = [
            draw(st.sampled_from(_FIGURES)),
            *draw(st.sampled_from(((), ("million",)))),
        ]
        words = [
            ",",
            draw(st.sampled_from(("and", "while"))),
            "the",
            "number",
            "of",
            "unemployed",
        ]
        words.append(draw(st.sampled_from(("people", "persons"))))
        if draw(st.booleans()):
            words += [",", "at", *counted, ","]
        verb = draw(
            st.sampled_from(
                (
                    ("changed", "little"),
                    *(
                        (be, *state)
                        for be in ("was", "were")
                        for state in (
                            ("little", "changed"),
                            ("essentially", "unchanged"),
                            ("unchanged",),
                        )
                    ),
                    *((rise,) for rise in _RISES),
                    ("edged", "up"),
                    ("edged", "down"),
                )
            )
        )
        words += verb
        if verb[0] in (*_RISES, "edged") and draw(st.booleans()):
            words += ["by", *counted]
        if draw(st.booleans()):
            words += [draw(st.sampled_from(("at", "to"))), *counted]
        if draw(st.booleans()):
            words += ["in", draw(st.sampled_from(MONTHS))]
    else:
        words = [",", *draw(st.sampled_from(_POPULATION_WORDS))]
    if draw(st.integers(0, 3)) == 0:
        words += [
            ",",
            *_REPORTED_WORDS,
            *draw(st.sampled_from(((), ("(BLS)",)))),
            "reported",
            "today",
        ]
    return words


@settings(max_examples=300, deadline=None)
@given(data=st.data(), clause=st.sampled_from(_CLAUSES))
def test_every_tail_of_the_closed_forms_is_read_by_both_readings(
    data: st.DataObject, clause: str
) -> None:
    tail = _render(data.draw(_tail_words(clause)))
    _check(tail, clause, True)


# Words a near-miss may gain: the forms' own, others BLS prints, and those
# that would speak to the statement's own basis, scope, measure or period.
_NEAR_WORDS = (
    ",",
    "and",
    "or",
    "but",
    "by",
    "of",
    "in",
    "for",
    "the",
    "a",
    "an",
    "over",
    "since",
    "month",
    "months",
    "year",
    "earlier",
    "prior",
    "previous",
    "per",
    "has",
    "was",
    "is",
    "were",
    "percent",
    "million",
    "change",
    "gain",
    "average",
    "monthly",
    "little",
    "no",
    "net",
    "trend",
    "range",
    "to",
    "at",
    "either",
    "July",
    "June",
    "2025",
    "2026",
    "12",
    "three",
    "166,000",
    "120,000",
    "4.1",
    "(+36,000)",
    "(BLS)",
    "U.S.",
    "seasonal",
    "adjustment",
    "adjusted",
    "rate",
    "including",
    "workers",
    "revised",
    "latest",
    "after",
    "following",
    "compared",
    "with",
    "same",
    "unemployed",
    "people",
    "showing",
    "today",
    # Round-9 forms and their neighbours.
    "half",
    "double",
    "offsetting",
    "largely",
    "jobs",
    "job",
    "large",
    "changing",
    "recent",
    "up",
    "down",
    "from",
    "different",
    "been",
    "remained",
    "continued",
    "showed",
    "six",
    "thirteen",
    "0",
    "100",
    "12-month",
    "past",
    "last",
    "point",
)


@st.composite
def _near_miss(draw: st.DrawFn, clause: str) -> str:
    """A tail of the closed forms with one to three word edits, or the
    start of one joined to the end of another (of any clause's forms). The
    probe names its year, so a tail starting with four digits is no year of
    the statement's: nothing is assumed away."""
    words = draw(_tail_words(clause))
    if draw(st.booleans()):
        other = draw(_tail_words(draw(st.sampled_from(_CLAUSES))))
        cut = draw(st.integers(0, len(words)))
        words = words[:cut] + other[draw(st.integers(0, len(other))) :]
    else:
        words = _edited(draw, words)
    return _render(words)


def _edited(draw: st.DrawFn, words: list[str]) -> list[str]:
    for _ in range(draw(st.integers(1, 3))):
        at = draw(st.integers(0, len(words)))
        edit = draw(st.sampled_from(("insert", "delete", "replace")))
        if edit == "insert" or not words:
            words.insert(at, draw(st.sampled_from(_NEAR_WORDS)))
        elif edit == "delete":
            del words[min(at, len(words) - 1)]
        else:
            words[min(at, len(words) - 1)] = draw(st.sampled_from(_NEAR_WORDS))
    return words


@settings(max_examples=1000, deadline=None)
@given(data=st.data(), clause=st.sampled_from(_CLAUSES))
def test_the_parser_reads_a_tail_exactly_when_the_closed_forms_do(
    data: st.DataObject, clause: str
) -> None:
    """Round-8 review: the parser's tails are the closed forms, written twice.

    Tails a few word edits away from a closed form (an added "and by
    120,000", a dropped operand, another month, a basis word), and closed
    forms cut and joined, are read by the parser exactly when the
    plain-Python reading above reads them.
    """
    tail = data.draw(_near_miss(clause))
    expected = _reference(tail, clause)
    event(f"{clause}: {'a tail' if expected else 'no tail'}")
    assert _admitted(tail, clause) is expected, (tail, clause)


@settings(max_examples=300, deadline=None)
@given(
    rates=st.lists(_tail_words("rate"), min_size=2, max_size=2),
    payrolls=st.lists(_tail_words("payroll"), min_size=2, max_size=2),
)
def test_no_tail_changes_what_a_statement_says(
    rates: list[list[str]], payrolls: list[list[str]]
) -> None:
    """Round-4 review: a continuation is a tail, and none of it is read."""
    _check_tails([_render(words) for words in (*rates, *payrolls)])


# Every tail in the 54 real captures (corpus/tails.py), by its clause.
_REAL_TAILS = (
    ("payroll", ", the U.S. Bureau of Labor Statistics reported today"),
    (
        "payroll",
        " and has shown little change since April, the U.S. Bureau of Labor Statistics"
        " (BLS) reported today",
    ),
    ("payroll", " but has shown little change since April"),
    ("payroll", ", below the average monthly gain of 215,000 over the prior 12 months"),
    (
        "payroll",
        ", following an average monthly gain of 194,000 over the prior 12 months",
    ),
    ("payroll", ", following little change in the prior month (+36,000)"),
    ("payroll", ", similar to the average monthly gain of 166,000 in 2024"),
    (
        "payroll",
        ", higher than the average monthly gain of 158,000 over the prior 12 months",
    ),
    (
        "payroll",
        ", roughly in line with the average monthly gain of 152,000 over the prior 12"
        " months",
    ),
    (
        "payroll",
        ", in line with the average monthly gain of 146,000 over the prior 12 months",
    ),
    ("payroll", ", following an increase in January (+126,000)"),
    ("payroll", ", following a decrease in February (-133,000)"),
    ("payroll", ", after showing little net change over the prior 12 months"),
    ("payroll", ", similar to the gain of 179,000 in April"),
    (
        "payroll",
        ", roughly in line with the average monthly change over the prior 12 months"
        " (+36,000)",
    ),
    (
        "rate",
        " and has remained in a narrow range of 4.0 percent to 4.2 percent since May"
        " 2024",
    ),
    (
        "rate",
        ", and the number of unemployed people increased by 352,000 to 7.2 million",
    ),
    (
        "rate",
        ", and the number of unemployed people, at 7.1 million, changed little in"
        " August",
    ),
    ("rate", ", and the number of unemployed people was little changed at 7.0 million"),
    ("rate", ", and the number of unemployed people changed little at 7.4 million"),
    (
        "rate",
        ", after accounting for the annual adjustments to the population controls",
    ),
    ("openings", " but was down by 885,000 over the year"),
    ("openings", " and was down by 966,000 over the year"),
)


@pytest.mark.parametrize(("clause", "tail"), _REAL_TAILS)
def test_every_real_tail_is_a_closed_form(clause: str, tail: str) -> None:
    _check(tail, clause, True)


# Round-8 red team (r8b), finding 1: what BLS prints after any measure's
# month, not only the headline's, is the evidence of its habits. A habit is
# what follows " in <month>" (with its year or change) to the sentence's
# end, when it opens with a comma (but ", and", ", while", ", at" and
# "reported today", which open clauses of their own) or with " and"/" but"
# and a verb: a comparison, a trend or a change. Each is a tail, or is
# excluded here for its reason.
_HABIT = re.compile(
    r", (?!and |while |the U\.S\. |at )"
    r"| (?:and|but) (?:has|have|had|is|are|was|were|continued|showed) "
)
_EXCLUDED_HABITS = (
    (
        r", (?:as|driven by|largely in|led by|mostly in|primarily (?:in|due to)"
        r"|reflecting|with) ",
        "what a change is made of or why: industries and events, no closed list",
    ),
    (r", federal government employment ", "a clause about another measure"),
    (r", more than offsetting decreases in those ", "a comparison with other measures"),
    (
        r", but at a slower pace than ",
        "a contrast after 'but', which BLS also prints with no comma before it",
    ),
    (
        r", essentially unchanged from the previous month$",
        "no operand: like 'compared with a year earlier', it makes the figure a change",
    ),
    (
        r" (?:and|but) (?:is|has) (?:up|down|fallen) by \S+ since ",
        "a change since a month: since June, it would be July's own change",
    ),
    (r" and was completed ", "a note on the survey"),
)


def _bls_habits() -> list[str]:
    after_month = re.compile(
        rf" in (?:{'|'.join(MONTHS)})(?: [0-9]{{4}})?(?: \([+\-−]?[0-9][0-9,]*\))?"
    )
    # A full stop: not in "U.S.", not in a number.
    stop = re.compile(r"(?<!\bU)(?<!\bU\.S)\.(?![0-9])(?=\s|$)")
    fixtures = ROOT / "tests" / "fixtures" / "release_capture"
    habits: set[str] = set()
    for raw_path in sorted([*fixtures.glob("*.raw"), *fixtures.glob("corpus/*.raw")]):
        if not raw_path.name.startswith(("empsit.nr0", "jolts.nr0")):
            continue
        raw = raw_path.read_bytes()
        body = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
        doc = legacy_release_parsers._Document()
        doc.feed(body.decode("utf-8", errors="replace"))
        doc.close()
        (block,) = doc.pres
        text = " ".join("".join(block).split())
        for month in after_month.finditer(text):
            end = stop.search(text, month.end())
            if end is not None and _HABIT.match(text, month.end()):
                habits.add(text[month.end() : end.start()])
    return sorted(habits)


def test_every_comparison_trend_or_change_bls_prints_is_a_tail_or_excluded() -> None:
    habits = _bls_habits()
    excluded = {
        habit
        for habit in habits
        if any(re.match(pattern, habit) for pattern, _ in _EXCLUDED_HABITS)
    }
    # Each exclusion is of something BLS printed.
    for pattern, _ in _EXCLUDED_HABITS:
        assert any(re.match(pattern, habit) for habit in excluded), pattern
    # 117 habits in the 32 summary captures: 73 tails, 44 excluded.
    assert (len(habits), len(excluded)) == (117, 44)
    for habit in habits:
        if habit in excluded:
            clauses: tuple[str, ...] = ()
        elif habit.startswith(", after accounting for "):
            clauses = ("rate",)
        elif re.match(
            r" (?:and|but) (?:(?:is|are|was|were|showed) |(?:has|have|had) "
            r"(?:increased|decreased|declined|risen|fallen|grown) by )",
            habit,
        ):
            clauses = ("rate", "openings")
        else:
            clauses = _CLAUSES
        for clause in _CLAUSES:
            _check(habit, clause, clause in clauses)


@pytest.mark.parametrize(
    "tail",
    (
        # Each opener, after its comma, and after an adverb.
        *(f", {' '.join(opener)} a gain in June" for opener in _OPENERS),
        *(f", {' '.join(opener)} 4.0 percent a year earlier" for opener in _OPENERS),
        *(f", {adverb} similar to the average in 2025" for adverb in _ADVERBS),
        # Each modifier, "showing", "changing little", each article and unit.
        *(f", following {modifier} change in June" for modifier in _MODIFIERS),
        ", after showing little net change over the prior 12 months",
        ", after changing little over the prior 12 months",
        ", following a decrease in June",
        ", following an increase in June",
        *(f", compared with 0.3 {' '.join(unit)} in June" for unit in _UNITS),
        *(f", compared with a gain of 0.3 {' '.join(unit)} in June" for unit in _UNITS),
        # Each period, and a change in parentheses before or after one.
        ", following a gain in May 2024",
        ", following a gain since June",
        ", following a gain since 2024",
        ", following a gain in 2025",
        *(
            f", following a gain {preposition} the {prior} month"
            for preposition in ("over", "for", "during", "in")
            for prior in _PRIOR_MONTH
        ),
        *(
            f", following a gain {preposition} the {prior} {span} months"
            for preposition in ("over", "for", "during", "in")
            for prior in _PRIOR
            for span in ("12", "six")
        ),
        ", following a gain over the year",
        *(
            f", following a gain {preposition} the {prior} year"
            for preposition in ("over", "for", "during", "in")
            for prior in _PRIOR
        ),
        ", following a gain a year earlier",
        ", following a gain a month earlier",
        ", following an average of 168,000 per month over the prior 12 months",
        ", following a gain so far this year",
        ", following a gain thus far this year",
        ", following little change (+36,000) in June",
        ", following little change in June (−36,000)",
        ", following gains of 34,000 in May and 41,000 in June",
        ", following an increase in May and a decrease in June",
        # A figure that only begins like a year is a figure.
        ", following a gain of 20251 in June",
        ", up from 1999.5 percent in June",
        # The average over the prior months names its own period.
        ", above the prior 12-month average gain (+5,000)",
        ", about double the prior 12-month average gain of 12,000",
        ", below the past six-month average",
        *(f", above the {prior} 12-month average" for prior in _PRIOR),
    ),
)
def test_each_part_of_a_comparison_may_be_its_own(tail: str) -> None:
    for clause in _CLAUSES:
        _check(tail, clause, True)


@pytest.mark.parametrize("span", ("1", "6", "9", "10", "12", "99", *_SPAN_WORDS))
def test_every_count_of_months_is_a_period(span: str) -> None:
    """Round-8 red team (r8b), finding 4: one-digit counts went untested."""
    for tail in (
        f", following a gain over the prior {span} months",
        f", following a gain over the prior {span} months (+36,000)",
        f", above the prior {span}-month average",
        f" and has shown little change over the past {span} months",
    ):
        _check(tail, "payroll", True)


@pytest.mark.parametrize("span", ("0", "00", "06", "100", "1.5", "thirteen", "one"))
def test_another_count_of_months_is_no_period(span: str) -> None:
    for tail in (
        f", following a gain over the prior {span} months",
        f", above the prior {span}-month average",
    ):
        _check(tail, "payroll", False)


@pytest.mark.parametrize("opener", _OPENERS)
def test_a_comparison_without_its_comma_is_no_tail(opener: tuple[str, ...]) -> None:
    """Round-8 red team (r8a), finding 1: "was 10.0 percent higher than 4.0
    percent in June" made the figure a difference."""
    for tail in (
        f" {' '.join(opener)} 4.0 percent in June",
        f" {' '.join(opener)} a gain in June",
        f" {' '.join(opener)} the prior 12-month average",
        f" roughly {' '.join(opener)} 50,000 in June",
    ):
        for clause in _CLAUSES:
            _check(tail, clause, False)


def test_round_8_red_team_a_comparison_never_makes_the_figure_a_difference() -> None:
    """Round-8 red team (r8a), finding 1, verbatim: they returned 10.0 and 120.0."""
    title, head = _EMPSIT_JULY
    rate = (
        "In July, the unemployment rate was 10.0 percent higher than 4.0 percent in "
        "June.\nThe unemployment rate was 10.0 percent higher than 4.0 percent in "
        "June."
    )
    assert parse_release(_page(title, head + rate), "empsit_unemployment_rate") is None
    payroll = (
        "The unemployment rate was 4.1 percent in July, and nonfarm payroll "
        "employment rose by 120,000 more than 50,000 in June.\nNonfarm payroll "
        "employment rose by 120,000 more than 50,000 in June."
    )
    assert parse_release(_page(title, head + payroll), "empsit_payroll_change") is None
    # With its comma, the comparison is with June's figure, and the
    # statement's own figure is read.
    rate = rate.replace(" higher", ", higher")
    assert parse_release(_page(title, head + rate), "empsit_unemployment_rate") == (
        "2026-07",
        10.0,
    )


@pytest.mark.parametrize(
    "tail",
    (
        # r8b, finding 2: words run together are no words of a tail.
        ", compared with 4.2percent in June",
        ", compared with 7million in June",
        ", following a gain in June,the U.S. Bureau of Labor Statistics reported today",
        ",following a gain in June",
        " , following a gain in June",
        ", following a gain in June ",
        ", following a gain inJune",
        ", following a gain in the prior 12months",
        ", above the prior 12 -month average",
        # r8b, finding 3: a year after the probe's own is no tail.
        " 2026",
        " 2025",
        " 20251",
        " 2026, following a gain in June",
    ),
)
def test_a_tail_run_together_or_carrying_a_year_is_no_tail(tail: str) -> None:
    for clause in _CLAUSES:
        _check(tail, clause, False)


@pytest.mark.parametrize("comparator", _COMPARATORS)
def test_each_comparator_may_be_what_a_comparison_names(comparator: str) -> None:
    for tail in (
        f", compared with the {comparator} a year earlier",
        f", following the {comparator} in June",
        f", up from the {comparator} over the prior 12 months",
        f", above the prior 12-month average {comparator} (+5,000)",
        f", below the {comparator} of 166,000 over the previous year",
    ):
        _check(tail, "payroll", True)
    # Not a period: the comparator names what is compared with.
    _check(f", following the {comparator}", "payroll", False)


@pytest.mark.parametrize(
    "tail",
    (
        " and has shown little change since April",
        " but has shown little movement since January",
        " and have shown little net change since April",
        " and had changed little since April",
        " and has been essentially unchanged since April",
        " and has been little changed since April",
        " and has been unchanged since April",
        " and has trended up over the prior 12 months",
        " and has trended down since 2024",
        " and has remained essentially unchanged since April",
        " and has remained little changed since April",
        " and has remained unchanged since April",
        " and has remained in a narrow range of 4.0 percent to 4.2 percent since May"
        " 2024",
        " and has remained at either 4.1 percent or 4.2 percent since June",
        " and continued its recent upward trend",
        " and continued the downward trend over the year",
        " but continued to trend up",
        " and continued to trend down since June",
        # Round-8 red team (r8b), finding 1, and BLS's own variants.
        " and has continued to trend up since April",
        " and had continued its upward trend",
        " and has shown little change for the past year",
        " and has been in a narrow range of 4.0 percent to 4.2 percent since May 2024",
        " and has been at either 4.1 percent or 4.2 percent since June",
        " and has shown little or no change since April",
        " and has shown little change in recent months",
        " but has shown little net employment change over the prior 12 months",
        " and continued to trend up in recent months",
    ),
)
def test_each_trend_may_be_its_own(tail: str) -> None:
    for clause in _CLAUSES:
        _check(tail, clause, True)


@pytest.mark.parametrize(
    "tail",
    (
        # "In recent months" is a trend's period only: a figure compared
        # with recent months may be of the release month itself.
        ", compared with 4.1 percent in recent months",
        ", following a gain in recent months",
        # "The past month" or "the last month" may be the release month.
        ", following a gain in the past month",
        ", following a gain in the last month",
        ", compared with 4.1 percent over the last month",
        " and has shown little change in the past month",
    ),
)
def test_a_period_that_may_be_the_release_month_is_no_operands_period(
    tail: str,
) -> None:
    for clause in _CLAUSES:
        _check(tail, clause, False)


@pytest.mark.parametrize(
    ("tail", "clauses"),
    (
        (", while the number of unemployed persons edged up by 0.1 million", ("rate",)),
        (", and the number of unemployed people were essentially unchanged", ("rate",)),
        (
            ", and the number of unemployed people fell to 6.9 million in July",
            ("rate",),
        ),
        (", after accounting for annual population control adjustments", ("rate",)),
        (" but were up by 0.3 million over the year", ("rate", "openings")),
        # Round-8 red team (r8b), finding 1, and BLS's own variants: a
        # level's change over the year, never the payroll change's.
        (" but was down 885,000 over the year", ("rate", "openings")),
        (" and was down by 1.8 million from a year earlier", ("rate", "openings")),
        (" but is down by 0.4 percentage point over the year", ("rate", "openings")),
        (
            " but has declined by 0.5 percentage point over the year",
            ("rate", "openings"),
        ),
        (" but has increased by 385,000 over the year", ("rate", "openings")),
        (" and is little changed over the year", ("rate", "openings")),
        (" but is little different from a year earlier", ("rate", "openings")),
        (" but is up from 1.5 million a year earlier", ("rate", "openings")),
        (" but showed little change from a year earlier", ("rate", "openings")),
    ),
)
def test_a_tail_about_another_measure_follows_only_its_own_clause(
    tail: str, clauses: tuple[str, ...]
) -> None:
    for clause in _CLAUSES:
        _check(tail, clause, clause in clauses)


@pytest.mark.parametrize(
    "tail",
    (
        # Round-8 review, finding 1: a later clause restating the figure.
        ", compared with a year earlier, and by 120,000 for the month",
        ", compared with a gain a year earlier, and by 120,000 for the month",
        ", following a gain in June, and by 120,000 for the month",
        ", following a gain in June and by 120,000 for the month",
        ", following a gain in June and 120,000 for the month",
        ", following a gain in June, and 120,000 over the month",
        ", following a gain in June or 120,000 over the month",
        " and has increased by 120,000 for the month",
        " and has shown little change since April, and by 120,000 for the month",
        " and was up by 120,000 over the month",
        ", and was 120,000 over the month",
        # A change since a month: since June, it is July's own change.
        " and is up by 120,000 since June",
        " and has risen by 120,000 since June",
        " and was up by 120,000 from the previous month",
        " and is up from 4.0 percent in June",
        " and was little changed from the previous month",
        # A comparison with no operand, or no period of its own.
        ", compared with a year earlier",
        " compared with the previous year",
        ", up from a year earlier",
        ", compared with 120,000",
        ", following a gain",
        ", following little change (+36,000)",
        ", compared with 2025",
        ", following 12 months",
        # Round-8 review, finding 2: a figure the test generator ran into a
        # count of months.
        ", following 166,000 month",
        ", following 166,000 months",
        ", following January January January 166,000 month",
        # A separating comma is no part of a figure.
        ", compared with 120,000, in June",
        ", following a gain of 120,000, in June",
        # The release month itself, or in the release year.
        ", compared with a gain of 120,000 in July",
        ", compared with a gain of 120,000 in July 2026",
        ", following a gain in June and 120,000 in July",
        " and has shown little change since July",
    ),
)
def test_a_tail_restating_the_statements_own_figure_is_no_tail(tail: str) -> None:
    for clause in _CLAUSES:
        _check(tail, clause, False)
    _check_requalified(tail)


def test_a_change_over_the_year_never_follows_the_payroll_change() -> None:
    for tail in (
        " and was up by 120,000 over the year",
        " but is little different from a year earlier",
        " and has increased by 1,500,000 over the year",
    ):
        _check(tail, "payroll", False)
        _check(tail, "rate", True)
        _check(tail, "openings", True)


@pytest.mark.parametrize(
    "verb",
    (
        "changed little",
        "was little changed",
        "were little changed",
        "was essentially unchanged",
        "were essentially unchanged",
        "was unchanged",
        "were unchanged",
        *_RISES,
        "edged up",
        "edged down",
    ),
)
def test_every_verb_of_the_number_unemployed_is_read_after_a_rate(verb: str) -> None:
    """Round-8 red team (r8b), finding 5: three verbs went untested."""
    moved = verb.split()[0] in (*_RISES, "edged")
    tails = [
        f", and the number of unemployed people {verb}",
        f", while the number of unemployed persons, at 7.1 million, {verb} in June",
        f", and the number of unemployed people {verb} to 7.1 million",
    ]
    if moved:
        tails.append(f", and the number of unemployed people {verb} by 352,000")
    for tail in tails:
        _check(tail, "rate", True)
        _check(tail, "payroll", False)
        _check(tail, "openings", False)
    if not moved:
        _check(
            f", and the number of unemployed people {verb} by 352,000", "rate", False
        )


def test_another_years_month_is_another_period() -> None:
    for tail in (
        ", compared with a gain of 120,000 in July 2025",
        " and has remained in a narrow range of 4.0 percent to 4.2 percent since July"
        " 2025",
    ):
        _check(tail, "payroll", True)


@pytest.mark.parametrize("opener", _OPENERS)
@pytest.mark.parametrize(
    ("period", "named"),
    (
        ("a year earlier", "a year earlier"),
        ("the previous year", "over the previous year"),
        ("the prior 12 months", "over the prior 12 months"),
        ("June", "in June"),
        ("2025", "in 2025"),
    ),
)
def test_a_comparison_with_a_bare_period_is_no_tail(
    opener: tuple[str, ...], period: str, named: str
) -> None:
    """Round-7 review, finding 1: "compared with a year earlier" makes the
    statement's own figure a change over the year."""
    _check_requalified(f", {' '.join(opener)} {period}")
    # Naming what it compares with, and that operand's period, it is a tail.
    for tail in (
        f", {' '.join(opener)} 4.0 percent {named}",
        f", {' '.join(opener)} a gain {named}",
    ):
        _check(tail, "payroll", True)


@pytest.mark.parametrize(
    "figure",
    ("+36,000", "-13,000", "−13,000", "(+36,000)", "(-41,000)", "(−41,000)"),
)
def test_a_tail_figure_may_carry_any_printed_sign(figure: str) -> None:
    # A minus sign may be printed as a hyphen or as U+2212.
    if figure.startswith("("):
        tails = [
            f", following little change in June {figure}",
            f", following a gain {figure} in June",
        ]
    else:
        tails = [
            f", up from {figure} in June",
            f", following a change of {figure} in June",
        ]
    _check_tails(["", "", *tails])


@pytest.mark.parametrize(
    "tail",
    (
        # BLS's January rate, and the wording of its later population notes.
        ", after accounting for the annual adjustments to the population controls",
        ", after accounting for annual population control adjustments",
    ),
)
def test_the_population_control_tail_may_follow_a_rate_statement(tail: str) -> None:
    _check_tails([tail, tail, "", ""])
    # Only whole: a part of it, or more, is no tail.
    for changed in (tail.rsplit(" ", 1)[0], f"{tail} by state"):
        title = "Employment Situation Summary - 2026 M07 Results"
        pre = (
            "THE EMPLOYMENT SITUATION -- JULY 2026\n"
            f"The unemployment rate was 4.8 percent in July{changed}. "
            f"The unemployment rate changed little at 4.8 percent in July{changed}."
        )
        assert parse_release(_page(title, pre), "empsit_unemployment_rate") is None


def _check_tails(tails: list[str]) -> None:
    """Rate statements ending in the first two tails, payroll statements in
    the last two: each reader returns its figure."""
    title = "Employment Situation Summary - 2026 M07 Results"
    pre = (
        "THE EMPLOYMENT SITUATION -- JULY 2026\n"
        f"The unemployment rate was 4.1 percent in July{tails[0]}. "
        f"The unemployment rate changed little at 4.1 percent in July{tails[1]}. "
        f"Total nonfarm payroll employment rose by 123,000 in July{tails[2]}. "
        f"Total nonfarm payroll employment changed little in July (+123,000)"
        f"{tails[3]}."
    )
    html = _page(title, pre)
    assert parse_release(html, "empsit_unemployment_rate") == ("2026-07", 4.1)
    assert parse_release(html, "empsit_payroll_change") == ("2026-07", 123.0)


# What a tail may not speak to: the statement's own basis, scope, measure,
# period or revision. No closed form holds any of these.
_REQUALIFIED = (
    # Basis.
    "after seasonal adjustment",
    "on a seasonally adjusted basis",
    "(not seasonally adjusted)",
    "Seasonally",
    "unadjusted",
    "adjusted",
    "excluding the population control adjustments",
    "without the strike",
    "on a three-month average basis",
    "before the annual benchmark",
    # Scope.
    "the national rate",
    "nationwide",
    "overall",
    "among the long-term unemployed",
    "for adults",
    "for adult women",
    "for teenagers",
    "for men",
    "for women",
    "for youth",
    "for veterans",
    "for Whites",
    "for Black workers",
    "for Asians",
    "for Hispanics",
    "for Latino workers",
    "for private employers",
    "in government",
    "in both sectors",
    "by industry",
    "in the Northeast region",
    "in most states",
    "in metropolitan areas",
    # Measure and period (round-6, round-7 and round-8 reviews).
    "the U.S. rate",
    "including discouraged workers in the labor force",
    "averaging the latest three months",
    "and by 120,000 for the month",
    "for the month",
    "over the month",
    "on the year",
    # Revision.
    "as revised",
    "after revision",
    "revisions",
)


@st.composite
def _requalified_tail(draw: st.DrawFn) -> str:
    """A tail of the closed forms for both readers (a comparison or trend),
    with a qualifier put in at any word boundary."""
    words = draw(_tail_words("payroll"))
    at = draw(st.integers(0, len(words)))
    comma = draw(st.sampled_from(((), (",",))))
    return _render(
        [*words[:at], *comma, draw(st.sampled_from(_REQUALIFIED)), *words[at:]]
    )


@settings(max_examples=300, deadline=None)
@given(tail=_requalified_tail())
def test_a_tail_speaking_to_the_statements_own_basis_unmakes_the_statement(
    tail: str,
) -> None:
    """Round-5 review, finding 1: such a sentence neither reads nor refuses."""
    _check_requalified(tail)


@pytest.mark.parametrize("phrase", _REQUALIFIED)
@pytest.mark.parametrize(
    "tail",
    (", compared with 3.9 percent in June", " and has remained unchanged since June"),
)
def test_each_word_naming_a_basis_scope_or_revision_unmakes_the_statement(
    phrase: str, tail: str
) -> None:
    _check_tails([tail, tail, tail, tail])
    _check_requalified(f"{tail} {phrase}")


def _check_requalified(tail: str) -> None:
    title = "Employment Situation Summary - 2026 M07 Results"
    head = "THE EMPLOYMENT SITUATION -- JULY 2026\n"
    requalified = (
        f"The unemployment rate was 4.8 percent in July{tail}. "
        f"The unemployment rate changed little at 4.8 percent in July{tail}. "
        f"Total nonfarm payroll employment rose by 999,000 in July{tail}. "
        f"Total nonfarm payroll employment changed little in July (+999,000){tail}."
    )
    for parser_id in _EMPSIT_IDS:
        assert parse_release(_page(title, head + requalified), parser_id) is None
    headline = (
        "The unemployment rate was 4.1 percent in July. "
        "The unemployment rate changed little at 4.1 percent in July. "
        "Total nonfarm payroll employment rose by 123,000 in July. "
        "Total nonfarm payroll employment changed little in July (+123,000)."
    )
    html = _page(title, f"{head}{headline} {requalified}")
    assert parse_release(html, "empsit_unemployment_rate") == ("2026-07", 4.1)
    assert parse_release(html, "empsit_payroll_change") == ("2026-07", 123.0)


def test_round_8_a_later_clause_never_supplies_the_monthly_change() -> None:
    """Round-8 review, finding 1, verbatim: it returned 2000."""
    title, head = _EMPSIT_JULY
    pre = (
        "Total nonfarm payroll employment rose by 2,000,000 in July, compared with "
        "a year earlier, and by 120,000 for the month.\n"
        "Total nonfarm payroll employment increased by 2,000,000 in July, compared "
        "with a year earlier, and by 120,000 for the month."
    )
    assert parse_release(_page(title, head + pre), "empsit_payroll_change") is None


def test_round_6_counterexamples_are_never_read() -> None:
    """Round-6 review, verbatim: each returned 4.8."""
    title = "Employment Situation Summary - 2026 M07 Results"
    head = "THE EMPLOYMENT SITUATION -- JULY 2026\n"
    abbreviated = (
        "The unemployment rate was 4.8 percent in July, compared with the U.S. rate "
        "of 4.1 percent on a seasonally adjusted basis.\n"
        "The unemployment rate stood at 4.8 percent in July, compared with the U.S. "
        "rate of 4.1 percent after seasonal adjustment."
    )
    measure = (
        "The unemployment rate was 4.1 percent.\n"
        "Alternative Measures of Labor Underutilization\n"
        "The unemployment rate was 4.8 percent in July, after including discouraged "
        "workers in the labor force.\n"
        "Annual Average Data for 2025\n"
        "The unemployment rate was 4.8 percent."
    )
    averaged = (
        "The unemployment rate was 4.8 percent in July, after averaging the latest "
        "three months.\n"
        "The unemployment rate stood at 4.8 percent in July, after averaging the "
        "latest three months."
    )
    for pre in (abbreviated, measure, averaged):
        assert (
            parse_release(_page(title, head + pre), "empsit_unemployment_rate") is None
        )
    # Were the U-4 sentence a statement, the undated statements, disagreeing
    # among themselves, still would not count: one dated statement remains.
    dated = measure.replace(
        ", after including discouraged workers in the labor force.", "."
    )
    assert parse_release(_page(title, head + dated), "empsit_unemployment_rate") is None


def test_a_tail_restating_the_figure_on_another_basis_is_never_read() -> None:
    """Round-5 review, finding 1, verbatim: it returned 4.8."""
    title = "Employment Situation Summary - 2026 M07 Results"
    pre = (
        "THE EMPLOYMENT SITUATION -- JULY 2026\n"
        "The unemployment rate was 4.8 percent in July but was 4.1 percent after "
        "seasonal adjustment.\n"
        "The unemployment rate stood at 4.8 percent in July but was 4.1 percent on "
        "a seasonally adjusted basis."
    )
    assert parse_release(_page(title, pre), "empsit_unemployment_rate") is None
    # Beside the headline, the same sentence is ignored, as is one saying
    # the headline was not seasonally adjusted.
    title, july = _empsit_text(_JULY)
    for added in (
        pre.split("\n", 1)[1],
        "The unemployment rate was 4.8 percent in July and was not seasonally "
        "adjusted.",
    ):
        html = _page(title, f"{july}\n\n{added}")
        for parser_id, reading in _readings(_JULY).items():
            assert parse_release(html, parser_id) == reading


@pytest.mark.parametrize(
    "continuation",
    (
        # Round-4 review, verbatim and its table.
        ", following little change in June (+36,000)",
        ", following gains of 34,000 in May and 41,000 in June",
        ", similar to the average monthly gain of 166,000 in 2019",
        ", compared with an average monthly gain of 158,000 thus far this year",
        ", below the average monthly gain of 168,000 over the past 12 months",
    ),
)
def test_a_payroll_continuation_is_read_as_a_tail(continuation: str) -> None:
    title = "Employment Situation Summary - 2026 M07 Results"
    pre = (
        "THE EMPLOYMENT SITUATION -- JULY 2026\n"
        "Total nonfarm payroll employment changed little in July (-23,000), and "
        "the unemployment rate was little changed at 4.1 percent, the U.S. Bureau "
        "of Labor Statistics reported today. "
        "Total nonfarm payroll employment changed little in July (-23,000)"
        f"{continuation}."
    )
    assert parse_release(_page(title, pre), "empsit_payroll_change") == (
        "2026-07",
        -23.0,
    )
    reported = pre.replace(
        f"{continuation}.",
        f"{continuation}, the U.S. Bureau of Labor Statistics (BLS) reported today.",
    )
    assert parse_release(_page(title, reported), "empsit_payroll_change") == (
        "2026-07",
        -23.0,
    )


@pytest.mark.parametrize(
    ("dated", "unsaid", "parser_id", "reading"),
    (
        (
            "The unemployment rate was little changed at 4.3 percent in May.",
            "The unemployment rate held at 4.3 percent and has remained in a narrow "
            "range of 4.3 percent to 4.5 percent since July 2025.",
            "empsit_unemployment_rate",
            4.3,
        ),
        (
            "Total nonfarm payroll employment increased by 142,000 in May.",
            "Total nonfarm payroll employment increased by 142,000 over the month.",
            "empsit_payroll_change",
            142.0,
        ),
        (
            "Total nonfarm payroll employment changed little in May (-23,000).",
            "Total nonfarm payroll employment changed little (-23,000).",
            "empsit_payroll_change",
            -23.0,
        ),
    ),
)
def test_a_statement_that_leaves_its_month_unsaid_only_corroborates(
    dated: str, unsaid: str, parser_id: str, reading: float
) -> None:
    """Real releases (May 2026, August 2024) state one figure without its month."""
    title = "Employment Situation Summary - 2026 M05 Results"
    head = "THE EMPLOYMENT SITUATION -- MAY 2026\n"

    def read(*sentences: str) -> tuple[str, float] | None:
        return parse_release(_page(title, head + " ".join(sentences)), parser_id)

    figure = re.search(r"[0-9]+[.,][0-9]+", unsaid)
    assert figure is not None
    other = unsaid.replace(
        figure.group(0), "9.9" if "." in figure.group(0) else "999,000", 1
    )
    # Dated and unsaid agreeing: read.
    assert read(dated, unsaid) == ("2026-05", reading)
    # Unsaid alone, even twice: no statement names the month.
    assert read(unsaid, unsaid) is None
    # Dated alone: one statement.
    assert read(dated) is None
    assert read(dated, unsaid, unsaid) == ("2026-05", reading)
    # Unsaid disagreeing never refuses, and no undated statement then
    # counts: one may be about another period, so none corroborates.
    assert read(dated, other) is None
    assert read(dated, dated, other) == ("2026-05", reading)
    assert read(dated, other, unsaid) is None
    assert read(dated, other, dated, unsaid) == ("2026-05", reading)
    assert read(other, other) is None
    # Where the release first names the measure, an undated statement is no
    # lead: refused, whatever follows.
    assert read(unsaid, dated, dated) is None
    assert read(other, dated, dated) is None


def test_an_undated_statement_never_refuses_the_page() -> None:
    """Round-5 review, finding 2: an annual average vetoed the headline."""
    title, july = _empsit_text(_JULY)
    for added in (
        "Annual Average Data for 2025\nThe unemployment rate was 4.0 percent.",
        "Total nonfarm payroll employment increased by 999,000 over the month.",
        # Contradicting itself, undated: ignored too.
        "Total nonfarm payroll employment edged up (-23,000).",
        "Both nonfarm payroll employment (-23,000) and the unemployment rate "
        "(4.1 percent) edged up.",
    ):
        html = _page(title, f"{july}\n\n{added}")
        for parser_id, reading in _readings(_JULY).items():
            assert parse_release(html, parser_id) == reading
    # Dated, such sentences refuse.
    for added, refused in (
        ("The unemployment rate was 4.0 percent in July.", _EMPSIT_IDS[:1]),
        (
            "Total nonfarm payroll employment edged up in July (-23,000).",
            _EMPSIT_IDS[1:],
        ),
        (
            "Both nonfarm payroll employment (-23,000) and the unemployment rate "
            "(4.1 percent) edged up in July.",
            _EMPSIT_IDS,
        ),
    ):
        html = _page(title, f"{july}\n\n{added}")
        for parser_id, reading in _readings(_JULY).items():
            expected = None if parser_id in refused else reading
            assert parse_release(html, parser_id) == expected


def test_an_undated_statement_contradicting_itself_stops_the_undated_counting() -> None:
    """Round-7 review: the mutant ignoring a self-contradicting undated
    statement in the unanimity check survived."""
    title = "Employment Situation Summary - 2026 M07 Results"
    head = "THE EMPLOYMENT SITUATION -- JULY 2026\n"
    pre = (
        "Total nonfarm payroll employment increased by 123,000 in July.\n"
        "Total nonfarm payroll employment increased by 123,000 over the month.\n"
    )
    html = _page(title, head + pre)
    assert parse_release(html, "empsit_payroll_change") == ("2026-07", 123.0)
    contradicted = "Total nonfarm payroll employment edged up (-23,000)."
    html = _page(title, head + pre + contradicted)
    assert parse_release(html, "empsit_payroll_change") is None


_ROUND_7 = (
    "THE EMPLOYMENT SITUATION -- JULY 2026\n"
    "Total nonfarm payroll employment rose by 120,000 in July, following no change "
    "in June.\n"
    "Total nonfarm payroll employment rose by 2,000,000 in July, compared with a "
    "year earlier.\n"
    "Total nonfarm payroll employment increased by 2,000,000 in July compared with "
    "the previous year."
)


def test_round_7_annual_comparisons_never_supply_the_monthly_change() -> None:
    """Round-7 review, finding 1, verbatim: it returned 2000."""
    title = "Employment Situation Summary - 2026 M07 Results"
    assert parse_release(_page(title, _ROUND_7), "empsit_payroll_change") is None
    # The true headline is a statement ("following no change in June" is a
    # comparison), and with a second statement it reads, beside the annual
    # comparisons.
    second = "\nTotal nonfarm payroll employment rose by 120,000 in July."
    assert parse_release(_page(title, _ROUND_7 + second), "empsit_payroll_change") == (
        "2026-07",
        120.0,
    )


def test_the_figure_is_the_one_stated_where_the_release_first_names_it() -> None:
    """Round-7 review, finding 1: with the true lead unread, other statements
    of another figure supplied it."""
    title = "Employment Situation Summary - 2026 M07 Results"
    head = "THE EMPLOYMENT SITUATION -- JULY 2026\n"
    annual = (
        "Total nonfarm payroll employment rose by 2,000,000 in July, up from a "
        "gain of 1,800,000 a year earlier.\n"
        "Total nonfarm payroll employment increased by 2,000,000 in July, up from "
        "a gain of 1,800,000 a year earlier."
    )
    # Alone, the two sentences are statements, and read.
    assert parse_release(_page(title, head + annual), "empsit_payroll_change") == (
        "2026-07",
        2000.0,
    )
    # After a lead the reader cannot read, nothing does.
    for lead in (
        "Total nonfarm payroll employment rose by 120,000 in July, following "
        "unusually strong hiring in June.",
        "Total nonfarm payroll employment rose by 120,000 in July.\n\n",
        "In June, total nonfarm payroll employment rose by 87,000.",
        "Private nonfarm payroll employment rose by 2,000,000 in July.",
        "Total nonfarm payroll employment rose by 2,000,000 over the month.",
    ):
        html = _page(title, f"{head}{lead}\n{annual}")
        expected = None
        assert parse_release(html, "empsit_payroll_change") == expected, lead
    # A lead stating the figure reads it, and one stating another refuses.
    for lead, expected in (
        ("Total nonfarm payroll employment rose by 2,000,000 in July.", 2000.0),
        ("Total nonfarm payroll employment rose by 120,000 in July.", None),
    ):
        html = _page(title, f"{head}{lead}\n{annual}")
        reading = None if expected is None else ("2026-07", expected)
        assert parse_release(html, "empsit_payroll_change") == reading


def test_the_lead_is_found_whatever_its_case() -> None:
    title = "Employment Situation Summary - 2026 M07 Results"
    pre = (
        "THE EMPLOYMENT SITUATION -- JULY 2026\n"
        "Nonfarm payroll employment rose by 87,000 in July.\n"
        "In June, total nonfarm payroll employment rose by 41,000.\n"
        "Nonfarm payroll employment increased by 87,000 in July."
    )
    assert parse_release(_page(title, pre), "empsit_payroll_change") == (
        "2026-07",
        87.0,
    )


@pytest.mark.parametrize(
    ("title", "heading", "mention", "statements", "parser_id", "reading"),
    (
        (
            "Employment Situation Summary - 2026 M07 Results",
            "THE EMPLOYMENT SITUATION -- JULY 2026",
            "Unemployment rates by race are shown in table A-2.",
            "The unemployment rate was 4.1 percent in July. "
            "The unemployment rate changed little at 4.1 percent in July.",
            "empsit_unemployment_rate",
            ("2026-07", 4.1),
        ),
        (
            "Job Openings and Labor Turnover Summary - 2026 M06 Results",
            "JOB OPENINGS AND LABOR TURNOVER -- JUNE 2026",
            "Job openings by industry are shown in table 1.",
            "The number of job openings was little changed at 7.4 million in June. "
            "The number of job openings was 7.4 million in June.",
            "jolts_job_openings",
            ("2026-06", 7.4),
        ),
    ),
)
def test_a_mention_in_capitals_before_the_headline_is_the_lead(
    title: str,
    heading: str,
    mention: str,
    statements: str,
    parser_id: str,
    reading: tuple[str, float],
) -> None:
    """The lead is where the release first names the measure, in any case."""
    assert parse_release(_page(title, f"{heading}\n{statements}"), parser_id) == reading
    html = _page(title, f"{heading}\n{mention}\n{statements}")
    assert parse_release(html, parser_id) is None


def test_round_8_red_team_a_label_before_the_lead_refuses_the_page() -> None:
    """Round-8 red team (r8a), finding 2, verbatim: it returned the
    unadjusted 4.8, though the page says the adjusted rate is 4.1."""
    title, _ = _EMPSIT_JULY
    pre = (
        "THE EMPLOYMENT SITUATION -- JULY 2026\n"
        "Not seasonally adjusted:\n"
        "The unemployment rate was 4.8 percent in July.\n"
        "The unemployment rate was 4.8 percent.\n"
        "The seasonally adjusted unemployment rate for July was 4.1 percent."
    )
    assert parse_release(_page(title, pre), "empsit_unemployment_rate") is None


# What may stand between a heading and the lead on a forged or rearranged
# page. None is a sound dated statement of the month.
_BEFORE_THE_LEAD = (
    "Not seasonally adjusted:",
    "NOT SEASONALLY ADJUSTED",
    "The figures below are not seasonally adjusted.",
    "Puerto Rico",
    "Table A. Household data, not seasonally adjusted",
    "-",
    "(p)",
    "In June, total nonfarm payroll employment rose by 87,000.",
    "Total nonfarm payroll employment rose by 87,000 in June.",
    "Total nonfarm payroll employment rose by 87,000.",
    "Total nonfarm payroll employment rose by 87,000 in July 2025.",
    "Total nonfarm payroll employment changed little (+87,000) in July, after "
    "seasonal adjustment.",
)


@settings(max_examples=200, deadline=None)
@given(case=_empsit(), before=st.sampled_from(_BEFORE_THE_LEAD))
def test_nothing_but_the_releases_statements_may_come_before_the_lead(
    case: dict, before: str
) -> None:
    title, pre = _empsit_text(case)
    heading, rest = pre.split("\n\n", 1)
    html = _page(title, f"{heading}\n\n{before}\n\n{rest}")
    for parser_id in _EMPSIT_IDS:
        assert parse_release(html, parser_id) is None


def test_the_release_may_open_with_payrolls_before_the_rate() -> None:
    """The 2025 releases state payrolls in their first sentence and the rate
    in their second: a sound dated statement of the month may come first."""
    title, head = _EMPSIT_JULY
    payroll = (
        "Total nonfarm payroll employment changed little in July (+73,000) and has "
        "shown little change since April, the U.S. Bureau of Labor Statistics (BLS) "
        "reported today."
    )
    rest = (
        "The unemployment rate changed little at 4.2 percent in July.\n"
        "Household Survey Data\n"
        "The unemployment rate was 4.2 percent in July.\n"
        "Establishment Survey Data\n"
        "Total nonfarm payroll employment rose by 73,000 in July."
    )
    html = _page(title, f"{head}{payroll}\n{rest}")
    assert parse_release(html, "empsit_unemployment_rate") == ("2026-07", 4.2)
    assert parse_release(html, "empsit_payroll_change") == ("2026-07", 73.0)
    # A payroll sentence of another month, undated, contradicting itself or
    # in no form may not open it.
    for first in (
        payroll.replace("July", "June"),
        payroll.replace(" in July", ""),
        payroll.replace("changed little", "edged down"),
        payroll.replace(" and has", ", not seasonally adjusted, and has"),
    ):
        html = _page(title, f"{head}{first}\n{rest}")
        assert parse_release(html, "empsit_unemployment_rate") is None, first


# Sentences in the readers' own forms, of any figure, month and year, with
# or without a tail, for the property below.
_ANY_TAILS = (
    "",
    ", following little change in June (+36,000)",
    ", compared with an average monthly gain of 158,000 over the prior 12 months",
    " and has remained in a narrow range of 4.0 percent to 4.2 percent since May",
    ", the U.S. Bureau of Labor Statistics reported today",
    ", compared with a year earlier",
    ", up from a gain of 1,800,000 a year earlier",
    ", after seasonal adjustment",
    ", following unusually strong hiring in June",
)
_RATES = ("3.9", "4.1", "4.8")
_CHANGES = (-23, 57, 123, 2000)


@st.composite
def _any_sentence(
    draw: st.DrawFn,
    rates: tuple[str, ...] = _RATES,
    changes: tuple[int, ...] = _CHANGES,
    months: tuple[str, ...] = ("June", "July", "August"),
) -> str:
    month = draw(st.sampled_from(months))
    whens = ("", " over the month", f" in {month}", f" in {month} 2025")
    when = draw(st.sampled_from(whens if len(months) > 1 else whens[:3]))
    tail = draw(st.sampled_from(_ANY_TAILS))
    rate = draw(st.sampled_from(rates))
    change = draw(st.sampled_from(changes))
    signed, count = _signed(change), _count(change)
    verb = draw(st.sampled_from(("rose by", "increased by", "declined by", "fell by")))
    words = draw(st.sampled_from(("changed little", "edged up", "edged down")))
    return draw(
        st.sampled_from(
            (
                f"The unemployment rate was {rate} percent{when}{tail}.",
                f"The unemployment rate ({rate} percent) changed little{when}{tail}.",
                f"In {month}, the unemployment rate was {rate} percent{tail}.",
                f"The unemployment rate for teenagers was {rate} percent{when}.",
                f"Total nonfarm payroll employment {verb} {count}{when}{tail}.",
                f"Total nonfarm payroll employment {words}{when} ({signed}){tail}.",
                f"Private nonfarm payroll employment {verb} {count}{when}.",
                f"Both nonfarm payroll employment ({signed}) and the unemployment rate "
                f"({rate} percent) {words}{when}{tail}.",
                f"Total nonfarm payroll employment {verb} {count}{when}, and the "
                f"unemployment rate changed little at {rate} percent{tail}.",
            )
        )
    )


@st.composite
def _lead(draw: st.DrawFn, parser_id: str) -> tuple[str, float | None, str | int]:
    """A lead for the reader, the July figure it states (None if none), and
    the figure it prints."""
    tail = draw(st.sampled_from(_ANY_TAILS[:5]))
    if parser_id == "empsit_unemployment_rate":
        rate = draw(st.sampled_from(_RATES))
        stated = (
            f"The unemployment rate was {rate} percent in July{tail}.",
            f"The unemployment rate changed little at {rate} percent in July{tail}.",
            f"In July, the unemployment rate was {rate} percent{tail}.",
            f"Both nonfarm payroll employment (+57,000) and the unemployment rate "
            f"({rate} percent) changed little in July{tail}.",
        )
        unstated = (
            f"The unemployment rate was {rate} percent in July, after including "
            "discouraged workers in the labor force.",
            f"The unemployment rate for teenagers was {rate} percent in July.",
            f"The unemployment rate was {rate} percent.",
            f"The unemployment rate was {rate} percent in July, compared with a year "
            "earlier.",
            f"In June, the unemployment rate was {rate} percent.",
        )
        figure, printed = float(rate), rate
    else:
        change = draw(st.sampled_from(_CHANGES))
        signed, count = _signed(change), _count(change)
        verb = "rose" if change > 0 else "fell"
        stated = (
            f"Total nonfarm payroll employment {verb} by {count} in July{tail}.",
            f"Total nonfarm payroll employment changed little in July ({signed})"
            f"{tail}.",
            f"Total nonfarm payroll employment {verb} by {count} in July, and the "
            f"unemployment rate changed little at 4.1 percent{tail}.",
        )
        unstated = (
            f"Total nonfarm payroll employment {verb} by {count} in July, following "
            "unusually strong hiring in June.",
            f"Private nonfarm payroll employment {verb} by {count} in July.",
            f"Total nonfarm payroll employment {verb} by {count} over the month.",
            f"Total nonfarm payroll employment {verb} by {count} in July, compared "
            "with a year earlier.",
            f"In June, total nonfarm payroll employment {verb} by {count}.",
        )
        figure, printed = float(change), change
    if draw(st.booleans()):
        return draw(st.sampled_from(stated)), figure, printed
    return draw(st.sampled_from(unstated)), None, printed


@settings(max_examples=400, deadline=None)
@given(data=st.data(), parser_id=st.sampled_from(_EMPSIT_IDS))
def test_whatever_follows_the_lead_the_reader_returns_its_figure_or_nothing(
    data: st.DataObject, parser_id: str
) -> None:
    """Round-7 review: the guarantee holds for any page, not one fixture.

    However the sentences after the lead are worded (statements of any
    figure, month or year, with tails a reader may or may not admit,
    decoys), the reader returns the July figure the lead states, or refuses.
    A lead that states no July figure refuses the page.
    """
    lead, figure, printed = data.draw(_lead(parser_id))
    # Sentences of any figures; all of one figure, so that they agree among
    # themselves as a wrong figure stated twice would; or the lead's own
    # figure for July, so that the page reads unless the lead is no
    # statement.
    mode = data.draw(st.sampled_from(("any", "one figure", "echo")))
    if mode == "any":
        sentence = _any_sentence()
    elif mode == "one figure":
        sentence = _any_sentence(
            (data.draw(st.sampled_from(_RATES)),),
            (data.draw(st.sampled_from(_CHANGES)),),
        )
    elif isinstance(printed, str):
        sentence = _any_sentence((printed,), _CHANGES, ("July",))
    else:
        sentence = _any_sentence(_RATES, (printed,), ("July",))
    body = data.draw(st.lists(sentence, min_size=1, max_size=6))
    gaps = data.draw(st.lists(st.sampled_from((" ", "\n", "\n\n")), min_size=6))
    text = lead + "".join(gap + sentence for gap, sentence in zip(gaps, body))
    html = _page(
        "Employment Situation Summary - 2026 M07 Results",
        f"THE EMPLOYMENT SITUATION -- JULY 2026\n\n{text}",
    )
    got = parse_release(html, parser_id)
    stated = "stated" if figure is not None else "unstated"
    event(f"{mode}, {stated} lead: {'read' if got else 'refused'}")
    allowed = (None,) if figure is None else (None, ("2026-07", figure))
    assert got in allowed, (lead, body, got)


def test_a_rate_lead_carrying_the_payroll_clause_is_checked_like_one() -> None:
    """Real release, July 2024: the payroll clause takes the rate's month."""
    title = "Employment Situation Summary - 2026 M07 Results"
    lead = (
        "The unemployment rate rose to 4.3 percent in July, and nonfarm payroll "
        "employment edged up by 114,000, the U.S. Bureau of Labor Statistics "
        "reported today."
    )
    sections = (
        "The unemployment rate rose by 0.2 percentage point to 4.3 percent in July, "
        "and the number of unemployed people increased by 352,000 to 7.2 million. "
        "Total nonfarm payroll employment edged up by 114,000 in July, below the "
        "average monthly gain of 215,000 over the prior 12 months."
    )
    html = _page(title, f"THE EMPLOYMENT SITUATION -- JULY 2026\n{lead} {sections}")
    assert parse_release(html, "empsit_unemployment_rate") == ("2026-07", 4.3)
    assert parse_release(html, "empsit_payroll_change") == ("2026-07", 114.0)
    signed = lead.replace("edged up by 114,000", "changed little (-114,000)")
    contradicted = signed.replace("changed little", "edged up")
    for text, readings in (
        (
            signed,
            {
                "empsit_unemployment_rate": ("2026-07", 4.3),
                "empsit_payroll_change": None,
            },
        ),
        (
            contradicted,
            {"empsit_unemployment_rate": None, "empsit_payroll_change": None},
        ),
    ):
        page = _page(title, f"THE EMPLOYMENT SITUATION -- JULY 2026\n{text} {sections}")
        for parser_id, reading in readings.items():
            assert parse_release(page, parser_id) == reading
    # The rate's month is the clause's: a June rate lead dates the payroll
    # clause June too, and refuses the page.
    june = lead.replace("in July", "in June")
    page = _page(title, f"THE EMPLOYMENT SITUATION -- JULY 2026\n{june} {sections}")
    for parser_id in _EMPSIT_IDS:
        assert parse_release(page, parser_id) is None


@pytest.mark.parametrize(
    ("clause", "payroll"),
    (
        (", and nonfarm payroll employment (+57,000) changed little", 57),
        (
            ", while total nonfarm payroll employment (-57,000) was essentially flat",
            -57,
        ),
    ),
)
def test_a_rate_lead_whose_payroll_clause_prints_its_figure_first_is_checked(
    clause: str, payroll: int
) -> None:
    """Round-5 review: the figure-before-verb clause was untested."""
    title = "Employment Situation Summary - 2026 M07 Results"
    head = "THE EMPLOYMENT SITUATION -- JULY 2026\n"
    sections = (
        "The unemployment rate was 4.1 percent in July. "
        f"Total nonfarm payroll employment changed little in July ({_signed(payroll)})."
    )

    def lead(text: str) -> str:
        return (
            f"The unemployment rate was little changed at 4.1 percent in July{text}, "
            "the U.S. Bureau of Labor Statistics reported today."
        )

    html = _page(title, f"{head}{lead(clause)} {sections}")
    assert parse_release(html, "empsit_unemployment_rate") == ("2026-07", 4.1)
    assert parse_release(html, "empsit_payroll_change") == ("2026-07", float(payroll))
    # The lead disagreeing with the payroll section refuses the payroll reader.
    other = clause.replace(_count(payroll), "58,000")
    html = _page(title, f"{head}{lead(other)} {sections}")
    assert parse_release(html, "empsit_unemployment_rate") == ("2026-07", 4.1)
    assert parse_release(html, "empsit_payroll_change") is None
    # Its verb contradicting its sign refuses both readers.
    verb = "edged down" if payroll > 0 else "edged up"
    contradicted = re.sub(r"\) .*", f") {verb}", clause)
    html = _page(title, f"{head}{lead(contradicted)} {sections}")
    for parser_id in _EMPSIT_IDS:
        assert parse_release(html, parser_id) is None


def test_qualified_statements_never_supply_the_rate() -> None:
    """Round-3 review, finding 1, verbatim: they returned 4.8."""
    title = "Employment Situation Summary - 2026 M07 Results"
    pre = (
        "THE EMPLOYMENT SITUATION -- JULY 2026\n"
        "In July, the unemployment rate was unchanged at 4.1 percent.\n"
        "The unemployment rate was unchanged at 4.1 percent in July and has "
        "remained in a narrow range of 4.0 percent to 4.2 percent since January.\n"
        "The unemployment rate was 4.8 percent in July, a year earlier.\n"
        "The unemployment rate (4.8 percent) was unchanged in July (2025)."
    )
    assert parse_release(_page(title, pre), "empsit_unemployment_rate") == (
        "2026-07",
        4.1,
    )


@settings(max_examples=100, deadline=None)
@given(case=_empsit(), lead=st.sampled_from((0, 2, 4, 6)))
def test_a_lead_whose_payroll_verb_contradicts_its_sign_refuses_both_readers(
    case: dict, lead: int
) -> None:
    """Round-3 review, finding 4: a rate statement's payroll clause is checked."""
    case = {**case, "lead": lead}
    title, pre = _empsit_text(case)
    heading, statement, rest = pre.split("\n\n", 2)
    assert statement.count("changed little") == 1
    down = case["payroll"] < 0
    for verb, refused in (("edged up", down), ("edged down", not down)):
        changed = statement.replace("changed little", verb)
        html = _page(title, f"{heading}\n\n{changed}\n\n{rest}")
        for parser_id, reading in _readings(case).items():
            assert parse_release(html, parser_id) == (None if refused else reading)


def test_a_page_without_exactly_one_preformatted_block_is_refused() -> None:
    title, pre = _empsit_text(_JULY)
    assert parse_release(_page(title, pre), "empsit_payroll_change") == (
        "2026-07",
        -23.0,
    )
    for pres in (0, 2):
        for parser_id in PROSE_PARSERS:
            assert parse_release(_page(title, pre, pres=pres), parser_id) is None


def test_round_8_red_team_a_commented_out_block_is_no_block() -> None:
    """Round-8 red team (r8a), finding 3, verbatim: it returned 4.8."""
    page = (
        "<title>Employment Situation Summary - 2026 M07 Results</title><!--<pre>THE "
        "EMPLOYMENT SITUATION -- JULY 2026\nThe unemployment rate was 4.8 percent in "
        "July.\nThe unemployment rate was 4.8 percent.</pre>--><p>The unemployment "
        "rate was 4.1 percent in July.</p>"
    )
    assert parse_release(page, "empsit_unemployment_rate") is None


def test_only_a_real_preformatted_element_is_the_release() -> None:
    title, pre = _empsit_text(_JULY)
    html = _page(title, pre)
    reading = ("2026-07", -23.0)
    assert parse_release(html, "empsit_payroll_change") == reading
    # A block in a comment or a script is no block, whatever it says.
    forged = (
        "<pre>THE EMPLOYMENT SITUATION -- JULY 2026\n"
        "Total nonfarm payroll employment rose by 999,000 in July.\n"
        "Total nonfarm payroll employment rose by 999,000 in July.</pre>"
    )
    for hidden in (f"<!--{forged}-->", f"<script>var s = '{forged}';</script>"):
        for at in ("<div>", "<p>Footer</p>"):
            page = html.replace(at, f"{hidden}{at}", 1)
            assert parse_release(page, "empsit_payroll_change") == reading, hidden
    # Inside the block a tag or comment is a word break.
    marked = html.replace(
        "THE EMPLOYMENT SITUATION", "THE<!-- x -->EMPLOYMENT<b>SITUATION</b>", 1
    )
    assert parse_release(marked, "empsit_payroll_change") == reading
    # A block never closed, or one inside another, is refused.
    for broken in (
        html.replace("</pre>", ""),
        html.replace("<pre>", "<pre><pre>", 1),
        html.replace("</pre>", "<pre></pre>"),
    ):
        assert parse_release(broken, "empsit_payroll_change") is None


@settings(max_examples=50, deadline=None)
@given(case=_empsit(), offset=st.integers(1, 11))
def test_a_heading_month_the_title_does_not_name_is_refused(
    case: dict, offset: int
) -> None:
    title, pre = _empsit_text(case)
    name = MONTHS[case["month"] - 1]
    other = MONTHS[(case["month"] - 1 + offset) % 12]
    for printed in (other.upper(), other):
        changed = re.sub(rf"-- {name} 2026", f"-- {printed} 2026", pre, flags=re.I)
        assert changed != pre
        for parser_id in _EMPSIT_IDS:
            assert parse_release(_page(title, changed), parser_id) is None


@pytest.mark.parametrize(
    ("code", "heading", "reading"),
    (
        ("M12", "DECEMBER", "2025-12"),
        ("M13", "DECEMBER", "2025-12"),
        ("M13", "December", "2025-12"),
        ("M13", "NOVEMBER", None),
        ("M14", "DECEMBER", None),
        ("M00", "DECEMBER", None),
    ),
)
def test_the_december_release_titled_m13_is_december(
    code: str, heading: str, reading: str | None
) -> None:
    """Real captures: BLS titles the December Employment Situation "M13"."""
    title = f"Employment Situation Summary - 2025 {code} Results"
    pre = (
        f"THE EMPLOYMENT SITUATION -- {heading} 2025\n"
        "Total nonfarm payroll employment increased by 256,000 in December, and "
        "the unemployment rate changed little at 4.1 percent, the U.S. Bureau of "
        "Labor Statistics reported today. "
        "The unemployment rate changed little at 4.1 percent in December. "
        "Total nonfarm payroll employment rose by 256,000 in December."
    )
    html = _page(title, pre)
    for parser_id, value in (
        ("empsit_unemployment_rate", 4.1),
        ("empsit_payroll_change", 256.0),
    ):
        expected = None if reading is None else (reading, value)
        assert parse_release(html, parser_id) == expected


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
    # A verb that contradicts its printed sign says two things: refused,
    # even when every statement prints the same figure.
    flipped = f"{'-' if sign > 0 else '+'}41,000"
    both = (
        "THE EMPLOYMENT SITUATION -- SEPTEMBER 2026\n"
        f"Total nonfarm payroll employment {verb} in September ({flipped}). "
        f"Total nonfarm payroll employment ({flipped}) {verb} in September."
    )
    assert parse_release(_page(title, both), "empsit_payroll_change") is None
    neutral = both.replace(f" {verb} in", " changed little in")
    assert parse_release(_page(title, neutral), "empsit_payroll_change") == (
        "2026-09",
        -41.0 * sign,
    )


def test_a_unicode_minus_is_a_minus() -> None:
    title = "Employment Situation Summary - 2026 M07 Results"
    pre = (
        "THE EMPLOYMENT SITUATION -- JULY 2026\n"
        "Total nonfarm payroll employment changed little in July (\u221223,000). "
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
        "lead": draw(st.integers(0, 6)),
        "section": draw(st.integers(0, 2)),
        "change": draw(st.integers(1, 999)),
        "dash": draw(st.sampled_from(("-", "--", "—", "�"))),
    }


def _jolts_page(
    case: dict,
    *,
    second: bool = True,
    month: str | None = None,
    lead: str | None = None,
) -> str:
    name = MONTHS[case["month"] - 1]
    prior = MONTHS[case["month"] - 2]
    openings = f"{case['openings']:.1f}"
    lead = (
        (
            f"The number of job openings was little changed at {openings} million "
            f"in {name}, the U.S. Bureau of Labor Statistics reported today.",
            f"The number of job openings {'rose' if case['month'] % 2 else 'fell'} "
            f"to {openings} million in {name}.",
            f"The number of job openings decreased by 300,000 to {openings} million "
            f"in {name}.",
            f"The number of job openings was little changed at {openings} million "
            f"on the last business day of {name}, the U.S. Bureau of Labor "
            "Statistics reported today.",
            # Real releases, November and December 2025.
            f"The number of job openings continued to trend down to {openings} "
            f"million in {name}, the U.S. Bureau of Labor Statistics reported today.",
            f"The number of job openings trended down to {openings} million "
            f"(-{case['change']},000) in {name} and was down by 966,000 over the year.",
            f"The number of job openings was little changed at {openings} million in "
            f"{name} but was down by 885,000 over the year.",
        )[case["lead"]]
        if lead is None
        else lead
    )
    section = (
        f"The number and rate of job openings were little changed at {openings} "
        f"million and {case['rate']:.1f} percent, respectively, in "
        f"{month or name}.",
        # Real release, April 2026.
        f"The number and rate of job openings increased to {openings} million "
        f"(+{case['change']},000) and {case['rate']:.1f} percent, respectively, "
        f"in {month or name}.",
        # The month unsaid: a supporting statement.
        f"The number of job openings was little changed at {openings} million "
        "over the month.",
    )[case["section"]]
    if not second:
        section = "Job openings changed little in most industries."
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
    html = _jolts_page({**case, "section": 0}).replace(
        f"changed at {openings} million and", f"changed at {other} million and"
    )
    assert parse_release(html, "jolts_job_openings") is None


@settings(max_examples=100, deadline=None)
@given(case=_jolts(), offset=st.integers(1, 11))
def test_jolts_openings_statement_naming_another_month_is_refused(
    case: dict, offset: int
) -> None:
    other = MONTHS[(case["month"] - 1 + offset) % 12]
    dated = {**case, "section": case["section"] % 2}
    assert parse_release(_jolts_page(dated, month=other), "jolts_job_openings") is None


@settings(max_examples=100, deadline=None)
@given(case=_jolts())
def test_jolts_openings_with_no_dated_statement_is_refused(case: dict) -> None:
    unsaid = (
        f"The number of job openings was little changed at {case['openings']:.1f} "
        "million over the month."
    )
    unsaid_only = {**case, "section": 2}
    assert parse_release(_jolts_page(unsaid_only), "jolts_job_openings") is not None
    html = _jolts_page(unsaid_only, lead=unsaid)
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
            "section": 0,
            "change": 731,
            "dash": "�",
        }
    )
    assert parse_release(jolts, "jolts_job_openings") == ("2026-06", 7.4)
    for parser_id in _EMPSIT_IDS:
        assert parse_release(jolts, parser_id) is None
    empsit = _page(*_empsit_text(_JULY))
    assert parse_release(empsit, "jolts_job_openings") is None
