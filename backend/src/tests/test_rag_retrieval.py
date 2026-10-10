from ai.rag_retrieval import load_age_profile, retrieve


def test_retrieve_ranks_by_term_overlap(tmp_path):
    (tmp_path / "aapl_10k.md").write_text("Apple annual report: revenue grew, margin expanded")
    (tmp_path / "macro.txt").write_text("Fed rates and the S&P 500 index")
    (tmp_path / "statement.pdf").write_bytes(b"%PDF binary")

    hits = retrieve("Apple revenue margin", docs_dir=tmp_path)
    assert [h.source for h in hits] == ["aapl_10k.md"]


def test_retrieve_without_docs_folder(tmp_path):
    assert retrieve("anything", docs_dir=tmp_path / "missing") == []


def test_age_profiles_are_loaded_by_label_not_retrieved(tmp_path):
    profiles = tmp_path / "age_profiles"
    profiles.mkdir()
    (profiles / "18-24.md").write_text("Sourced profile for revenue-chasing 18-24s")

    assert load_age_profile("18-24", docs_dir=tmp_path).startswith("Sourced")
    assert load_age_profile("40-54", docs_dir=tmp_path) is None
    assert retrieve("revenue", docs_dir=tmp_path) == []
