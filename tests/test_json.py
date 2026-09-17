from __future__ import annotations

import json

import pytest

from pytest_collect_profile import plugin
from pytest_collect_profile.plugin import (
    _build_profile_snapshot,
    _CollectorTiming,
    _CollectProfilePlugin,
    _HookTiming,
    _json_report,
    _text_report_lines,
)


def _hook(duration_ns: int, call_count: int, name: str) -> _HookTiming:
    return _HookTiming(duration_ns, call_count, name)


def _profile_from_output(output: str) -> dict[str, object]:
    matches = [
        json.loads(line)
        for line in output.splitlines()
        if line.startswith('{"schema":"pytest-collect-profile"')
    ]
    assert len(matches) == 1
    return matches[0]


def _run(pytester, monkeypatch, *args):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    return pytester.runpytest_inprocess(*args, plugins=[plugin])


def _snapshot():
    timings = [
        _CollectorTiming(
            duration_ns=2_000 - index,
            collector_type="Session" if index == 0 else "Module",
            nodeid="" if index == 0 else f"tests/test_{index}.py",
            direct_children=None if index == 0 else index,
            direct_items=None if index == 0 else index - 1,
            nested_collectors_ns=100 if index == 0 else 0,
            hook_timings=(
                _hook(400, 1, "z_hook"),
                _hook(400, 2, "a_hook"),
                _hook(300, 3, 'quoted_"_hook'),
                _hook(200, 4, "backslash_\\_hook"),
                _hook(100, 5, "unicode_żółw\n\t\x1b[31m_$(touch nope)"),
            ),
        )
        for index in range(12)
    ]
    return _build_profile_snapshot(
        timings,
        total_duration_ns=9_876,
        item_count=42,
        collection_hook_timings=(
            _hook(40, 1, "z_collection"),
            _hook(40, 2, "a_collection"),
            _hook(30, 3, "third_collection"),
            _hook(20, 4, "folded_collection"),
        ),
    )


def test_json_v1_has_exact_order_types_bounds_and_folding() -> None:
    report = json.loads(_json_report(_snapshot()))

    assert list(report) == [
        "schema",
        "schema_version",
        "profile_complete",
        "collectors",
        "collection_hooks",
        "total_collection_ns",
        "item_count",
    ]
    assert report["schema"] == "pytest-collect-profile"
    assert report["schema_version"] == 1
    assert report["profile_complete"] is True
    assert type(report["total_collection_ns"]) is int
    assert type(report["item_count"]) is int

    collectors = report["collectors"]
    assert len(collectors) == 10
    assert [collector["rank"] for collector in collectors] == list(range(1, 11))
    assert list(collectors[0]) == [
        "rank",
        "duration_ns",
        "collector_type",
        "nodeid",
        "attribution",
    ]
    assert [collector["attribution"] is not None for collector in collectors] == [
        True,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    ]

    attribution = collectors[0]["attribution"]
    assert list(attribution) == [
        "direct_children",
        "direct_items",
        "hooks",
        "nested_collectors_ns",
        "outside_observed_hooks_ns",
    ]
    assert attribution["direct_children"] is None
    assert attribution["direct_items"] is None
    assert [hook["name"] for hook in attribution["hooks"]] == [
        "a_hook",
        "z_hook",
        'quoted_"_hook',
        "other observed hooks",
    ]
    assert attribution["hooks"][-1] == {
        "name": "other observed hooks",
        "duration_ns": 300,
        "call_count": 9,
    }
    assert list(attribution["hooks"][0]) == ["name", "duration_ns", "call_count"]
    assert report["collection_hooks"][-1] == {
        "name": "other observed hooks",
        "duration_ns": 20,
        "call_count": 4,
    }


def test_json_is_one_compact_unstyled_unicode_safe_line() -> None:
    hostile = (
        'żółw_ÿ_: value_"_\\_\n_\t_\x1b[31m_\u0085_\u2028_\u2029_'
        "astral_\U0001f40d_$(touch nope)"
    )
    snapshot = _build_profile_snapshot(
        [
            _CollectorTiming(
                10,
                hostile,
                hostile,
                hook_timings=(_hook(1, 1, hostile),),
            )
        ],
        total_duration_ns=12,
        item_count=0,
    )
    line = _json_report(snapshot)

    assert len(line.splitlines()) == 1
    assert "\n" not in line
    assert "\x1b" not in line
    assert "\u0085" not in line
    assert "\u2028" not in line
    assert "\u2029" not in line
    assert "ó" not in line
    assert "ÿ" not in line
    assert "\U0001f40d" not in line
    assert "ż" not in line
    assert line.isascii()
    report = json.loads(line)
    assert report["collectors"][0]["collector_type"] == hostile
    assert report["collectors"][0]["nodeid"] == hostile
    assert report["collectors"][0]["attribution"]["hooks"][0]["name"] == hostile
    assert "\\n" in line
    assert "\\t" in line
    assert "\\u001b[31m" in line
    assert "\\u0085" in line
    assert "\\u00f3" in line
    assert "\\u00ff" in line
    assert "\\u017c" in line
    assert "\\u2028" in line
    assert "\\u2029" in line
    assert "\\ud83d\\udc0d" in line
    assert ": value" in line
    assert "$(touch nope)" in line
    assert line.startswith(
        '{"schema":"pytest-collect-profile","schema_version":1,'
        '"profile_complete":true,"collectors":[{'
    )


