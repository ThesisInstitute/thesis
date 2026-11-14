"""The regex string escaper must match the rule it replaced, character by character.

canonical_json hashes commit every custody root and log chunk, so one changed
byte would break the record chain. `reference_serialize_string` is the
character-at-a-time definition the escaper has to reproduce. Parity with the
TypeScript implementation lives in
site/src/__tests__/canonical-json-python-parity.test.ts.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest
from hypothesis import given
from hypothesis import strategies as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from canonical_json import (  # noqa: E402
    _serialize_string,
    canonical_sha256,
    canonical_stringify,
)

MAX_CODE_POINT = 0x10FFFF
BLOCK = 0x1000


def reference_serialize_string(value: str) -> str:
    pieces = ['"']
    short_escapes = {
        "\b": "\\b",
        "\t": "\\t",
        "\n": "\\n",
        "\f": "\\f",
        "\r": "\\r",
        '"': '\\"',
        "\\": "\\\\",
    }
    for char in value:
        if char in short_escapes:
            pieces.append(short_escapes[char])
        elif ord(char) < 0x20 or 0xD800 <= ord(char) <= 0xDFFF:
            pieces.append(f"\\u{ord(char):04x}")
        else:
            pieces.append(char)
    pieces.append('"')
    return "".join(pieces)


def test_every_code_point_serializes_as_the_reference_does() -> None:
    # The escaper decides each character alone, so agreement on every code
    # point, in order and with neighbours, covers strings of any length.
    for start in range(0, MAX_CODE_POINT + 1, BLOCK):
        block = "".join(
            chr(point) for point in range(start, min(start + BLOCK, MAX_CODE_POINT + 1))
        )
        assert _serialize_string(block) == reference_serialize_string(block), hex(start)


# st.text() almost never yields a lone surrogate, even from an alphabet that holds
# them, so this joins characters and weights the ones the escaper treats specially.
ANY_TEXT = st.lists(
    st.one_of(
        st.characters(),
        st.sampled_from(
            [
                '"',
                "\\",
                "\b",
                "\t",
                "\n",
                "\f",
                "\r",
                "\x00",
                "\x1f",
                "\x7f",
                "퟿",
                "\ud800",
                "\udbff",
                "\udc00",
                "\udfff",
                "",
                "😀",
            ]
        ),
    )
).map("".join)


@given(ANY_TEXT)
def test_any_text_serializes_as_the_reference_does(value: str) -> None:
    assert _serialize_string(value) == reference_serialize_string(value)


@given(st.text())
def test_serialized_text_round_trips_through_json(value: str) -> None:
    assert json.loads(_serialize_string(value)) == value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", '""'),
        ("plain", '"plain"'),
        ('a"b\\c', '"a\\"b\\\\c"'),
        ("\b\t\n\f\r", '"\\b\\t\\n\\f\\r"'),
        ("\x00\x1f", '"\\u0000\\u001f"'),
        ("\x7f", '"\x7f"'),
        ("\ud83d", '"\\ud83d"'),
        ("\udfff", '"\\udfff"'),
        ("퟿", '"퟿"'),
        ("😀", '"😀"'),
    ],
)
def test_pinned_escapes(value: str, expected: str) -> None:
    assert _serialize_string(value) == expected


def test_a_nested_document_keeps_its_pinned_hash() -> None:
    document = {
        "z": ['a"b\\c\n', "\x00", "\ud83d", "😀", 1e-7, -0.0, 1e21],
        "": {"퟿": None, "😀": True},
    }
    # Both values come from the character-at-a-time implementation.
    assert canonical_stringify(document) == (
        '{"z":["a\\"b\\\\c\\n","\\u0000","\\ud83d","😀",1e-7,0,1e+21],'
        '"":{"퟿":null,"😀":true}}'
    )
    assert (
        canonical_sha256(document)
        == "86fbe64b925d2332ed51d4928fa7cc0d28fa6f9f5d3d28e12a8da6ec25aadda7"
    )
