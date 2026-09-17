from __future__ import annotations

import re
from dataclasses import dataclass

import pytest

from pytest_collect_profile import plugin
from pytest_collect_profile.plugin import _CollectProfilePlugin


class _Clock:
    def __init__(self) -> None:
        self.now = 0

    def __call__(self) -> int:
        return self.now

    def advance(self, nanoseconds: int) -> None:
        self.now += nanoseconds


@dataclass
class _Collector:
    nodeid: str


@dataclass
class _Report:
    result: object


def _runtime(pytester, clock: _Clock) -> _CollectProfilePlugin:
    return _CollectProfilePlugin(pytester.parseconfig(), clock=clock)


def _enter(generator) -> None:
    assert next(generator) is None


def _finish(generator, result: object) -> object:
    with pytest.raises(StopIteration) as finished:
        generator.send(result)
    return finished.value.value


def _before(runtime: _CollectProfilePlugin, name: str) -> None:
    runtime._before_hook_call(name, (), {})


def _after(runtime: _CollectProfilePlugin, name: str) -> None:
    runtime._after_hook_call(None, name, (), {})


def _run(pytester, monkeypatch, *args):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    return pytester.runpytest_inprocess(*args, plugins=[plugin])


def _collector_block(output: str, collector_type: str, nodeid: str) -> str:
    lines = output.splitlines()
    heading = re.compile(rf"^\d+\. {re.escape(collector_type)} {re.escape(nodeid)}$")
    start = next(index for index, line in enumerate(lines) if heading.match(line))
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if re.match(r"^\d+\. ", line) or line in {
            "collection-level hooks",
            "Total collection:",
        }:
            break
        if not line:
            break
        end += 1
    return "\n".join(lines[start:end])


def test_records_repeated_hook_calls_with_exclusive_time(pytester) -> None:
    clock = _Clock()
    runtime = _runtime(pytester, clock)
    collector = _Collector("tests/test_api.py")
    operation = runtime.pytest_make_collect_report(collector)
    _enter(operation)

    _before(runtime, "pytest_generate_tests")
    clock.advance(11)
    _after(runtime, "pytest_generate_tests")
    clock.advance(3)
    _before(runtime, "pytest_generate_tests")
    clock.advance(17)
    _after(runtime, "pytest_generate_tests")
    clock.advance(5)
    _finish(operation, _Report([]))

    timing = runtime._collector_timings[0]
    assert timing.duration_ns == 36
    assert [
        (hook.hook_name, hook.duration_ns, hook.call_count)
        for hook in timing.hook_timings
    ] == [("pytest_generate_tests", 28, 2)]
    assert timing.outside_observed_hooks_ns == 8


def test_deeply_nested_hooks_are_exclusive_and_counted_once(pytester) -> None:
    clock = _Clock()
    runtime = _runtime(pytester, clock)
    operation = runtime.pytest_make_collect_report(_Collector("module"))
    _enter(operation)

    _before(runtime, "outer")
    clock.advance(5)
    _before(runtime, "middle")
    clock.advance(7)
    _before(runtime, "inner")
    clock.advance(11)
    _after(runtime, "inner")
    clock.advance(13)
    _after(runtime, "middle")
    clock.advance(17)
    _after(runtime, "outer")
    clock.advance(19)
    _finish(operation, _Report([]))

    timing = runtime._collector_timings[0]
    assert {
        hook.hook_name: (hook.duration_ns, hook.call_count)
        for hook in timing.hook_timings
    } == {
        "outer": (22, 1),
        "middle": (20, 1),
        "inner": (11, 1),
    }
    assert timing.outside_observed_hooks_ns == 19


def test_hook_owner_is_captured_before_nested_collector_activates(pytester) -> None:
    clock = _Clock()
    runtime = _runtime(pytester, clock)
    parent = runtime.pytest_make_collect_report(_Collector("parent"))
    _enter(parent)

    _before(runtime, "parent_hook")
    clock.advance(5)
    _before(runtime, "pytest_make_collect_report")
    child = runtime.pytest_make_collect_report(_Collector("parent::child"))
    _enter(child)
    _before(runtime, "child_hook")
    clock.advance(7)
    _after(runtime, "child_hook")
    clock.advance(3)
    _finish(child, _Report([]))
    _after(runtime, "pytest_make_collect_report")
    clock.advance(11)
    _after(runtime, "parent_hook")
    clock.advance(13)
    _finish(parent, _Report([]))

    child_timing, parent_timing = runtime._collector_timings
    assert child_timing.nested_collectors_ns == 0
    assert child_timing.hook_timings[0].hook_name == "child_hook"
    assert child_timing.hook_timings[0].duration_ns == 7
    assert child_timing.outside_observed_hooks_ns == 3

    assert parent_timing.nested_collectors_ns == 10
    assert parent_timing.hook_timings[0].hook_name == "parent_hook"
    assert parent_timing.hook_timings[0].duration_ns == 16
    assert parent_timing.outside_observed_hooks_ns == 13


