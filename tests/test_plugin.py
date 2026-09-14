from __future__ import annotations

import re

import pytest

from pytest_collect_profile import plugin
from pytest_collect_profile.plugin import (
    _CollectorTiming,
    _CollectProfilePlugin,
    _format_duration,
    _report_lines,
)


def _timing(duration_ns: int, collector_type: str, nodeid: str) -> _CollectorTiming:
    return _CollectorTiming(duration_ns, collector_type, nodeid)


def test_duration_uses_fixed_seconds_with_three_decimal_places() -> None:
    assert _format_duration(1_421_400_000) == "1.421s"
    assert _format_duration(400_000) == "0.000s"


def test_report_formats_rows_session_label_and_summary() -> None:
    lines = _report_lines(
        [
            _timing(1_421_000_000, "Module", "tests/test_api.py"),
            _timing(612_000_000, "Session", ""),
        ],
        total_duration_ns=2_340_000_000,
        item_count=842,
    )

    assert lines == [
        "time      collector   node",
        "1.421s    Module      tests/test_api.py",
        "0.612s    Session     <session>",
        "",
        "Total collection: 2.340s | 842 items",
    ]


def test_report_separates_long_collector_type_from_nodeid() -> None:
    lines = _report_lines(
        [_timing(1_000_000_000, "VeryLongCollector", "tests/test_api.py")],
        total_duration_ns=1_000_000_000,
        item_count=1,
    )

    assert lines[1] == "1.000s    VeryLongCollector tests/test_api.py"


def test_report_sorts_raw_timings_before_display_rounding() -> None:
    lines = _report_lines(
        [
            _timing(1_000_400_000, "Module", "tests/a.py"),
            _timing(1_000_499_999, "Module", "tests/z.py"),
        ],
        total_duration_ns=2_000_000_000,
        item_count=2,
    )

    assert lines[1:3] == [
        "1.000s    Module      tests/z.py",
        "1.000s    Module      tests/a.py",
    ]


def test_report_breaks_exact_ties_by_nodeid_then_collector_type() -> None:
    lines = _report_lines(
        [
            _timing(1_000_000_000, "Package", "tests/z.py"),
            _timing(1_000_000_000, "Module", "tests/a.py"),
            _timing(1_000_000_000, "Class", "tests/a.py"),
        ],
        total_duration_ns=3_000_000_000,
        item_count=3,
    )

    assert lines[1:4] == [
        "1.000s    Class       tests/a.py",
        "1.000s    Module      tests/a.py",
        "1.000s    Package     tests/z.py",
    ]


def test_report_limits_rows_to_ten_without_ellipsis() -> None:
    timings = [
        _timing(index, "Module", f"tests/test_{index}.py") for index in range(12)
    ]

    lines = _report_lines(timings, total_duration_ns=100, item_count=12)

    assert len(lines) == 13
    assert "..." not in "\n".join(lines)
    assert "tests/test_11.py" in lines[1]
    assert "tests/test_2.py" in lines[10]


def test_report_keeps_every_row_when_fewer_than_ten_exist() -> None:
    timings = [_timing(index, "Module", f"tests/test_{index}.py") for index in range(3)]

    lines = _report_lines(timings, total_duration_ns=100, item_count=3)

    assert len(lines) == 6


def test_nested_measurement_hooks_keep_inclusive_timings(pytester) -> None:
    class ParentCollector:
        nodeid = "parent"

    class ChildCollector:
        nodeid = "parent::child"

    clock_values = iter([0, 10, 30, 50])
    runtime = _CollectProfilePlugin(
        config=pytester.parseconfig(),
        clock=lambda: next(clock_values),
    )

    parent_hook = runtime.pytest_make_collect_report(ParentCollector())
    assert next(parent_hook) is None
    child_hook = runtime.pytest_make_collect_report(ChildCollector())
    assert next(child_hook) is None

    child_result = object()
    with pytest.raises(StopIteration) as child_finished:
        child_hook.send(child_result)
    assert child_finished.value.value is child_result

    parent_result = object()
    with pytest.raises(StopIteration) as parent_finished:
        parent_hook.send(parent_result)
    assert parent_finished.value.value is parent_result

    child_timing, parent_timing = runtime._collector_timings
    assert (
        child_timing.duration_ns,
        child_timing.collector_type,
        child_timing.nodeid,
    ) == (
        20,
        "ChildCollector",
        "parent::child",
    )
    assert (
        parent_timing.duration_ns,
        parent_timing.collector_type,
        parent_timing.nodeid,
    ) == (50, "ParentCollector", "parent")
    assert parent_timing.nested_collectors_ns == 20


