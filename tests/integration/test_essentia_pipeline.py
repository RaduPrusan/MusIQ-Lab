from analyze import pipeline


def test_essentia_extract_registered():
    stage_names = [name for name, _ in pipeline._STAGE_EXECUTION_ORDER]
    assert "essentia_extract" in stage_names


def test_essentia_extract_is_optional():
    optional_names = [name for name, _ in pipeline.OPTIONAL_STAGES]
    assert "essentia_extract" in optional_names


def test_essentia_extract_runs_late():
    """essentia_extract must run AFTER beats + key so compute_agreement has
    something to compare against (the agreement is computed in the summary
    writer, but the stage MIGHT in the future use beat/key context)."""
    order = [name for name, _ in pipeline._STAGE_EXECUTION_ORDER]
    assert order.index("essentia_extract") > order.index("beats")
    assert order.index("essentia_extract") > order.index("key")


def test_essentia_extract_has_correct_deps():
    """STAGE_DEPS for essentia_extract includes beats + key (the
    agreement cross-check reads them). Selecting --stages-only essentia_extract
    requires beats + key already cached."""
    assert "essentia_extract" in pipeline.STAGE_DEPS
    deps = pipeline.STAGE_DEPS["essentia_extract"]
    assert "beats" in deps
    assert "key" in deps