def test_empty_hooks_and_raw_session_nodeid_are_explicit() -> None:
    snapshot = _build_profile_snapshot(
        [_CollectorTiming(10, "Session", "")],
        total_duration_ns=12,
        item_count=0,
    )

    report = json.loads(_json_report(snapshot))
    assert report["collectors"][0]["nodeid"] == ""
    assert report["collectors"][0]["attribution"]["hooks"] == []
    assert report["collection_hooks"] == []
    assert any("Session <session>" in line for line in _text_report_lines(snapshot))


def test_text_and_json_consume_the_same_bounded_snapshot() -> None:
    snapshot = _snapshot()
    lines = _text_report_lines(snapshot)
    report = json.loads(_json_report(snapshot))

    assert report["collectors"][0]["collector_type"] == "Session"
    assert report["collectors"][0]["nodeid"] == ""
    assert lines[1] == "0.000s    Session     <session>"
    assert [
        hook["name"] for hook in report["collectors"][0]["attribution"]["hooks"]
    ] == [
        "a_hook",
        "z_hook",
        'quoted_"_hook',
        "other observed hooks",
    ]
    assert "   0.000s | 9 calls | other observed hooks" in lines
    assert report["collectors"][0]["attribution"]["nested_collectors_ns"] == 100
    assert "   0.000s | nested collectors" in lines
    assert report["total_collection_ns"] == 9_876
    assert report["item_count"] == 42
    assert lines[-1] == "Total collection: 0.000s | 42 items"


def test_json_option_is_registered_once(pytester, monkeypatch) -> None:
    result = _run(pytester, monkeypatch, "--help")

    output = result.stdout.str()
    assert output.count("--collect-profile-json") == 1
    assert "emit the collection profile as one compact JSON object" in output


def test_normal_json_precedes_test_execution_and_replaces_text(
    pytester, monkeypatch
) -> None:
    pytester.makepyfile(
        """
        def test_runs():
            print("TEST EXECUTED")
        """
    )

    result = _run(
        pytester,
        monkeypatch,
        "--collect-profile",
        "--collect-profile-json",
        "-q",
        "-s",
    )

    result.assert_outcomes(passed=1)
    output = result.stdout.str()
    report = _profile_from_output(output)
    assert report["item_count"] == 1
    assert output.index('{"schema"') < output.index("TEST EXECUTED")
    assert "collector attribution" not in output
    assert "Total collection:" not in output


@pytest.mark.parametrize(
    "mode_args",
    [
        ["--collect-profile-only"],
        ["--collect-profile", "--collect-profile-only"],
    ],
)
def test_profile_only_json_emits_once_without_test_protocol(
    pytester, monkeypatch, mode_args
) -> None:
    marker = pytester.path / "protocol-ran"
    pytester.makepyfile(
        f"""
        from pathlib import Path

        def test_must_not_run():
            Path({str(marker)!r}).write_text("ran", encoding="utf-8")
        """
    )

    result = _run(
        pytester,
        monkeypatch,
        *mode_args,
        "--collect-profile-json",
        "-q",
    )

    assert result.ret == 0
    report = _profile_from_output(result.stdout.str())
    assert report["item_count"] == 1
    assert "test_must_not_run" not in result.stdout.str()
    assert not marker.exists()


def test_json_modifier_alone_is_usage_error_before_collection(
    pytester, monkeypatch
) -> None:
    collection_marker = pytester.path / "collection-started"
    execution_marker = pytester.path / "test-executed"
    pytester.makeconftest(
        f"""
        from pathlib import Path

        def pytest_collection():
            Path({str(collection_marker)!r}).write_text("started", encoding="utf-8")
        """
    )
    pytester.makepyfile(
        f"""
        from pathlib import Path

        def test_must_not_run():
            Path({str(execution_marker)!r}).write_text("ran", encoding="utf-8")
        """
    )

    result = _run(pytester, monkeypatch, "--collect-profile-json")

    assert result.ret == 4
    combined = result.stdout.str() + result.stderr.str()
    assert (
        "--collect-profile-json requires --collect-profile or --collect-profile-only"
        in combined
    )
    assert '{"schema":"pytest-collect-profile"' not in combined
    assert not collection_marker.exists()
    assert not execution_marker.exists()


