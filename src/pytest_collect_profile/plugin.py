"""Pytest hooks for collection profiling."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from time import perf_counter_ns

import pytest

_PROFILE_OPTION = "--collect-profile"
_PROFILE_ONLY_OPTION = "--collect-profile-only"
_JSON_OPTION = "--collect-profile-json"
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
_JSON_USAGE_ERROR = (
    "--collect-profile-json requires --collect-profile or --collect-profile-only"
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


@dataclass(frozen=True)
class _CollectorAttribution:
    direct_children: int | None
    direct_items: int | None
    hook_timings: tuple[_HookTiming, ...]
    nested_collectors_ns: int
    outside_observed_hooks_ns: int


@dataclass(frozen=True)
class _RankedCollector:
    rank: int
    duration_ns: int
    collector_type: str
    nodeid: str
    attribution: _CollectorAttribution | None


@dataclass(frozen=True)
class _ProfileSnapshot:
    collectors: tuple[_RankedCollector, ...]
    collection_hook_timings: tuple[_HookTiming, ...]
    total_collection_ns: int
    item_count: int


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
    group.addoption(
        _JSON_OPTION,
        action="store_true",
        default=False,
        help="emit the collection profile as one compact JSON object",
    )


def pytest_configure(config: pytest.Config) -> None:
    profile_enabled = config.getoption(_PROFILE_OPTION)
    profile_only_enabled = config.getoption(_PROFILE_ONLY_OPTION)
    json_enabled = config.getoption(_JSON_OPTION)
    if json_enabled and not (profile_enabled or profile_only_enabled):
        raise pytest.UsageError(_JSON_USAGE_ERROR)
    if not (profile_enabled or profile_only_enabled):
        return

    if profile_only_enabled and _xdist_is_active(config):
        raise pytest.UsageError(_XDIST_USAGE_ERROR)

    config.pluginmanager.register(
        _CollectProfilePlugin(
            config,
            profile_only=profile_only_enabled,
            native_collect_only=config.getoption("collectonly"),
            json_output=json_enabled,
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
        json_output: bool = False,
    ) -> None:
        self._config = config
        self._clock = clock
        self._activate_collect_only = profile_only and not native_collect_only
        self._json_output = json_output
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

        snapshot = _build_profile_snapshot(
            self._collector_timings,
            total_duration_ns,
            item_count,
            collection_hook_timings=_freeze_hook_aggregates(
                self._collection_hook_aggregates
            ),
        )
        if self._json_output:
            terminal_reporter.write_line(_json_report(snapshot))
            return

        terminal_reporter.section("collect profile")
        for line in _text_report_lines(snapshot):
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


def _bounded_hook_timings(
    hook_timings: Iterable[_HookTiming], *, limit: int
) -> tuple[_HookTiming, ...]:
    ranked_hooks = sorted(
        hook_timings,
        key=lambda timing: (-timing.duration_ns, timing.hook_name),
    )
    bounded_hooks = ranked_hooks[:limit]
    folded_hooks = ranked_hooks[limit:]
    if folded_hooks:
        bounded_hooks.append(
            _HookTiming(
                duration_ns=sum(timing.duration_ns for timing in folded_hooks),
                call_count=sum(timing.call_count for timing in folded_hooks),
                hook_name="other observed hooks",
            )
        )
    return tuple(bounded_hooks)


def _build_profile_snapshot(
    timings: Iterable[_CollectorTiming],
    total_duration_ns: int,
    item_count: int,
    *,
    collection_hook_timings: Iterable[_HookTiming] = (),
) -> _ProfileSnapshot:
    ranked_timings = _rank_timings(timings)
    collectors = []
    for rank, timing in enumerate(ranked_timings, start=1):
        attribution = None
        if rank <= _COLLECTOR_DETAIL_LIMIT:
            attribution = _CollectorAttribution(
                direct_children=timing.direct_children,
                direct_items=timing.direct_items,
                hook_timings=_bounded_hook_timings(
                    timing.hook_timings,
                    limit=_COLLECTOR_HOOK_LIMIT,
                ),
                nested_collectors_ns=timing.nested_collectors_ns,
                outside_observed_hooks_ns=timing.outside_observed_hooks_ns,
            )
        collectors.append(
            _RankedCollector(
                rank=rank,
                duration_ns=timing.duration_ns,
                collector_type=timing.collector_type,
                nodeid=timing.nodeid,
                attribution=attribution,
            )
        )
    return _ProfileSnapshot(
        collectors=tuple(collectors),
        collection_hook_timings=_bounded_hook_timings(
            collection_hook_timings,
            limit=_COLLECTION_HOOK_LIMIT,
        ),
        total_collection_ns=total_duration_ns,
        item_count=item_count,
    )


def _text_report_lines(snapshot: _ProfileSnapshot) -> list[str]:
    lines = [f"{'time':<6}    {'collector':<11} node"]

    for collector in snapshot.collectors:
        duration = _format_duration(collector.duration_ns)
        nodeid = collector.nodeid or "<session>"
        lines.append(f"{duration:<6}    {collector.collector_type:<11} {nodeid}")

    lines.extend(["", "collector attribution"])
    for collector in snapshot.collectors:
        attribution = collector.attribution
        if attribution is None:
            continue
        nodeid = collector.nodeid or "<session>"
        lines.append(f"{collector.rank}. {collector.collector_type} {nodeid}")
        lines.append(f"   {_fan_out_line(attribution)}")
        lines.extend(_format_bounded_hook_lines(attribution.hook_timings))
        if attribution.nested_collectors_ns:
            lines.append(
                f"   {_format_duration(attribution.nested_collectors_ns)} | "
                "nested collectors"
            )
        lines.append(
            f"   {_format_duration(attribution.outside_observed_hooks_ns)} | "
            "outside observed hooks"
        )

    if snapshot.collection_hook_timings:
        lines.extend(["", "collection-level hooks"])
        lines.extend(_format_bounded_hook_lines(snapshot.collection_hook_timings))

    lines.extend(
        [
            "",
            "Total collection: "
            f"{_format_duration(snapshot.total_collection_ns)} | "
            f"{snapshot.item_count} items",
        ]
    )
    return lines


def _fan_out_line(attribution: _CollectorAttribution) -> str:
    if attribution.direct_children is None or attribution.direct_items is None:
        return "direct fan-out: unavailable"
    return (
        f"direct fan-out: {attribution.direct_children} children | "
        f"{attribution.direct_items} items"
    )


def _format_bounded_hook_lines(hook_timings: Iterable[_HookTiming]) -> list[str]:
    return [
        _format_hook_line(timing.duration_ns, timing.call_count, timing.hook_name)
        for timing in hook_timings
    ]


def _json_report(snapshot: _ProfileSnapshot) -> str:
    collectors = []
    for collector in snapshot.collectors:
        attribution = collector.attribution
        collectors.append(
            {
                "rank": collector.rank,
                "duration_ns": collector.duration_ns,
                "collector_type": collector.collector_type,
                "nodeid": collector.nodeid,
                "attribution": (
                    None
                    if attribution is None
                    else {
                        "direct_children": attribution.direct_children,
                        "direct_items": attribution.direct_items,
                        "hooks": _json_hooks(attribution.hook_timings),
                        "nested_collectors_ns": attribution.nested_collectors_ns,
                        "outside_observed_hooks_ns": (
                            attribution.outside_observed_hooks_ns
                        ),
                    }
                ),
            }
        )
    report = {
        "schema": "pytest-collect-profile",
        "schema_version": 1,
        "profile_complete": True,
        "collectors": collectors,
        "collection_hooks": _json_hooks(snapshot.collection_hook_timings),
        "total_collection_ns": snapshot.total_collection_ns,
        "item_count": snapshot.item_count,
    }
    return json.dumps(report, ensure_ascii=True, separators=(",", ":"))


def _json_hooks(hook_timings: Iterable[_HookTiming]) -> list[dict[str, object]]:
    return [
        {
            "name": timing.hook_name,
            "duration_ns": timing.duration_ns,
            "call_count": timing.call_count,
        }
        for timing in hook_timings
    ]


def _format_hook_line(duration_ns: int, call_count: int, label: str) -> str:
    call_label = "call" if call_count == 1 else "calls"
    return f"   {_format_duration(duration_ns)} | {call_count} {call_label} | {label}"


def _format_duration(duration_ns: int) -> str:
    return f"{duration_ns / 1_000_000_000:.3f}s"
