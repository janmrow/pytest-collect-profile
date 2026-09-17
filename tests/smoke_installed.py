"""Exercise the public workflow from an installed wheel in a fresh environment."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    wheel = parser.parse_args().wheel.resolve(strict=True)

    with tempfile.TemporaryDirectory(prefix="pytest-collect-profile-smoke-") as root:
        root_path = Path(root)
        environment = root_path / "venv"
        suite = root_path / "suite"
        suite.mkdir()

        venv.EnvBuilder(with_pip=True).create(environment)
        python = _environment_python(environment)
        pytest_command = _environment_pytest(environment)
        clean_environment = _clean_subprocess_environment()

        _run(
            python,
            "-m",
            "pip",
            "install",
            str(wheel),
            environment=clean_environment,
            timeout=120,
        )
        _write_suite(suite)
        execution_marker = suite / "test-executed"

        help_result = _run(
            python,
            "-m",
            "pytest",
            "--help",
            cwd=suite,
            environment=clean_environment,
        )
        _require(
            len(re.findall(r"(?m)^  --collect-profile(?:\s|$)", help_result.stdout))
            == 1,
            "installed pytest did not expose exactly one --collect-profile option",
            help_result,
        )
        _require(
            len(
                re.findall(r"(?m)^  --collect-profile-only(?:\s|$)", help_result.stdout)
            )
            == 1,
            "installed pytest did not expose exactly one --collect-profile-only option",
            help_result,
        )
        _require(
            len(
                re.findall(r"(?m)^  --collect-profile-json(?:\s|$)", help_result.stdout)
            )
            == 1,
            "installed pytest did not expose exactly one --collect-profile-json option",
            help_result,
        )

        collect_only_result = _run(
            pytest_command,
            "--collect-profile",
            "--collect-only",
            cwd=suite,
            environment=clean_environment,
        )
        _check_collect_only_run(collect_only_result)
        _require(
            not execution_marker.exists(),
            "the README collect-only workflow executed a test",
            collect_only_result,
        )

        profile_only_result = _run(
            pytest_command,
            "--collect-profile-only",
            cwd=suite,
            environment=clean_environment,
        )
        _check_profile_only_run(profile_only_result)
        _require(
            not execution_marker.exists(),
            "--collect-profile-only executed a test",
            profile_only_result,
        )

        combined_options_result = _run(
            pytest_command,
            "--collect-profile",
            "--collect-profile-only",
            cwd=suite,
            environment=clean_environment,
        )
        _check_profile_only_run(combined_options_result)
        _require(
            not execution_marker.exists(),
            "the combined profile options executed a test",
            combined_options_result,
        )

        profiled_result = _run(
            pytest_command,
            "--collect-profile",
            cwd=suite,
            environment=clean_environment,
        )
        _check_profiled_run(profiled_result)
        _require(
            execution_marker.exists(),
            "--collect-profile prevented normal test execution",
            profiled_result,
        )
        execution_marker.unlink()

        json_profiled_result = _run(
            pytest_command,
            "--collect-profile",
            "--collect-profile-json",
            cwd=suite,
            environment=clean_environment,
        )
        _check_json_run(json_profiled_result, item_listing=True)
        _require(
            execution_marker.exists(),
            "normal JSON profiling prevented test execution",
            json_profiled_result,
        )
        execution_marker.unlink()

        json_profile_only_result = _run(
            pytest_command,
            "--collect-profile-only",
            "--collect-profile-json",
            cwd=suite,
            environment=clean_environment,
        )
        _check_json_run(json_profile_only_result, item_listing=False)
        _require(
            not execution_marker.exists(),
            "profile-only JSON executed a test",
            json_profile_only_result,
        )

        json_combined_result = _run(
            pytest_command,
            "--collect-profile",
            "--collect-profile-only",
            "--collect-profile-json",
            cwd=suite,
            environment=clean_environment,
        )
        _check_json_run(json_combined_result, item_listing=False)
        _require(
            not execution_marker.exists(),
            "combined profile options with JSON executed a test",
            json_combined_result,
        )

        json_collect_only_result = _run(
            pytest_command,
            "--collect-profile",
            "--collect-profile-json",
            "--collect-only",
            cwd=suite,
            environment=clean_environment,
        )
        _check_json_run(json_collect_only_result, item_listing=True)
        _require(
            not execution_marker.exists(),
            "explicit collect-only with JSON executed a test",
            json_collect_only_result,
        )

        modifier_only_result = _run(
            pytest_command,
            "--collect-profile-json",
            cwd=suite,
            environment=clean_environment,
            expected_returncode=4,
        )
        _require(
            "--collect-profile-json requires --collect-profile or "
            "--collect-profile-only" in modifier_only_result.stderr,
            "modifier-only use did not produce the expected usage error",
            modifier_only_result,
        )
        _require(
            '"schema":"pytest-collect-profile"' not in modifier_only_result.stdout,
            "modifier-only use emitted a JSON profile",
            modifier_only_result,
        )
        _require(
            not execution_marker.exists(),
            "modifier-only use executed a test",
            modifier_only_result,
        )

        unprofiled_result = _run(
            python,
            "-m",
            "pytest",
            "-q",
            "-s",
            cwd=suite,
            environment=clean_environment,
        )
        _check_unprofiled_run(unprofiled_result)
        _require(
            execution_marker.exists(),
            "the unprofiled test did not execute",
            unprofiled_result,
        )

    print("installed wheel smoke test passed")


def _environment_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _environment_pytest(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "pytest.exe"
    return environment / "bin" / "pytest"


def _clean_subprocess_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "PYTEST_ADDOPTS",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
        "PYTEST_PLUGINS",
    ):
        environment.pop(name, None)
    return environment


def _write_suite(suite: Path) -> None:
    (suite / "conftest.py").write_text(
        """