def test_option_is_registered_once(pytester, monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

    result = pytester.runpytest_inprocess("--help", plugins=[plugin])

    output = result.stdout.str()
    assert "show the slowest collectors after collection" in output
    assert "profile collection without running tests or listing" in output
    assert "collected nodes" in output
    assert len(re.findall(r"(?m)^  --collect-profile(?:\s|$)", output)) == 1
    assert len(re.findall(r"(?m)^  --collect-profile-only(?:\s|$)", output)) == 1


def test_disabled_plugin_is_silent_and_does_not_prevent_execution(
    pytester, monkeypatch
) -> None:
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    pytester.makepyfile(
        """
        def test_runs():
            print("TEST EXECUTED")
        """
    )

    result = pytester.runpytest_inprocess("-q", "-s", plugins=[plugin])

    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["*TEST EXECUTED*"])
    assert "collect profile" not in result.stdout.str()


def test_enabled_plugin_ranks_a_slow_collector_and_reports_before_execution(
    pytester, monkeypatch
) -> None:
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    pytester.makeconftest(
        """
        import time
        import pytest

        class SlowFile(pytest.File):
            def collect(self):
                time.sleep(0.03)
                return []

        def pytest_collect_file(file_path, parent):
            if file_path.name == "slow.case":
                return SlowFile.from_parent(parent, path=file_path)
        """
    )
    pytester.makefile(".case", slow="content")
    pytester.makepyfile(
        """
        def test_runs():
            print("TEST EXECUTED")
        """
    )

    result = pytester.runpytest_inprocess(
        "--collect-profile", "-q", "-s", plugins=[plugin]
    )

    result.assert_outcomes(passed=1)
    output = result.stdout.str()
    assert re.search(
        r"(?m)^time\s+collector\s+node\n"
        r"\d+\.\d{3}s\s+SlowFile\s+slow\.case$",
        output,
    )
    assert re.search(r"(?m)^\d+\.\d{3}s\s+Module\s+\S+\.py$", output)
    assert re.search(r"Total collection: \d+\.\d{3}s \| 1 items", output)
    assert output.index("collect profile") < output.index("TEST EXECUTED")


def test_terminal_report_treats_unexpected_nodeid_text_as_data(
    pytester, monkeypatch
) -> None:
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    unexpected_nodeid = "$(touch terminal-side-effect).case"
    side_effect = pytester.path / "terminal-side-effect"
    (pytester.path / unexpected_nodeid).write_text("content\n", encoding="utf-8")
    pytester.makeconftest(
        f"""
        import pytest

        class UnexpectedFile(pytest.File):
            def collect(self):
                return []

        def pytest_collect_file(file_path, parent):
            if file_path.name == {unexpected_nodeid!r}:
                return UnexpectedFile.from_parent(parent, path=file_path)
        """
    )
    pytester.makepyfile("def test_passes(): pass")

    result = pytester.runpytest_inprocess("--collect-profile", "-q", plugins=[plugin])

    result.assert_outcomes(passed=1)
    assert re.search(
        rf"(?m)^\d+\.\d{{3}}s\s+UnexpectedFile\s+{re.escape(unexpected_nodeid)}$",
        result.stdout.str(),
    )
    assert not side_effect.exists()


def test_total_includes_collection_work_outside_collector_reports(
    pytester, monkeypatch
) -> None:
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    pytester.makeconftest(
        """
        import time

        def pytest_collection_modifyitems(items):
            time.sleep(0.03)
        """
    )
    pytester.makepyfile("def test_passes(): pass")

    result = pytester.runpytest_inprocess(
        "--collect-profile", "--collect-only", "-q", plugins=[plugin]
    )

    assert result.ret == 0
    result.stdout.fnmatch_lines(["*1 test collected*"])
    output = result.stdout.str()
    row_durations = [
        float(value)
        for value in re.findall(
            r"(?m)^(\d+\.\d{3})s\s+\w+\s+(?:\S.*|<session>)$", output
        )
    ]
    total_match = re.search(r"Total collection: (\d+\.\d{3})s", output)
    assert row_durations
    assert total_match is not None
    assert float(total_match.group(1)) >= max(row_durations) + 0.02


