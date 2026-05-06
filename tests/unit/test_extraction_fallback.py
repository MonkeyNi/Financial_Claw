from fa.extract.repair import maybe_repair_table


def test_repair_triggered_only_low_confidence():
    table = {"rows": [["Revenue", "100"]], "confidence": 0.25}

    repaired = maybe_repair_table(
        table,
        enable_llm=True,
        threshold=0.4,
        repair_fn=lambda t: {"rows": t["rows"], "confidence": 0.9},
    )

    assert repaired["confidence"] == 0.9


def test_repair_skipped_when_llm_disabled():
    table = {"rows": [["Revenue", "100"]], "confidence": 0.1}
    repaired = maybe_repair_table(
        table,
        enable_llm=False,
        threshold=0.4,
        repair_fn=lambda _: {"rows": [], "confidence": 1.0},
    )
    assert repaired is table


def test_no_repair_when_confidence_already_high():
    table = {"rows": [["Revenue", "100"]], "confidence": 0.9}

    repaired = maybe_repair_table(
        table,
        enable_llm=True,
        threshold=0.4,
        repair_fn=lambda _: {"rows": [], "confidence": 0.0},
    )

    assert repaired is table
