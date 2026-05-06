from fa.merge import union_rows
from fa.normalize import parse_number


def test_parse_parentheses_negative():
    assert parse_number("(1,234)") == -1234


def test_union_rows_preserves_missing_as_blank():
    periods = ["2023", "2024"]
    rows = {"Cash": {"2023": 100}, "Inventory": {"2024": 50}}
    out = union_rows(rows, periods)
    assert out["Cash"]["2024"] is None
    assert out["Inventory"]["2023"] is None
