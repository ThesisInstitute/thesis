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
- after its month a statement holds only a tail, then optionally "the U.S.
  Bureau of Labor Statistics reported today", then its full stop. A tail
  opens with a comparison word, "and has ...", "and continued ...", "but
  was down by ..." or ", and the number of unemployed people", and holds
  only the reviewed words of a change, an average, a range, a trend or a
  period, with months and figures;
- anything else after the month (another period, subgroup, basis or
  measure: ", a year earlier", "after seasonal adjustment", "the U.S.
  rate", "after including discouraged workers") makes the sentence no
  statement, which neither supplies the figure nor refuses the page;
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
  is refused (None), never guessed.
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
        # Round-6 review: an abbreviation ends no tail early, and a tail holds
        # only the reviewed words, so no measure, period or scope follows.
        ", compared with the U.S. rate of 4.1 percent on a seasonally adjusted basis",
        ", compared with the U.S. rate of 4.1 percent",
        ", after including discouraged workers in the labor force",
        ", after averaging the latest three months",
        " and is 4.1 percent",
        ", the U.S. Bureau of Labor Statistics reported today on an adjusted basis",
        # "Before" opens no tail even when every word after it is reviewed:
        # the figure before a change is another figure.
        ", before a change of 0.3 percentage point",
        ", before the change",
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


# The words a tail may hold, as reviewed. The parser's own list must be
# exactly this one, so a word is added only with a test.
_TAIL_VOCABULARY = tuple(
    (
        # Articles, prepositions and conjunctions.
        "a an the of in to by at over since and or either than this its thus so "
        "far "
        # A change and its size.
        "change changes changed unchanged little net gain gains loss losses "
        "increase increases increased decrease decreases decreased decline "
        "declines declined rose fell edged up down percent percentage point "
        "points million "
        # An average, a range or a trend.
        "average monthly narrow range trend trended upward downward movement "
        "recent showing shown has have had remained continued was were "
        # A period.
        "month months year prior past previous earlier"
    ).split()
)


def test_the_tail_vocabulary_is_the_reviewed_one() -> None:
    assert legacy_release_parsers._TAIL_VOCABULARY == _TAIL_VOCABULARY


# What a tail may open with, and words it may hold after: other months and
# years, other figures, the reviewed words. None is capitalized but a month,
# so no tail holds a statement of its own.
_TAIL_OPENERS = (
    ", following",
    " following",
    ", after",
    ", compared with",
    " compared with",
    ", similar to",
    ", in line with",
    ", close to",
    ", about the same as",
    ", the same as",
    ", up from",
    ", down from",
    ", higher than",
    ", lower than",
    ", less than",
    ", more than",
    ", above",
    ", below",
    " and has",
    " and have",
    " and had",
    " and continued",
    " and remained",
    " but has",
    " but was down by",
    " and was up by",
    " and were down by",
    ", and the number of unemployed people",
    ", while the number of unemployed persons",
)
_TAIL_WORDS = (
    *MONTHS,
    "2024",
    "2025",
    "4.2 percent",
    "0.3 percentage point",
    "(+36,000)",
    "(-41,000)",
    "166,000",
    "a year earlier",
    "over the year",
    "over the prior 12 months",
    "the average monthly gain",
    "a narrow range of 4.0 percent to 4.2 percent",
    "thus far this year",
    "-13,000",
    "12",
    *_TAIL_VOCABULARY,
)


@st.composite
def _tail(draw: st.DrawFn) -> str:
    words = draw(st.lists(st.sampled_from(_TAIL_WORDS), max_size=12))
    # Words follow one another after a space or a comma.
    return draw(st.sampled_from(_TAIL_OPENERS)) + "".join(
        draw(st.sampled_from((" ", ", "))) + word for word in words
    )


@settings(max_examples=300, deadline=None)
@given(tails=st.lists(st.one_of(st.just(""), _tail()), min_size=4, max_size=4))
def test_no_tail_changes_what_a_statement_says(tails: list[str]) -> None:
    """Round-4 review: a continuation is a tail, and none of it is read."""
    _check_tails(tails)


@pytest.mark.parametrize("word", _TAIL_VOCABULARY)
def test_each_reviewed_word_may_be_part_of_a_tail(word: str) -> None:
    _check_tails([f", following {word}", f" and has {word}", "", f", below {word}"])
    # Each tail may also end "reported today", as a lead's does.
    reported = ", the U.S. Bureau of Labor Statistics (BLS) reported today"
    _check_tails([f", following {word}{reported}", "", "", f" and has {word}"])


@pytest.mark.parametrize(
    "figure",
    ("+36,000", "-13,000", "−13,000", "(+36,000)", "(-41,000)", "(−41,000)"),
)
def test_a_tail_figure_may_carry_any_printed_sign(figure: str) -> None:
    # A minus sign may be printed as a hyphen or as U+2212.
    _check_tails(
        ["", "", f", up from {figure} in June", f", following {figure} in June"]
    )


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
# period or revision. Each phrase holds a word outside the tail vocabulary.
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
    # Measure and period (round-6 review).
    "the U.S. rate",
    "including discouraged workers in the labor force",
    "averaging the latest three months",
    # Revision.
    "as revised",
    "after revision",
    "revisions",
)


@st.composite
def _requalified_tail(draw: st.DrawFn) -> str:
    words = [
        *draw(st.lists(st.sampled_from(_TAIL_WORDS), max_size=6)),
        draw(st.sampled_from(_REQUALIFIED)),
        *draw(st.lists(st.sampled_from(_TAIL_WORDS), max_size=6)),
    ]
    # Words follow one another after a space or a comma.
    return draw(st.sampled_from(_TAIL_OPENERS)) + "".join(
        draw(st.sampled_from((" ", ", "))) + word for word in words
    )


@settings(max_examples=300, deadline=None)
@given(tail=_requalified_tail())
def test_a_tail_speaking_to_the_statements_own_basis_unmakes_the_statement(
    tail: str,
) -> None:
    """Round-5 review, finding 1: such a sentence neither reads nor refuses."""
    _check_requalified(tail)


@pytest.mark.parametrize("phrase", _REQUALIFIED)
@pytest.mark.parametrize("opener", (", compared with 3.9 percent", " and has remained"))
def test_each_word_naming_a_basis_scope_or_revision_unmakes_the_statement(
    phrase: str, opener: str
) -> None:
    _check_requalified(f"{opener} {phrase}")


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
    assert read(other, dated, unsaid) is None
    assert read(other, dated, dated, unsaid) == ("2026-05", reading)
    assert read(other, other) is None


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