def test_collection_level_hooks_are_aggregated_separately(pytester) -> None:
    clock = _Clock()
    runtime = _runtime(pytester, clock)

    _before(runtime, "pytest_collection_modifyitems")
    clock.advance(23)
    _after(runtime, "pytest_collection_modifyitems")
    _before(runtime, "pytest_collection_modifyitems")
    clock.advance(29)
    _after(runtime, "pytest_collection_modifyitems")

    aggregate = runtime._collection_hook_aggregates["pytest_collection_modifyitems"]
    assert (aggregate.duration_ns, aggregate.call_count) == (52, 2)


def test_boundary_hooks_affect_nesting_but_are_not_attributed(pytester) -> None:
    clock = _Clock()
    runtime = _runtime(pytester, clock)
    operation = runtime.pytest_make_collect_report(_Collector("module"))
    _enter(operation)

    _before(runtime, "pytest_make_collect_report")
    clock.advance(5)
    _before(runtime, "observed")
    clock.advance(7)
    _after(runtime, "observed")
    clock.advance(11)
    _after(runtime, "pytest_make_collect_report")
    clock.advance(13)
    _finish(operation, _Report([]))

    timing = runtime._collector_timings[0]
    assert [(hook.hook_name, hook.duration_ns) for hook in timing.hook_timings] == [
        ("observed", 7)
    ]
    assert "pytest_make_collect_report" not in runtime._collection_hook_aggregates
    assert timing.outside_observed_hooks_ns == 29


def test_direct_fan_out_uses_only_completed_report_result(pytester) -> None:
    clock = _Clock()
    runtime = _runtime(pytester, clock)
    config = pytester.parseconfig()
    session = pytest.Session.from_config(config)
    module = pytest.Module.from_parent(session, path=pytester.path / "test_api.py")

    class ExampleItem(pytest.Item):
        def runtest(self) -> None:
            pass

    item = ExampleItem.from_parent(module, name="test_one")
    operation = runtime.pytest_make_collect_report(_Collector("module"))
    _enter(operation)
    clock.advance(10)
    _finish(operation, _Report([module, item]))

    timing = runtime._collector_timings[0]
    assert (timing.direct_children, timing.direct_items) == (2, 1)


@pytest.mark.parametrize("unusable_result", [None, object()])
def test_unusable_report_result_keeps_fan_out_unavailable(
    pytester, unusable_result
) -> None:
    clock = _Clock()
    runtime = _runtime(pytester, clock)
    operation = runtime.pytest_make_collect_report(_Collector("module"))
    _enter(operation)
    clock.advance(10)
    _finish(operation, _Report(unusable_result))

    timing = runtime._collector_timings[0]
    assert timing.direct_children is None
    assert timing.direct_items is None


def test_escaping_collector_exception_keeps_fan_out_unavailable_and_cleans_stack(
    pytester,
) -> None:
    clock = _Clock()
    runtime = _runtime(pytester, clock)
    operation = runtime.pytest_make_collect_report(_Collector("module"))
    _enter(operation)
    clock.advance(10)

    with pytest.raises(RuntimeError, match="stopped"):
        operation.throw(RuntimeError("stopped"))

    timing = runtime._collector_timings[0]
    assert timing.direct_children is None
    assert timing.direct_items is None
    assert runtime._collector_stack == []


def test_collection_monitoring_is_removed_after_success(pytester) -> None:
    clock = _Clock()
    config = pytester.parseconfig()
    runtime = _CollectProfilePlugin(config, clock=clock)
    undo_calls = []

    def add_monitoring(before, after):
        assert before == runtime._before_hook_call
        assert after == runtime._after_hook_call

        def undo() -> None:
            undo_calls.append(True)

        return undo

    config.pluginmanager.add_hookcall_monitoring = add_monitoring
    collection = runtime.pytest_collection(type("Session", (), {"items": []})())
    _enter(collection)
    clock.advance(10)
    _finish(collection, object())

    assert undo_calls == [True]
    assert runtime._hook_stack == []


def test_collection_monitoring_is_removed_after_exception(pytester) -> None:
    clock = _Clock()
    config = pytester.parseconfig()
    runtime = _CollectProfilePlugin(config, clock=clock)
    undo_calls = []
    config.pluginmanager.add_hookcall_monitoring = lambda before, after: (
        lambda: undo_calls.append(True)
    )
    collection = runtime.pytest_collection(type("Session", (), {"items": []})())
    _enter(collection)

    with pytest.raises(KeyboardInterrupt):
        collection.throw(KeyboardInterrupt())

    assert undo_calls == [True]
    assert runtime._hook_stack == []


