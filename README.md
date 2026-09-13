# pytest-collect-profile

[![PyPI version](https://img.shields.io/pypi/v/pytest-collect-profile)](https://pypi.org/project/pytest-collect-profile/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://pypi.org/project/pytest-collect-profile/)
[![CI](https://github.com/janmrow/pytest-collect-profile/actions/workflows/ci.yml/badge.svg)](https://github.com/janmrow/pytest-collect-profile/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/janmrow/pytest-collect-profile/blob/main/LICENSE)

Find what makes pytest collection slow.

`pytest-collect-profile` is a pytest plugin that reports the slowest collector
operations and the total collection time before tests begin to run. It measures
pytest's collection model directly, including custom collectors, rather than
guessing from file layout.

For a focused diagnostic, use `--collect-profile-only`: it shows the same compact
top-10 profile without running tests or dumping pytest's routine collected-node
list. That keeps terminal and CI logs, copied diagnostics, and coding-agent
context focused on useful collection evidence instead of output proportional to
the size of the suite.

## Installation

Install the plugin in the environment where pytest runs:

```bash
python -m pip install pytest-collect-profile
```

To install from a source checkout instead:

```bash
python -m pip install .
```

## Quick start

Profile collection without listing or running the collected tests:

```bash
pytest --collect-profile-only
```

This is the recommended diagnostic workflow. Pytest performs its normal
collection and selection, while the plugin prints at most 10 collector rows and
the fixed summary.

To profile collection and then run the selected tests normally:

```bash
pytest --collect-profile
```

If you explicitly want pytest's native collected-node listing, combine either
profiling mode with `--collect-only` or its `--co` alias:

```bash
pytest --collect-profile-only --collect-only
```

The explicit pytest option keeps its normal detailed presentation. Both
profiling options still produce one profiler report per run.

## Example

```text
====================== collect profile ======================
time      collector   node
1.421s    Module      tests/integration/test_api.py
0.612s    Class       tests/test_users.py::TestUsers
0.184s    Directory   tests/integration

Total collection: 2.340s | 842 items
```

The banner padding may change with terminal width. The report itself always
uses seconds with three decimal places and shows at most 10 collector operations,
ordered by measured duration. An empty root-session node ID appears as
`<session>`.

Each row measures one collector operation. Collector calls may be nested, so row
times can overlap. `Total collection` is measured separately and includes work
outside collector calls, such as item modification hooks. Do not add the rows or
expect their sum to equal the total.

The report helps locate where collection time is spent. It does not explain why
a collector is slow or guarantee that optimizing one displayed row will reduce
the total by the same amount.

## Behavior

- The plugin is silent unless one of its two profiling options is present.
- The report appears after collection and before test execution.
- `--collect-profile-only` prevents test setup, call, and teardown without
  suppressing pytest warnings, errors, or session outcome information.
- Plugin-owned output stays bounded at 10 collector rows plus fixed framing and
  a summary, regardless of the number of collected items.
- `-q`, `-qq`, and `-v` continue to control pytest-owned framing; verbosity
  alone never re-enables the routine collected-node listing.
- Selection, collection diagnostics, test failures, and exit statuses remain
  pytest's responsibility.
- Timings and records exist only for the current pytest process; the plugin
  creates no history, cache, network request, or external service.

## Compatibility

`pytest-collect-profile` requires Python 3.10 or newer and pytest 8.0 or newer.
Version `0.2.0` targets Linux, macOS, and Windows.

The project's GitHub Actions matrix covers Python 3.10 through 3.14,
representative pytest 8.x and 9.x releases, and Linux, macOS, and Windows.

## Limitations

Version `0.2.0` profiles collection only. It does not profile test execution,
fixtures, functions, or call stacks; explain the cause of slowness; produce JSON,
HTML, or flamegraphs; store history; compare runs; enforce thresholds; or offer
configurable ranking and filters.

With `--collect-profile-only`, pytest-xdist may be installed but must remain
inactive; `-n0` uses the supported serial path. Active distributed profiling is
rejected, and worker-result aggregation is not supported. The existing
`--collect-profile` mode continues to provide no special xdist guarantees.

See the
[contribution guide](https://github.com/janmrow/pytest-collect-profile/blob/main/CONTRIBUTING.md)
for contribution guidance. This project is available under the terms of the
[MIT License](https://github.com/janmrow/pytest-collect-profile/blob/main/LICENSE).
