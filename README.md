# pytest-collect-profile

[![PyPI version](https://img.shields.io/pypi/v/pytest-collect-profile)](https://pypi.org/project/pytest-collect-profile/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://pypi.org/project/pytest-collect-profile/)
[![CI](https://github.com/janmrow/pytest-collect-profile/actions/workflows/ci.yml/badge.svg)](https://github.com/janmrow/pytest-collect-profile/actions/workflows/ci.yml)

Find what makes pytest collection slow.

Pytest taking a long time before the first test starts? `pytest --durations` helps find slow test execution, but it does not explain time spent collecting tests. `pytest-collect-profile` profiles the collection phase, ranking slow collectors and attributing time to observed pytest hooks.

No configuration. Install it, then run:

```bash
python -m pip install pytest-collect-profile
pytest --collect-profile-only
```

> Using pytest-xdist? Profile collection serially with `-n0`.

Example output (abridged):

```text
====================== collect profile ======================
time      collector   node
1.421s    Module      tests/integration/test_api.py
0.612s    Class       tests/test_users.py::TestUsers

collector attribution
1. Module tests/integration/test_api.py
   direct fan-out: 842 children | 842 items
   1.100s | 1 call | pytest_generate_tests
   0.321s | outside observed hooks
2. Class tests/test_users.py::TestUsers
   direct fan-out: 12 children | 12 items
   0.612s | outside observed hooks

collection-level hooks
   0.300s | 1 call | pytest_collection_modifyitems

Total collection: 2.340s | 854 items
```

The first row is the slowest collector. The attribution below the table shows which observed hooks consumed its time. `Total collection` is measured independently, so collector rows are not expected to add up to it.

## What this tells you

The plugin ranks collector operations observed through public pytest hooks, attributes time to observed hook calls, and measures the whole collection phase independently — including custom collectors.

| You see | Check first |
|---|---|
| large `pytest_generate_tests` | test generation and parametrization |
| large `pytest_collection_modifyitems` | hooks and plugins modifying the collected tests |
| large `outside observed hooks` | work inside the collector outside observed hooks; slow imports are one possibility, never the claim |

- The slowest collector is first. The table contains at most 10 rows.
- Attribution detail appears for the first 3 rows only, with at most 3 named hooks per row; the remainder folds into `other observed hooks` without losing time or call counts. Hook time covers the complete hook call excluding nested hook calls, and never times or blames an individual implementation or plugin.
- `direct fan-out` counts immediate children and items produced by that collector, not descendants.
- `nested collectors` is directly nested collector time and appears only when nonzero. `outside observed hooks` is the measured remainder after exclusive hook time and nested collector time are subtracted; it is evidence, not a cause.
- Collection-level hooks ran outside any single collector and are reported separately. The total is the independently measured collection phase, so rows are not expected to sum to it.

## Choose a mode

```bash
pytest --collect-profile-only
```

Profile collection without running tests or listing collected nodes. This is the recommended diagnostic command: pytest still owns selection, diagnostics, the final summary, and exit status.

```bash
pytest --collect-profile
```

Same profile, then normal test execution.

Add pytest's `--collect-only` or `--co` to either mode when you explicitly want its native collected-node listing. With both profiling flags present, profile-only execution semantics win and exactly one profile is emitted.

## Machine-readable output

```bash
pytest --collect-profile-only --collect-profile-json
```

The modifier replaces the text report with one compact JSON v1 line. Pytest diagnostics and framing stay in the terminal stream, so consumers should locate the line whose `schema` is `pytest-collect-profile` and parse that object. The example below is expanded for readability; actual output is a single physical line.

```json
{
  "schema": "pytest-collect-profile",
  "schema_version": 1,
  "profile_complete": true,
  "collectors": [
    {
      "rank": 1,
      "duration_ns": 1421000000,
      "collector_type": "Module",
      "nodeid": "tests/integration/test_api.py",
      "attribution": {
        "direct_children": 842,
        "direct_items": 842,
        "hooks": [
          {
            "name": "pytest_generate_tests",
            "duration_ns": 1100000000,
            "call_count": 1
          }
        ],
        "nested_collectors_ns": 0,
        "outside_observed_hooks_ns": 321000000
      }
    }
  ],
  "collection_hooks": [
    {
      "name": "pytest_collection_modifyitems",
      "duration_ns": 300000000,
      "call_count": 1
    }
  ],
  "total_collection_ns": 2340000000,
  "item_count": 854
}
```

- The object carries the same bounded profile as text: at most 10 ranked collectors, attribution for ranks 1–3 only, the same 3-plus-folded hook bound per scope, integer nanosecond durations, and the selected item count. The root session keeps its raw empty `nodeid` in JSON; the text report displays it as `<session>`.
- `profile_complete: true` means the object covers the collection phase that ran; it does not mean collection succeeded. Preserve pytest's process exit code: the presence of a profile is not a success signal. An interrupted collection emits no JSON object.
- `other observed hooks` is a synthetic aggregate entry, not an actual hook name. Hook entries carry `name`, `duration_ns`, and `call_count`.
- The modifier alone is a usage error; combine it with `--collect-profile` or `--collect-profile-only`. If pytest's terminal plugin is disabled, the profiler has no terminal destination and emits neither the text report nor JSON.
- For xdist projects, consume JSON serially with `-n0`. Active distributed collection is not aggregated: profile-only mode rejects it, and regular profiling can otherwise produce a controller-local report with `item_count: 0` and no collectors.

## Compatibility and known boundaries

- The plugin requires Python 3.10 or newer and pytest 8.0 or newer. CI covers Python 3.10 through 3.14 on Linux, macOS, and Windows with representative pytest 8.x and 9.x releases.
- Pytest continues to own selection, diagnostics, warnings, verbosity, and exit status. The plugin is silent unless a profiling mode is selected, stores no history or cache, and makes no network requests.
- Active distributed xdist collection is unsupported for `--collect-profile-only` and fails clearly before collection with a usage error directing you to `-n0`. Merely having xdist installed, or using `-n0`, follows the normal serial path.

## Focused by design

- The project profiles collection only: not test execution, fixtures, functions, call stacks, imports as a separate category, or total CI cost.
- It reports measured boundaries; it never claims a root cause and never relabels `outside observed hooks`.
- No history, run comparison, thresholds, budgets, advice, file exports, or destination controls.
- No configurable ranking, filters, or per-implementation and per-plugin timing or blame.
- No xdist aggregation.

See the [contribution guide](https://github.com/janmrow/pytest-collect-profile/blob/main/CONTRIBUTING.md) for contribution guidance. This project is available under the terms of the [MIT License](https://github.com/janmrow/pytest-collect-profile/blob/main/LICENSE).
