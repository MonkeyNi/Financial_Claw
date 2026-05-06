from fa.incremental import conflict_column_name


def test_conflict_column_name_annual():
    assert conflict_column_name("2024", "ReportA.pdf") == "2024 Conflict - ReportA.pdf"


def test_fuzz_in_grey_band():
    from fa.merge import fuzz_in_grey_band

    assert fuzz_in_grey_band(0.75) is True
    assert fuzz_in_grey_band(0.5) is False
