# pytest-collect-profile

[![PyPI version](https://img.shields.io/pypi/v/pytest-collect-profile)](https://pypi.org/project/pytest-collect-profile/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://pypi.org/project/pytest-collect-profile/)
[![CI](https://github.com/janmrow/pytest-collect-profile/actions/workflows/ci.yml/badge.svg)](https://github.com/janmrow/pytest-collect-profile/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/janmrow/pytest-collect-profile/blob/main/LICENSE)

Find what makes pytest collection slow.

`pytest-collect-profile` shows which collector operations take the most time and
how long collection takes overall. It measures pytest directly, including custom
collectors, so the report matches the suite pytest actually sees.

## Installation

```bash
python -m pip install pytest-collect-profile
```

## Quick start

### Profile collection only — recommended

```bash
pytest --collect-profile-only
```

Start here when you want a diagnosis, not a test run. Pytest collects and selects
the tests, the plugin prints one report, and the run stops. It does not print the
usual list of collected nodes.

Only the 10 slowest collector operations are shown. The output stays useful in a
terminal, a CI log, or coding-agent context even for large suites.

### Profile collection, then run tests

```bash
pytest --collect-profile
```

Use this when you want to see the profile without changing your normal test run.
The selected tests execute after the report is printed.

Need pytest's complete collected-node listing? Add `--collect-only` or `--co` to
either command. An explicit pytest collect-only option keeps its native output.

## Example report

```text
====================== collect profile ======================
time      collector   node
1.421s    Module      tests/integration/test_api.py
0.612s    Class       tests/test_users.py::TestUsers
0.184s    Directory   tests/integration

Total collection: 2.340s | 842 items
```

## Reading the report

- The slowest collector operations appear first, with at most 10 rows.
- `Total collection` measures the complete collection phase separately.
- Collector calls may be nested, so row times can overlap and are not meant to
  add up to the total.
- An empty root-session node ID is shown as `<session>`.

The report points to where collection time is spent. It does not guess why a
collector is slow or promise that changing one row will reduce the total by the
same amount.

## Works with pytest

- The plugin is silent unless one of its two profiling options is present.
- Pytest continues to own selection, diagnostics, warnings, and exit status.
- `-q`, `-qq`, and `-v` keep their normal pytest meaning.
- Timings exist only for the current process. The plugin stores no history or
  cache and makes no network requests.

## Compatibility

`pytest-collect-profile` requires Python 3.10 or newer and pytest 8.0 or newer.
The project targets Linux, macOS, and Windows, with CI coverage across Python
3.10 through 3.14 and representative pytest 8.x and 9.x releases.

### pytest-xdist

For a meaningful collection profile, run xdist projects serially:

```bash
pytest -n0 --collect-profile-only
```

The profile-only mode rejects active distributed execution and points to `-n0`.
The regular `--collect-profile` mode does not aggregate worker results, so `-n0`
is recommended there as well.

## Focused by design

`pytest-collect-profile` does one thing: profile collection. It does not profile
test execution, fixtures, functions, or call stacks. It does not provide
exports, history, run-to-run comparisons, thresholds, or configurable rankings
and filters.

See the
[contribution guide](https://github.com/janmrow/pytest-collect-profile/blob/main/CONTRIBUTING.md)
for contribution guidance. This project is available under the terms of the
[MIT License](https://github.com/janmrow/pytest-collect-profile/blob/main/LICENSE).
