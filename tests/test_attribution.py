from __future__ import annotations

from dataclasses import dataclass

import pytest

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
