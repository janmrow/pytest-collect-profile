from __future__ import annotations

import re

import pytest

from pytest_collect_profile import plugin


def _make_protocol_suite(pytester):
    protocol_marker = pytester.path / "test-protocol"
    pytester.makepyfile(
        test_sample=f"""
        from pathlib import Path

        import pytest

        MARKER = Path({str(protocol_marker)!r})

        @pytest.fixture(autouse=True)
        def record_protocol():
            MARKER.write_text("setup", encoding="utf-8")
            yield
            MARKER.write_text("teardown", encoding="utf-8")

        def test_visible_item():
            MARKER.write_text("call", encoding="utf-8")
        """
    )
    return protocol_marker


def _run(pytester, monkeypatch, *args):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    return pytester.runpytest_inprocess(*args, plugins=[plugin])


def _assert_one_profile(output: str) -> None:
    assert output.count("collect profile") == 1
    assert output.count("Total collection:") == 1


def test_profile_only_reports_without_listing_or_running_tests(
    pytester, monkeypatch
) -> None:
    protocol_marker = _make_protocol_suite(pytester)

    result = _run(pytester, monkeypatch, "--collect-profile-only")

    assert result.ret == 0
    output = result.stdout.str()
    _assert_one_profile(output)
    assert "| 1 items" in output
    assert "1 test collected" in output
    assert "test_visible_item" not in output
    assert not protocol_marker.exists()


