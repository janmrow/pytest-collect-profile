"""Pytest hooks for collection profiling."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from time import perf_counter_ns

import pytest

_PROFILE_OPTION = "--collect-profile"
_PROFILE_ONLY_OPTION = "--collect-profile-only"
_RUNTIME_PLUGIN_NAME = "pytest-collect-profile-runtime"
_ROW_LIMIT = 10
_COLLECTOR_DETAIL_LIMIT = 3
_COLLECTOR_HOOK_LIMIT = 3
_COLLECTION_HOOK_LIMIT = 3
_ATTRIBUTION_BOUNDARY_HOOKS = frozenset(
    {"pytest_collection", "pytest_make_collect_report"}
)
_XDIST_USAGE_ERROR = (
    "--collect-profile-only does not support active pytest-xdist distribution; use -n0"
)


@dataclass(frozen=True)
class _HookTiming:
    duration_ns: int
    call_count: int
    hook_name: str


@dataclass(frozen=True)
class _CollectorTiming:
    duration_ns: int
    collector_type: str
    nodeid: str
    direct_children: int | None = None
    direct_items: int | None = None
    nested_collectors_ns: int = 0
    hook_timings: tuple[_HookTiming, ...] = ()

    @property
    def outside_observed_hooks_ns(self) -> int:
        return (
            self.duration_ns
            - sum(timing.duration_ns for timing in self.hook_timings)
            - self.nested_collectors_ns
        )


@dataclass(slots=True)
class _HookAggregate:
    duration_ns: int = 0
    call_count: int = 0


@dataclass(slots=True)
class _CollectorFrame:
    started_at: int
    collector_type: str
    nodeid: str
    hook_aggregates: dict[str, _HookAggregate] = field(default_factory=dict)
    nested_collectors_ns: int = 0


@dataclass(slots=True)
class _HookCallFrame:
    started_at: int
    hook_name: str
    owner: _CollectorFrame | None
    nested_hooks_ns: int = 0


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("collect profile")
    group.addoption(
        _PROFILE_OPTION,
        action="store_true",
        default=False,
        help="show the slowest collectors with collection-time attribution",
    )
    group.addoption(
        _PROFILE_ONLY_OPTION,
        action="store_true",
        default=False,
        help=(
            "profile collection with attribution without running tests or listing "
            "collected nodes"
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    profile_enabled = config.getoption(_PROFILE_OPTION)
    profile_only_enabled = config.getoption(_PROFILE_ONLY_OPTION)
    if not (profile_enabled or profile_only_enabled):
        return

    if profile_only_enabled and _xdist_is_active(config):
        raise pytest.UsageError(_XDIST_USAGE_ERROR)

    config.pluginmanager.register(
        _CollectProfilePlugin(
            config,
            profile_only=profile_only_enabled,
            native_collect_only=config.getoption("collectonly"),
        ),
        name=_RUNTIME_PLUGIN_NAME,
    )


def _xdist_is_active(config: pytest.Config) -> bool:
    distribution_mode = config.getoption("dist", default="no")
    transmitters = config.getoption("tx", default=())
    return distribution_mode != "no" and bool(transmitters)


class _CollectProfilePlugin:
    def __init__(
        self,
        config: pytest.Config,
        clock: Callable[[], int] = perf_counter_ns,
        *,
        profile_only: bool = False,
        native_collect_only: bool = False,
    ) -> None:
        self._config = config
        self._clock = clock
        self._activate_collect_only = profile_only and not native_collect_only
        self._collector_timings: list[_CollectorTiming] = []
        self._collector_stack: list[_CollectorFrame] = []
        self._hook_stack: list[_HookCallFrame] = []
        self._collection_hook_aggregates: dict[str, _HookAggregate] = {}

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_make_collect_report(self, collector: pytest.Collector):
        frame = _CollectorFrame(
            started_at=self._clock(),
            collector_type=type(collector).__name__,
            nodeid=collector.nodeid,
        )
        self._collector_stack.append(frame)
        result = None
        try:
            result = yield
        finally:
            duration_ns = self._clock() - frame.started_at
            popped_frame = self._collector_stack.pop()
            assert popped_frame is frame
            if self._collector_stack:
                self._collector_stack[-1].nested_collectors_ns += duration_ns

            direct_children, direct_items = _direct_fan_out(result)
            self._collector_timings.append(
                _completed_collector_timing(
                    frame,
                    duration_ns=duration_ns,
                    direct_children=direct_children,
                    direct_items=direct_items,
                )
            )
        return result

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_collection(self, session: pytest.Session):
        started_at = self._clock()
        undo_monitoring = self._config.pluginmanager.add_hookcall_monitoring(
            self._before_hook_call,
            self._after_hook_call,
        )
        try:
            result = yield
        finally:
            undo_monitoring()
        total_duration_ns = self._clock() - started_at
        self._write_report(total_duration_ns, len(session.items))
        if self._activate_collect_only:
            self._config.option.collectonly = True
        return result

    def _before_hook_call(
        self,
        hook_name: str,
        _hook_impls: object,
        _caller_kwargs: Mapping[str, object],
    ) -> None:
        owner = self._collector_stack[-1] if self._collector_stack else None
        self._hook_stack.append(
            _HookCallFrame(
                started_at=self._clock(),
                hook_name=hook_name,
                owner=owner,
            )
        )

    def _after_hook_call(
        self,
        _outcome: object,
        hook_name: str,
        _hook_impls: object,
        _caller_kwargs: Mapping[str, object],
    ) -> None:
        finished_at = self._clock()
        frame = self._hook_stack.pop()
        assert frame.hook_name == hook_name

        inclusive_ns = finished_at - frame.started_at
        if self._hook_stack:
            self._hook_stack[-1].nested_hooks_ns += inclusive_ns

        if hook_name in _ATTRIBUTION_BOUNDARY_HOOKS:
            return

        exclusive_ns = inclusive_ns - frame.nested_hooks_ns
        aggregates = (
            frame.owner.hook_aggregates
            if frame.owner is not None
            else self._collection_hook_aggregates
        )
        aggregate = aggregates.get(hook_name)
        if aggregate is None:
            aggregates[hook_name] = _HookAggregate(exclusive_ns, 1)
        else:
            aggregate.duration_ns += exclusive_ns
            aggregate.call_count += 1

    def _write_report(self, total_duration_ns: int, item_count: int) -> None:
        terminal_reporter = self._config.pluginmanager.get_plugin("terminalreporter")
        if terminal_reporter is None:
            return

        terminal_reporter.section("collect profile")
        for line in _report_lines(
            self._collector_timings,
            total_duration_ns,
            item_count,
            collection_hook_timings=_freeze_hook_aggregates(
                self._collection_hook_aggregates
            ),
        ):
            terminal_reporter.write_line(line)


def _completed_collector_timing(
    frame: _CollectorFrame,
    *,
    duration_ns: int,
    direct_children: int | None,
    direct_items: int | None,
) -> _CollectorTiming:
    return _CollectorTiming(
        duration_ns=duration_ns,
        collector_type=frame.collector_type,
        nodeid=frame.nodeid,
        direct_children=direct_children,
        direct_items=direct_items,
        nested_collectors_ns=frame.nested_collectors_ns,
        hook_timings=_freeze_hook_aggregates(frame.hook_aggregates),
    )


def _freeze_hook_aggregates(
    aggregates: Mapping[str, _HookAggregate],
) -> tuple[_HookTiming, ...]:
    return tuple(
        _HookTiming(
            duration_ns=aggregate.duration_ns,
            call_count=aggregate.call_count,
            hook_name=hook_name,
        )
        for hook_name, aggregate in aggregates.items()
    )


def _direct_fan_out(report: object) -> tuple[int | None, int | None]:
    result = getattr(report, "result", None)
    if not isinstance(result, (list, tuple)):
        return None, None
    return len(result), sum(isinstance(node, pytest.Item) for node in result)


def _rank_timings(timings: Iterable[_CollectorTiming]) -> list[_CollectorTiming]:
    return sorted(
        timings,
        key=lambda timing: (
            -timing.duration_ns,
            timing.nodeid,
            timing.collector_type,
        ),
    )[:_ROW_LIMIT]


def _report_lines(
    timings: Iterable[_CollectorTiming],
    total_duration_ns: int,
    item_count: int,
    *,
    collection_hook_timings: Iterable[_HookTiming] = (),
) -> list[str]:
    lines = [f"{'time':<6}    {'collector':<11} node"]
    ranked_timings = _rank_timings(timings)

    for timing in ranked_timings:
        duration = _format_duration(timing.duration_ns)
        nodeid = timing.nodeid or "<session>"
        lines.append(f"{duration:<6}    {timing.collector_type:<11} {nodeid}")

    lines.extend(["", "collector attribution"])
    for index, timing in enumerate(ranked_timings[:_COLLECTOR_DETAIL_LIMIT], start=1):
        nodeid = timing.nodeid or "<session>"
        lines.append(f"{index}. {timing.collector_type} {nodeid}")
        lines.append(f"   {_fan_out_line(timing)}")
        lines.extend(
            _format_hook_lines(timing.hook_timings, limit=_COLLECTOR_HOOK_LIMIT)
        )
        if timing.nested_collectors_ns:
            lines.append(
                f"   {_format_duration(timing.nested_collectors_ns)} | "
                "nested collectors"
            )
        lines.append(
            f"   {_format_duration(timing.outside_observed_hooks_ns)} | "
            "outside observed hooks"
        )

    collection_hook_timings = tuple(collection_hook_timings)
    if collection_hook_timings:
        lines.extend(["", "collection-level hooks"])
        lines.extend(
            _format_hook_lines(
                collection_hook_timings,
                limit=_COLLECTION_HOOK_LIMIT,
            )
        )

    lines.extend(
        [
            "",
            f"Total collection: {_format_duration(total_duration_ns)} | {item_count} items",
        ]
    )
    return lines


def _fan_out_line(timing: _CollectorTiming) -> str:
    if timing.direct_children is None or timing.direct_items is None:
        return "direct fan-out: unavailable"
    return (
        f"direct fan-out: {timing.direct_children} children | "
        f"{timing.direct_items} items"
    )


def _format_hook_lines(hook_timings: Iterable[_HookTiming], *, limit: int) -> list[str]:
    ranked_hooks = sorted(
        hook_timings,
        key=lambda timing: (-timing.duration_ns, timing.hook_name),
    )
    lines = [
        _format_hook_line(timing.duration_ns, timing.call_count, timing.hook_name)
        for timing in ranked_hooks[:limit]
    ]
    folded_hooks = ranked_hooks[limit:]
    if folded_hooks:
        lines.append(
            _format_hook_line(
                sum(timing.duration_ns for timing in folded_hooks),
                sum(timing.call_count for timing in folded_hooks),
                "other observed hooks",
            )
        )
    return lines


def _format_hook_line(duration_ns: int, call_count: int, label: str) -> str:
    call_label = "call" if call_count == 1 else "calls"
    return f"   {_format_duration(duration_ns)} | {call_count} {call_label} | {label}"


def _format_duration(duration_ns: int) -> str:
    return f"{duration_ns / 1_000_000_000:.3f}s"