def test_collect_only_reports_without_executing_tests(pytester, monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    execution_marker = pytester.path / "test-executed"
    pytester.makepyfile(
        f"""
        from pathlib import Path

        def test_does_not_run():
            Path({str(execution_marker)!r}).write_text("executed", encoding="utf-8")
        """
    )

    result = pytester.runpytest_inprocess(
        "--collect-profile", "--collect-only", "-q", plugins=[plugin]
    )

    assert result.ret == 0
    result.stdout.fnmatch_lines(["*1 test collected*"])
    output = result.stdout.str()
    assert "test_does_not_run" in output
    assert "Total collection:" in output
    assert not execution_marker.exists()


def test_profile_preserves_selection_and_collected_item_count(
    pytester, monkeypatch
) -> None:
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    pytester.makepyfile(
        """
        def test_selected():
            print("SELECTED EXECUTED")

        def test_not_selected():
            print("UNSELECTED EXECUTED")
        """
    )

    profiled = pytester.runpytest_inprocess(
        "--collect-profile", "-q", "-s", "-k", "test_selected", plugins=[plugin]
    )
    unprofiled = pytester.runpytest_inprocess(
        "-q", "-s", "-k", "test_selected", plugins=[plugin]
    )

    assert profiled.ret == unprofiled.ret == 0
    assert (
        profiled.parseoutcomes()
        == unprofiled.parseoutcomes()
        == {
            "passed": 1,
            "deselected": 1,
        }
    )
    assert "Total collection:" in profiled.stdout.str()
    assert "| 1 items" in profiled.stdout.str()
    assert "collect profile" not in unprofiled.stdout.str()
    for result in (profiled, unprofiled):
        assert "SELECTED EXECUTED" in result.stdout.str()
        assert "UNSELECTED EXECUTED" not in result.stdout.str()


def test_profiled_empty_suite_preserves_native_no_tests_outcome(
    pytester, monkeypatch
) -> None:
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

    profiled = pytester.runpytest_inprocess("--collect-profile", "-q", plugins=[plugin])
    unprofiled = pytester.runpytest_inprocess("-q", plugins=[plugin])

    assert profiled.ret == unprofiled.ret == 5
    assert "Total collection:" in profiled.stdout.str()
    assert "| 0 items" in profiled.stdout.str()
    assert "collect profile" not in unprofiled.stdout.str()


def test_collection_error_keeps_native_failure_and_exit_status(
    pytester, monkeypatch
) -> None:
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    pytester.makepyfile("import module_that_does_not_exist")

    profiled = pytester.runpytest_inprocess("--collect-profile", "-q", plugins=[plugin])
    unprofiled = pytester.runpytest_inprocess("-q", plugins=[plugin])

    assert profiled.ret == unprofiled.ret == 2
    for result in (profiled, unprofiled):
        result.stdout.fnmatch_lines(["*ERROR collecting*"])
        assert "ModuleNotFoundError" in result.stdout.str()
        assert "1 error" in result.stdout.str()
        assert "passed" not in result.stdout.str()
    assert "Total collection:" in profiled.stdout.str()
    assert "| 0 items" in profiled.stdout.str()
    assert "collect profile" not in unprofiled.stdout.str()


def test_failing_test_keeps_native_outcome_after_profile_report(
    pytester, monkeypatch
) -> None:
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    pytester.makepyfile(
        """
        def test_fails():
            assert False, "native failure"
        """
    )

    profiled = pytester.runpytest_inprocess("--collect-profile", "-q", plugins=[plugin])
    unprofiled = pytester.runpytest_inprocess("-q", plugins=[plugin])

    assert profiled.ret == unprofiled.ret == 1
    assert profiled.parseoutcomes() == unprofiled.parseoutcomes() == {"failed": 1}
    for result in (profiled, unprofiled):
        assert "native failure" in result.stdout.str()
    output = profiled.stdout.str()
    assert "Total collection:" in output
    assert output.index("collect profile") < output.index("FAILURES")
    assert "collect profile" not in unprofiled.stdout.str()