def test_profile_only_output_is_bounded_for_many_items(pytester, monkeypatch) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.parametrize("case", range(200))
        def test_many_items(case):
            pass
        """
    )

    result = _run(pytester, monkeypatch, "--collect-profile-only", "-q")

    assert result.ret == 0
    output = result.stdout.str()
    _assert_one_profile(output)
    assert "| 200 items" in output
    assert "200 tests collected" in output
    assert "test_many_items[" not in output
    rows = re.findall(r"(?m)^\d+\.\d{3}s\s+\w+\s+(?:\S.*|<session>)$", output)
    assert 1 <= len(rows) <= 10


@pytest.mark.parametrize("native_collect_only", ["--collect-only", "--co"])
def test_explicit_collect_only_keeps_native_listing_with_profile_only(
    pytester, monkeypatch, native_collect_only
) -> None:
    protocol_marker = _make_protocol_suite(pytester)

    result = _run(
        pytester,
        monkeypatch,
        "--collect-profile-only",
        native_collect_only,
        "-q",
    )

    assert result.ret == 0
    output = result.stdout.str()
    _assert_one_profile(output)
    assert "test_sample.py::test_visible_item" in output
    assert not protocol_marker.exists()


def test_both_profile_options_use_one_profile_only_runtime(
    pytester, monkeypatch
) -> None:
    protocol_marker = _make_protocol_suite(pytester)

    result = _run(
        pytester,
        monkeypatch,
        "--collect-profile",
        "--collect-profile-only",
    )

    assert result.ret == 0
    output = result.stdout.str()
    _assert_one_profile(output)
    assert "test_visible_item" not in output
    assert not protocol_marker.exists()


@pytest.mark.parametrize(
    ("selection", "expected_items"),
    [
        (["test_selection.py"], 2),
        (["test_selection.py::test_first"], 1),
        (["test_selection.py", "-k", "first"], 1),
        (["test_selection.py", "-m", "fast"], 1),
    ],
)
def test_profile_only_preserves_pytest_selection(
    pytester, monkeypatch, selection, expected_items
) -> None:
    pytester.makeini("[pytest]\nmarkers = fast: selected test\n")
    pytester.makepyfile(
        test_selection="""
        import pytest

        @pytest.mark.fast
        def test_first():
            pass

        def test_second():
            pass
        """
    )

    result = _run(
        pytester,
        monkeypatch,
        "--collect-profile-only",
        "-q",
        *selection,
    )

    assert result.ret == 0
    output = result.stdout.str()
    _assert_one_profile(output)
    assert f"| {expected_items} items" in output
    assert "test_first" not in output
    assert "test_second" not in output


@pytest.mark.parametrize("verbosity", [["-q"], ["-qq"], ["-v"]])
def test_profile_only_stays_compact_at_supported_verbosity(
    pytester, monkeypatch, verbosity
) -> None:
    protocol_marker = _make_protocol_suite(pytester)

    result = _run(
        pytester,
        monkeypatch,
        "--collect-profile-only",
        *verbosity,
    )

    assert result.ret == 0
    output = result.stdout.str()
    _assert_one_profile(output)
    assert "test_visible_item" not in output
    assert not protocol_marker.exists()


def test_profile_only_keeps_collection_warning_visible(pytester, monkeypatch) -> None:
    pytester.makepyfile(
        """
        import warnings

        warnings.warn("VISIBLE COLLECTION WARNING", UserWarning)

        def test_collected():
            pass
        """
    )

    result = _run(pytester, monkeypatch, "--collect-profile-only", "-q")

    assert result.ret == 0
    output = result.stdout.str()
    _assert_one_profile(output)
    assert "VISIBLE COLLECTION WARNING" in output


def test_profile_only_collection_error_matches_native_collect_only(
    pytester, monkeypatch
) -> None:
    pytester.makepyfile("import missing_collection_dependency")

    profiled = _run(pytester, monkeypatch, "--collect-profile-only", "-q")
    native = _run(pytester, monkeypatch, "--collect-only", "-q")

    assert profiled.ret == native.ret == 2
    assert "ModuleNotFoundError" in profiled.stdout.str()
    _assert_one_profile(profiled.stdout.str())


def test_profile_only_continued_collection_error_never_runs_valid_test(
    pytester, monkeypatch
) -> None:
    execution_marker = pytester.path / "test-executed"
    pytester.makepyfile(test_broken="import missing_collection_dependency")
    pytester.makepyfile(
        test_valid=f"""
        from pathlib import Path

        def test_must_not_run():
            Path({str(execution_marker)!r}).write_text("executed", encoding="utf-8")
        """
    )

    result = _run(
        pytester,
        monkeypatch,
        "--collect-profile-only",
        "--continue-on-collection-errors",
        "-q",
    )

    assert result.ret == 1
    output = result.stdout.str()
    _assert_one_profile(output)
    assert "ModuleNotFoundError" in output
    assert not execution_marker.exists()


def test_interrupted_collection_does_not_render_complete_profile(
    pytester, monkeypatch
) -> None:
    pytester.makepyfile('raise KeyboardInterrupt("collection stopped")')
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

    result = pytester.runpytest_subprocess(
        "-p",
        "pytest_collect_profile.plugin",
        "--collect-profile-only",
        "-q",
    )

    assert result.ret == 2
    assert "KeyboardInterrupt" in result.stdout.str()
    assert "Total collection:" not in result.stdout.str()


def test_profile_only_empty_suite_keeps_native_no_tests_status(
    pytester, monkeypatch
) -> None:
    result = _run(pytester, monkeypatch, "--collect-profile-only", "-q")

    assert result.ret == 5
    output = result.stdout.str()
    _assert_one_profile(output)
    assert "| 0 items" in output


def test_profile_only_fully_deselected_suite_keeps_native_status(
    pytester, monkeypatch
) -> None:
    protocol_marker = _make_protocol_suite(pytester)

    result = _run(
        pytester,
        monkeypatch,
        "--collect-profile-only",
        "-q",
        "-k",
        "not_present",
    )

    assert result.ret == 5
    output = result.stdout.str()
    _assert_one_profile(output)
    assert "| 0 items" in output
    assert not protocol_marker.exists()


def test_usage_error_before_collection_has_no_profile(pytester, monkeypatch) -> None:
    result = _run(
        pytester,
        monkeypatch,
        "--collect-profile-only",
        "--not-a-real-option",
    )

    assert result.ret == 4
    assert "unrecognized arguments: --not-a-real-option" in result.stderr.str()
    assert "Total collection:" not in result.stdout.str()


def test_profile_only_keeps_custom_collector_and_hides_long_item_nodeid(
    pytester, monkeypatch
) -> None:
    pytester.makeconftest(
        """
        import pytest

        class ProfiledFile(pytest.File):
            def collect(self):
                return []

        def pytest_collect_file(file_path, parent):
            if file_path.name == "custom.case":
                return ProfiledFile.from_parent(parent, path=file_path)
        """
    )
    pytester.makefile(".case", custom="content")
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.parametrize("value", [1], ids=["very-long-parameter-id"])
        def test_parameterized_item(value):
            pass
        """
    )

    result = _run(pytester, monkeypatch, "--collect-profile-only", "-q")

    assert result.ret == 0
    output = result.stdout.str()
    _assert_one_profile(output)
    assert re.search(r"(?m)^\d+\.\d{3}s\s+ProfiledFile\s+custom\.case$", output)
    assert "test_parameterized_item[very-long-parameter-id]" not in output