@pytest.mark.parametrize("collect_only", ["--collect-only", "--co"])
def test_explicit_collect_only_keeps_native_listing_with_json(
    pytester, monkeypatch, collect_only
) -> None:
    pytester.makepyfile("def test_visible_item(): pass")

    result = _run(
        pytester,
        monkeypatch,
        "--collect-profile-only",
        "--collect-profile-json",
        collect_only,
        "-q",
    )

    assert result.ret == 0
    _profile_from_output(result.stdout.str())
    assert "test_visible_item" in result.stdout.str()


def test_completed_collection_error_emits_json_and_preserves_status(
    pytester, monkeypatch
) -> None:
    pytester.makepyfile("import missing_json_profile_dependency")

    result = _run(
        pytester,
        monkeypatch,
        "--collect-profile-only",
        "--collect-profile-json",
        "-q",
    )

    assert result.ret == 2
    assert "ModuleNotFoundError" in result.stdout.str()
    report = _profile_from_output(result.stdout.str())
    assert report["profile_complete"] is True
    assert report["item_count"] == 0


def test_interrupted_collection_does_not_emit_json(pytester, monkeypatch) -> None:
    pytester.makepyfile('raise KeyboardInterrupt("collection stopped")')
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

    result = pytester.runpytest_subprocess(
        "-p",
        "pytest_collect_profile.plugin",
        "--collect-profile-only",
        "--collect-profile-json",
        "-q",
    )

    assert result.ret == 2
    assert "KeyboardInterrupt" in result.stdout.str()
    assert '"schema":"pytest-collect-profile"' not in result.stdout.str()


@pytest.mark.parametrize("selection", [[], ["-k", "not_present"]])
def test_empty_or_deselected_suite_reports_zero_items(
    pytester, monkeypatch, selection
) -> None:
    if selection:
        pytester.makepyfile("def test_exists(): pass")

    result = _run(
        pytester,
        monkeypatch,
        "--collect-profile-only",
        "--collect-profile-json",
        "-q",
        *selection,
    )

    assert result.ret == 5
    assert _profile_from_output(result.stdout.str())["item_count"] == 0


def test_hostile_nodeid_is_only_json_data(pytester, monkeypatch) -> None:
    nodeid = (
        'żółw_: value_"_\\_\n_\t_\x1b[31m_\u0085_\u2028_\u2029_'
        "$(touch json-side-effect).case"
    )
    side_effect = pytester.path / "json-side-effect"
    (pytester.path / "hostile.case").write_text("content\n", encoding="utf-8")
    pytester.makeconftest(
        f"""
        import pytest

        class HostileFile(pytest.File):
            def collect(self):
                return []

        def pytest_collect_file(file_path, parent):
            if file_path.name == "hostile.case":
                return HostileFile.from_parent(
                    parent, path=file_path, nodeid={nodeid!r}
                )
        """
    )

    result = _run(
        pytester,
        monkeypatch,
        "--collect-profile-only",
        "--collect-profile-json",
        "-q",
    )

    assert result.ret == 5
    report = _profile_from_output(result.stdout.str())
    assert any(collector["nodeid"] == nodeid for collector in report["collectors"])
    assert not side_effect.exists()


def test_json_remains_valid_with_ascii_terminal_encoding(pytester, monkeypatch) -> None:
    nodeid = "latin_é_bmp_ż_astral_\U0001f40d.case"
    (pytester.path / "hostile.case").write_text("content\n", encoding="utf-8")
    pytester.makeconftest(
        f"""
        import pytest

        class HostileFile(pytest.File):
            def collect(self):
                return []

        def pytest_collect_file(file_path, parent):
            if file_path.name == "hostile.case":
                return HostileFile.from_parent(
                    parent, path=file_path, nodeid={nodeid!r}
                )
        """
    )
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("PYTHONIOENCODING", "ascii")

    result = pytester.runpytest_subprocess(
        "-p",
        "pytest_collect_profile.plugin",
        "--collect-profile-only",
        "--collect-profile-json",
        "-q",
    )

    assert result.ret == 5
    json_lines = [
        line
        for line in result.stdout.str().splitlines()
        if line.startswith('{"schema":"pytest-collect-profile"')
    ]
    assert len(json_lines) == 1
    assert "\\x" not in json_lines[0]
    assert "\\U" not in json_lines[0]
    assert "\\u00e9" in json_lines[0]
    assert "\\ud83d\\udc0d" in json_lines[0]
    report = json.loads(json_lines[0])
    assert any(collector["nodeid"] == nodeid for collector in report["collectors"])


def test_missing_terminal_reporter_does_not_build_or_redirect_report(
    pytester, monkeypatch
) -> None:
    config = pytester.parseconfig()
    runtime = _CollectProfilePlugin(config, json_output=True)
    monkeypatch.setattr(config.pluginmanager, "get_plugin", lambda name: None)
    monkeypatch.setattr(
        plugin,
        "_build_profile_snapshot",
        lambda *args, **kwargs: pytest.fail("snapshot should not be built"),
    )

    runtime._write_report(total_duration_ns=1, item_count=0)
