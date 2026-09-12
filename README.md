# pytest-collect-profile

Find what makes pytest collection slow.

`pytest-collect-profile` is a pytest plugin that reports the slowest collector
operations and the total collection time before tests begin to run. It measures
pytest's collection model directly, including custom collectors, rather than
guessing from file layout.

## Installation

The first release is still being prepared. Once it is published on PyPI, install
it in the environment where pytest runs:

```bash
python -m pip install pytest-collect-profile
```

To try the current source checkout instead:

```bash
python -m pip install .
```

## Quick start

Run the normal test suite with collection profiling enabled:

```bash
pytest --collect-profile
```

To inspect collection without executing tests, combine the plugin flag with
pytest's existing `--collect-only` option:

```bash
pytest --collect-profile --collect-only
```

`--collect-profile` does not imply `--collect-only`; without the latter, pytest
continues to execute the selected tests normally.

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

- The plugin is silent unless `--collect-profile` is present.
- The report appears after collection and before test execution.
- Selection, execution, collection errors, test failures, and exit statuses
  remain pytest's responsibility.
- Timings and records exist only for the current pytest process; the plugin
  creates no history, cache, network request, or external service.

## Compatibility

`pytest-collect-profile` requires Python 3.10 or newer and pytest 8.0 or newer.
Version `0.1.0` targets Linux, macOS, and Windows.

The project's GitHub Actions matrix has passed for Python 3.10 through 3.14,
representative pytest 8.x and 9.x releases, and Linux, macOS, and Windows.
Version `0.1.0` has not yet been published to PyPI.

## Limitations

Version `0.1.0` profiles collection only. It does not profile test execution,
fixtures, functions, or call stacks; explain the cause of slowness; produce JSON,
HTML, or flamegraphs; store history; compare runs; enforce thresholds; or offer
configurable ranking and filters. It provides no special xdist guarantees.

See the
[contribution guide](https://github.com/janmrow/pytest-collect-profile/blob/main/CONTRIBUTING.md)
for contribution guidance. This project is available under the terms of the
[MIT License](https://github.com/janmrow/pytest-collect-profile/blob/main/LICENSE).
