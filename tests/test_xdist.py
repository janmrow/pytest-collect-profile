from __future__ import annotations

import pytest

pytest.importorskip("xdist")


def _run_with_xdist(pytester, monkeypatch, *args):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    return pytester.runpytest_subprocess(
        "-p",
        "xdist.plugin",
        "-p",
        "pytest_collect_profile.plugin",
        *args,
    )


def _make_execution_suite(pytester):
    execution_marker = pytester.path / "test-executed"
    pytester.makepyfile(
        test_sample=f"""
        from pathlib import Path

        def test_must_not_run():
            Path({str(execution_marker)!r}).write_text("executed", encoding="utf-8")
        """
    )
    return execution_marker


@pytest.mark.parametrize("xdist_args", [[], ["-n", "0"]])
def test_profile_only_uses_serial_path_when_xdist_is_inactive(
    pytester, monkeypatch, xdist_args
) -> None:
    execution_marker = _make_execution_suite(pytester)

    result = _run_with_xdist(
        pytester,
        monkeypatch,
        "--collect-profile-only",
        "-q",
        *xdist_args,
    )

    assert result.ret == 0
    output = result.stdout.str()
    assert output.count("collect profile") == 1
    assert "| 1 items" in output
    assert "test_must_not_run" not in output
    assert not execution_marker.exists()


@pytest.mark.parametrize(
    "extra_args",
    [
        [],
        ["--collect-only"],
        ["--co"],
        ["--collect-profile"],
    ],
)
def test_profile_only_rejects_active_xdist_before_collection(
    pytester, monkeypatch, extra_args
) -> None:
    collection_marker = pytester.path / "collection-started"
    pytester.makeconftest(
        f"""
        from pathlib import Path

        def pytest_collection():
            Path({str(collection_marker)!r}).write_text("started", encoding="utf-8")
        """
    )
    execution_marker = _make_execution_suite(pytester)

    result = _run_with_xdist(
        pytester,
        monkeypatch,
        "--collect-profile-only",
        "-n",
        "2",
        *extra_args,
    )

    assert result.ret == 4
    combined_output = result.stdout.str() + result.stderr.str()
    assert (
        "--collect-profile-only does not support active pytest-xdist distribution; "
        "use -n0"
    ) in combined_output
    assert "Total collection:" not in combined_output
    assert not collection_marker.exists()
    assert not execution_marker.exists()
