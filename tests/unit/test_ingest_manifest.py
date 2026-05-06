from fa.ingest import select_input_files


def test_selects_only_new_hashes():
    manifest = {"seen_hashes": ["h1"]}
    files = [("a.pdf", "h1"), ("b.pdf", "h2")]
    selected = select_input_files(files, manifest, explicit_files=None)
    assert selected == [("b.pdf", "h2")]


def test_explicit_files_override_manifest():
    manifest = {"seen_hashes": ["h1", "h2"]}
    files = [("a.pdf", "h1"), ("b.pdf", "h2")]
    selected = select_input_files(files, manifest, explicit_files=["a.pdf"])
    assert selected == [("a.pdf", "h1")]
