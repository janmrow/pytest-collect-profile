from __future__ import annotations

import re

from pytest_collect_profile import plugin
from pytest_collect_profile.plugin import (
    _CollectorTiming,
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


def test_option_is_registered_once(pytester, monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

    result = pytester.runpytest_inprocess("--help", plugins=[plugin])

    result.stdout.fnmatch_lines(["*--collect-profile*slowest collectors*"])
    assert result.stdout.str().count("--collect-profile") == 1


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
    assert re.search(r"Total collection: \d+\.\d{3}s \| 1 items", output)
    assert output.index("collect profile") < output.index("TEST EXECUTED")


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