import time

import pytest


class SlowFile(pytest.File):
    def collect(self):
        time.sleep(0.05)
        return []


class HostileFile(pytest.File):
    def collect(self):
        return []


def pytest_collect_file(file_path, parent):
    if file_path.name == "slow.case":
        return SlowFile.from_parent(parent, path=file_path)
    if file_path.name == "hostile_żółw_$(echo).case":
        return HostileFile.from_parent(parent, path=file_path)


def pytest_generate_tests(metafunc):
    time.sleep(0.03)


def pytest_collection_modifyitems(items):
    time.sleep(0.02)
""".lstrip(),
        encoding="utf-8",
    )
    (suite / "slow.case").write_text("content\n", encoding="utf-8")
    (suite / "hostile_żółw_$(echo).case").write_text("content\n", encoding="utf-8")
    (suite / "test_sample.py").write_text(
        """
from pathlib import Path


def test_runs():
    Path("test-executed").write_text("executed", encoding="utf-8")
    print("TEST EXECUTED")
""".lstrip(),
        encoding="utf-8",
    )


def _run(
    *command: str | Path,
    cwd: Path | None = None,
    environment: dict[str, str],
    timeout: int = 30,
    expected_returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    string_command = [str(part) for part in command]
    result = subprocess.run(
        string_command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    _require(
        result.returncode == expected_returncode,
        f"command failed: {shlex.join(string_command)}",
        result,
    )
    return result


def _check_profiled_run(result: subprocess.CompletedProcess[str]) -> None:
    output = result.stdout
    _require(
        re.search(
            r"(?m)^time\s+collector\s+node\n"
            r"\d+\.\d{3}s\s+SlowFile\s+slow\.case$",
            output,
        )
        is not None,
        "the deliberately slow collector was not the first reported row",
        result,
    )
    _require(
        re.search(r"Total collection: \d+\.\d{3}s \| 1 items", output) is not None,
        "the installed plugin did not print the collection summary",
        result,
    )
    _check_attribution(result)
    _require("1 passed" in output, "the profiled test did not pass", result)


def _check_profile_only_run(result: subprocess.CompletedProcess[str]) -> None:
    output = result.stdout
    _require(
        output.count("collect profile") == 1,
        "profile-only mode did not emit exactly one report",
        result,
    )
    _require(
        re.search(
            r"(?m)^time\s+collector\s+node\n"
            r"\d+\.\d{3}s\s+SlowFile\s+slow\.case$",
            output,
        )
        is not None,
        "profile-only mode did not rank the deliberately slow collector first",
        result,
    )
    _require(
        re.search(r"Total collection: \d+\.\d{3}s \| 1 items", output) is not None,
        "profile-only mode did not print the collection summary",
        result,
    )
    _require(
        "1 test collected" in output,
        "profile-only mode did not preserve pytest's collection outcome",
        result,
    )
    _require(
        "test_sample.py::test_runs" not in output,
        "profile-only mode printed the routine collected-node listing",
        result,
    )
    _check_attribution(result)


def _check_collect_only_run(result: subprocess.CompletedProcess[str]) -> None:
    output = result.stdout
    _require(
        re.search(
            r"(?m)^time\s+collector\s+node\n"
            r"\d+\.\d{3}s\s+SlowFile\s+slow\.case$",
            output,
        )
        is not None,
        "the README workflow did not rank the deliberately slow collector first",
        result,
    )
    _require(
        re.search(r"Total collection: \d+\.\d{3}s \| 1 items", output) is not None,
        "the README workflow did not print the collection summary",
        result,
    )
    _require(
        "1 test collected" in output,
        "the README workflow did not preserve pytest's collect-only outcome",
        result,
    )
    _require(
        "test_runs" in output,
        "the README workflow did not preserve pytest's collected-node listing",
        result,
    )
    _check_attribution(result)


def _check_attribution(result: subprocess.CompletedProcess[str]) -> None:
    output = result.stdout
    _require(
        output.count("collector attribution") == 1,
        "the installed plugin did not emit one collector attribution section",
        result,
    )
    _require(
        "direct fan-out:" in output,
        "the installed plugin did not report direct fan-out",
        result,
    )
    _require(
        re.search(
            r"(?m)^   \d+\.\d{3}s \| 1 call \| pytest_generate_tests$",
            output,
        )
        is not None,
        "the installed plugin did not attribute pytest_generate_tests",
        result,
    )
    _require(
        "collection-level hooks" in output
        and "pytest_collection_modifyitems" in output,
        "the installed plugin did not attribute collection-level hook work",
        result,
    )
    _require(
        "outside observed hooks" in output,
        "the installed plugin did not report the unobserved residual",
        result,
    )
    _require(
        "pytest_make_collect_report" not in output,
        "the installed plugin reported its collector timing boundary as attribution",
        result,
    )


def _check_json_run(
    result: subprocess.CompletedProcess[str], *, item_listing: bool
) -> None:
    json_lines = [
        line
        for line in result.stdout.splitlines()
        if line.startswith('{"schema":"pytest-collect-profile"')
    ]
    _require(
        len(json_lines) == 1,
        "installed plugin did not emit exactly one JSON profile line",
        result,
    )
    profile = json.loads(json_lines[0])
    _require(
        list(profile)
        == [
            "schema",
            "schema_version",
            "profile_complete",
            "collectors",
            "collection_hooks",
            "total_collection_ns",
            "item_count",
        ],
        "installed JSON profile did not match the v1 top-level schema",
        result,
    )
    _require(
        profile["collectors"][0]["collector_type"] == "SlowFile"
        and profile["collectors"][0]["nodeid"] == "slow.case",
        "the deterministic JSON consumer did not find the expected hotspot",
        result,
    )
    _require(
        isinstance(profile["total_collection_ns"], int)
        and profile["total_collection_ns"] > 0
        and profile["item_count"] == 1,
        "the deterministic JSON consumer did not read total or item count",
        result,
    )
    first_attribution = profile["collectors"][0]["attribution"]
    _require(
        isinstance(first_attribution["outside_observed_hooks_ns"], int)
        and first_attribution["outside_observed_hooks_ns"] > 0,
        "the deterministic JSON consumer did not read the hotspot residual",
        result,
    )
    collector_hooks = {
        hook["name"]
        for collector in profile["collectors"]
        if collector["attribution"] is not None
        for hook in collector["attribution"]["hooks"]
    }
    _require(
        "pytest_generate_tests" in collector_hooks,
        "the deterministic JSON consumer did not read collector hooks",
        result,
    )
    _require(
        any(
            hook["name"] == "pytest_collection_modifyitems"
            for hook in profile["collection_hooks"]
        ),
        "the deterministic JSON consumer did not read collection hooks",
        result,
    )
    _require(
        any(
            collector["nodeid"] == "hostile_żółw_$(echo).case"
            for collector in profile["collectors"]
        ),
        "the installed JSON profile did not preserve the hostile node ID as data",
        result,
    )
    _require(
        "collector attribution" not in result.stdout
        and "Total collection:" not in result.stdout,
        "JSON mode also emitted the text profile",
        result,
    )
    if item_listing:
        _require(
            "test_runs" in result.stdout or "1 passed" in result.stdout,
            "JSON run did not retain execution or explicit collect-only output",
            result,
        )
    else:
        _require(
            "test_sample.py::test_runs" not in result.stdout,
            "profile-only JSON printed the routine collected-node listing",
            result,
        )


def _check_unprofiled_run(result: subprocess.CompletedProcess[str]) -> None:
    output = result.stdout
    _require(
        "collect profile" not in output,
        "the installed plugin printed a report without its option",
        result,
    )
    _require("TEST EXECUTED" in output, "the unprofiled test did not run", result)
    _require("1 passed" in output, "the unprofiled test did not pass", result)


def _require(
    condition: bool,
    message: str,
    result: subprocess.CompletedProcess[str],
) -> None:
    if condition:
        return

    raise RuntimeError(
        f"{message}\n\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
