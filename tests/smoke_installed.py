"""Exercise the public workflow from an installed wheel in a fresh environment."""

from __future__ import annotations

import argparse
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
        time.sleep(0.03)
        return []


def pytest_collect_file(file_path, parent):
    if file_path.name == "slow.case":
        return SlowFile.from_parent(parent, path=file_path)
""".lstrip(),
        encoding="utf-8",
    )
    (suite / "slow.case").write_text("content\n", encoding="utf-8")
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
        result.returncode == 0,
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