@pytest.mark.parametrize("mode", ["--collect-profile", "--collect-profile-only"])
def test_slow_generate_tests_is_attributed_in_both_modes(
    pytester, monkeypatch, mode
) -> None:
    pytester.makeconftest(
        """
        import time

        def pytest_generate_tests(metafunc):
            time.sleep(0.03)
        """
    )
    pytester.makepyfile("def test_one(): pass")

    result = _run(pytester, monkeypatch, mode, "-q")

    assert result.ret == 0
    block = _collector_block(
        result.stdout.str(),
        "Module",
        "test_slow_generate_tests_is_attributed_in_both_modes.py",
    )
    match = re.search(
        r"(?m)^   (\d+\.\d{3})s \| 1 call \| pytest_generate_tests$", block
    )
    assert match is not None
    assert float(match.group(1)) >= 0.02


def test_slow_collection_modifyitems_is_collection_level_work(
    pytester, monkeypatch
) -> None:
    pytester.makeconftest(
        """
        import time

        def pytest_collection_modifyitems(items):
            time.sleep(0.03)
        """
    )
    pytester.makepyfile("def test_one(): pass")

    result = _run(pytester, monkeypatch, "--collect-profile-only", "-q")

    assert result.ret == 0
    output = result.stdout.str()
    collection_section = output.split("collection-level hooks", 1)[1]
    match = re.search(
        r"(?m)^   (\d+\.\d{3})s \| 1 call \| pytest_collection_modifyitems$",
        collection_section,
    )
    assert match is not None
    assert float(match.group(1)) >= 0.02


def test_large_parametrization_reports_direct_fan_out_without_item_listing(
    pytester, monkeypatch
) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.parametrize("case", range(200))
        def test_many(case):
            pass
        """
    )

    result = _run(pytester, monkeypatch, "--collect-profile-only", "-q")

    assert result.ret == 0
    output = result.stdout.str()
    block = _collector_block(
        output,
        "Module",
        "test_large_parametrization_reports_direct_fan_out_without_item_listing.py",
    )
    assert "direct fan-out: 200 children | 200 items" in block
    assert "test_many[" not in output
    assert output.count("direct fan-out:") <= 3


def test_direct_custom_collector_work_remains_outside_observed_hooks(
    pytester, monkeypatch
) -> None:
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

    result = _run(pytester, monkeypatch, "--collect-profile-only", "-q")

    assert result.ret == 5
    block = _collector_block(result.stdout.str(), "SlowFile", "slow.case")
    match = re.search(r"(?m)^   (\d+\.\d{3})s \| outside observed hooks$", block)
    assert match is not None
    assert float(match.group(1)) >= 0.02


def test_slow_import_dominates_residual_without_causal_label(
    pytester, monkeypatch
) -> None:
    pytester.makepyfile(
        """
        import time
        time.sleep(0.03)

        def test_one():
            pass
        """
    )

    result = _run(pytester, monkeypatch, "--collect-profile-only", "-q")

    assert result.ret == 0
    output = result.stdout.str()
    block = _collector_block(
        output,
        "Module",
        "test_slow_import_dominates_residual_without_causal_label.py",
    )
    match = re.search(r"(?m)^   (\d+\.\d{3})s \| outside observed hooks$", block)
    assert match is not None
    assert float(match.group(1)) >= 0.02
    assert "import time" not in output
    assert "plugin" not in output
    assert "optimiz" not in output.lower()


def test_nested_hooks_and_collectors_keep_accounting_bounded(
    pytester, monkeypatch
) -> None:
    pytester.makeconftest(
        """
        import time

        def pytest_generate_tests(metafunc):
            if metafunc.cls is not None:
                time.sleep(0.03)
        """
    )
    pytester.makepyfile(
        """
        import pytest

        class TestGroup:
            @pytest.mark.parametrize("case", range(3))
            def test_many(self, case):
                pass
        """
    )

    result = _run(
        pytester,
        monkeypatch,
        "--collect-profile-only",
        "-q",
        "test_nested_hooks_and_collectors_keep_accounting_bounded.py",
    )

    assert result.ret == 0
    output = result.stdout.str()
    class_block = _collector_block(
        output,
        "Class",
        "test_nested_hooks_and_collectors_keep_accounting_bounded.py::TestGroup",
    )
    module_block = _collector_block(
        output,
        "Module",
        "test_nested_hooks_and_collectors_keep_accounting_bounded.py",
    )
    session_block = _collector_block(output, "Session", "<session>")
    assert "pytest_generate_tests" in class_block
    assert "pytest_pycollect_makeitem" in module_block
    assert "nested collectors" in session_block
    assert output.count("collector attribution") == 1
    assert output.count("Total collection:") == 1


def test_hook_failure_keeps_native_error_and_complete_profile(
    pytester, monkeypatch
) -> None:
    pytester.makeconftest(
        """
        def pytest_generate_tests(metafunc):
            raise RuntimeError("HOOK FAILED")
        """
    )
    pytester.makepyfile("def test_one(): pass")

    profiled = _run(pytester, monkeypatch, "--collect-profile-only", "-q")
    native = _run(pytester, monkeypatch, "--collect-only", "-q")

    assert profiled.ret == native.ret == 2
    assert "HOOK FAILED" in profiled.stdout.str()
    assert "pytest_generate_tests" in profiled.stdout.str()
    assert profiled.stdout.str().count("Total collection:") == 1
