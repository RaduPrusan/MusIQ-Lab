import inspect

from analyze.pipeline import analyze


def test_skip_stages_param_accepted():
    """analyze() must accept a skip_stages kwarg.

    Surface-level signature check — full integration is implied by the
    pipeline's stage-loop being parameterized over skip_stages.
    """
    sig = inspect.signature(analyze)
    assert "skip_stages" in sig.parameters
    # Must be a keyword-only parameter (the analyze() signature uses
    # keyword-only args after the * marker).
    param = sig.parameters["skip_stages"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY
    # Defaults to None so existing callers don't break.
    assert param.default is None


def test_no_identify_flag_exists_in_cli():
    """--no-identify must be a recognized argparse flag."""
    import argparse
    from analyze import cli

    # Re-build the parser the same way cli.main does, just to interrogate it.
    # The simplest portable way is to call main with --help and observe the
    # SystemExit; but that's noisy. Instead, monkey-test that argparse
    # accepts --no-identify by parsing a minimal valid arg list.
    parser = argparse.ArgumentParser()
    # ... but we want to actually test the real parser.

    # Strategy: capture the parser by patching ArgumentParser.parse_args
    # to return its args before main calls analyze().
    captured = {}
    real_parse = argparse.ArgumentParser.parse_args

    def fake_parse(self, argv=None):
        ns = real_parse(self, argv)
        captured["ns"] = ns
        captured["parser"] = self
        raise SystemExit(0)  # short-circuit before any real work

    import pytest
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(argparse.ArgumentParser, "parse_args", fake_parse)
        try:
            cli.main(["/nonexistent.mp3", "--no-identify"])
        except SystemExit:
            pass
    finally:
        monkey.undo()

    ns = captured.get("ns")
    assert ns is not None, "parse_args was not reached"
    assert getattr(ns, "no_identify", None) is True
