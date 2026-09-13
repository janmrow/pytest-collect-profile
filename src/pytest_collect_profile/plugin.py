"""Pytest hooks for collection profiling."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from time import perf_counter_ns

import pytest

_PROFILE_OPTION = "--collect-profile"
_PROFILE_ONLY_OPTION = "--collect-profile-only"
_RUNTIME_PLUGIN_NAME = "pytest-collect-profile-runtime"
_ROW_LIMIT = 10
_XDIST_USAGE_ERROR = (
    "--collect-profile-only does not support active pytest-xdist distribution; use -n0"
)


@dataclass(frozen=True)
class _CollectorTiming:
    duration_ns: int
    collector_type: str
    nodeid: str


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("collect profile")
    group.addoption(
        _PROFILE_OPTION,
        action="store_true",
        default=False,
        help="show the slowest collectors after collection",
    )
    group.addoption(
        _PROFILE_ONLY_OPTION,
        action="store_true",
        default=False,
        help="profile collection without running tests or listing collected nodes",
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

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_make_collect_report(self, collector: pytest.Collector):
        started_at = self._clock()
        try:
            result = yield
        finally:
            self._collector_timings.append(
                _CollectorTiming(
                    duration_ns=self._clock() - started_at,
                    collector_type=type(collector).__name__,
                    nodeid=collector.nodeid,
                )
            )
        return result

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_collection(self, session: pytest.Session):
        started_at = self._clock()
        result = yield
        total_duration_ns = self._clock() - started_at
        self._write_report(total_duration_ns, len(session.items))
        if self._activate_collect_only:
            self._config.option.collectonly = True
        return result

    def _write_report(self, total_duration_ns: int, item_count: int) -> None:
        terminal_reporter = self._config.pluginmanager.get_plugin("terminalreporter")
        if terminal_reporter is None:
            return

        terminal_reporter.section("collect profile")
        for line in _report_lines(
            self._collector_timings, total_duration_ns, item_count
        ):
            terminal_reporter.write_line(line)


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
    timings: Iterable[_CollectorTiming], total_duration_ns: int, item_count: int
) -> list[str]:
    lines = [f"{'time':<6}    {'collector':<11} node"]

    for timing in _rank_timings(timings):
        duration = _format_duration(timing.duration_ns)
        nodeid = timing.nodeid or "<session>"
        lines.append(f"{duration:<6}    {timing.collector_type:<11} {nodeid}")

    lines.extend(
        [
            "",
            f"Total collection: {_format_duration(total_duration_ns)} | {item_count} items",
        ]
    )
    return lines


def _format_duration(duration_ns: int) -> str:
    return f"{duration_ns / 1_000_000_000:.3f}s"
