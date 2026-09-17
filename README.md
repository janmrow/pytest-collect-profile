# pytest-collect-profile

[![PyPI version](https://img.shields.io/pypi/v/pytest-collect-profile)](https://pypi.org/project/pytest-collect-profile/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://pypi.org/project/pytest-collect-profile/)
[![CI](https://github.com/janmrow/pytest-collect-profile/actions/workflows/ci.yml/badge.svg)](https://github.com/janmrow/pytest-collect-profile/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/janmrow/pytest-collect-profile/blob/main/LICENSE)

Find what makes pytest collection slow.

`pytest-collect-profile` ranks pytest collector operations, attributes time to observed pytest hooks, and reports the complete collection time. It measures the suite pytest actually sees, including custom collectors.

## Installation

```bash
python -m pip install pytest-collect-profile
```

## Profile collection only (recommended)

```bash
pytest --collect-profile-only
```

Pytest collects and selects tests, the plugin prints one bounded report, and no test setup, call, or teardown runs. The usual collected-node listing is omitted.

```text
====================== collect profile ======================
time      collector   node
1.421s    Module      tests/integration/test_api.py
0.612s    Class       tests/test_users.py::TestUsers

collector attribution
1. Module tests/integration/test_api.py
   direct fan-out: 842 children | 842 items
   1.100s | 1 call | pytest_generate_tests
   0.050s | 7 calls | pytest_pycollect_makeitem
   0.020s | 842 calls | pytest_make_parametrize_id
   0.010s | 4 calls | other observed hooks
   0.100s | nested collectors
   0.141s | outside observed hooks
2. Class tests/test_users.py::TestUsers
   direct fan-out: 12 children | 12 items
   0.200s | 1 call | pytest_generate_tests
   0.412s | outside observed hooks

collection-level hooks
   0.300s | 1 call | pytest_collection_modifyitems

Total collection: 2.340s | 854 items
```

### Reading the report

- The slowest collector is first. The report contains at most 10 collector rows.
- Attribution is shown for the first 3 rows, with at most 3 named hooks. Additional hooks are combined as `other observed hooks` without losing their total time or call count.
- A hook duration covers the complete hook call, excluding time in nested hook calls. It does not time or blame individual hook implementations or plugins.
- `direct fan-out` counts immediate children and items, not all descendants.
- `nested collectors` is direct nested collector time and appears only when nonzero.
- `outside observed hooks` is the measured remainder after exclusive hook time and direct nested collector time are subtracted. It is not a claim about the cause.
- Collection-level hooks are reported separately. The total collection time is measured independently, so collector rows are not expected to add up to it.

## Profile collection, then run tests

```bash
pytest --collect-profile
```

This prints the same profile before normal test execution. Add pytest's `--collect-only` or `--co` to either profiling mode when you explicitly want its native collected-node listing.

## JSON for tools

Add `--collect-profile-json` to either profiling mode:

```bash
pytest --collect-profile-only --collect-profile-json
```

The plugin replaces its text report with one compact JSON v1 line. The example below is expanded only for readability; actual output is a single physical line.

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
        "nested_collectors_ns": 100000000,
        "outside_observed_hooks_ns": 221000000
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

The schema is deliberately bounded and complete:

- `schema` is always `pytest-collect-profile`, and `schema_version` is `1`. `profile_complete: true` means the object covers the complete collection phase that ran; it does not mean collection finished without errors. An interrupted collection emits no JSON object.
- `collectors` contains at most 10 ranked entries. Each entry has `rank`, `duration_ns`, `collector_type`, `nodeid`, and `attribution`.
- `attribution` is present for ranks 1–3 and is `null` for later ranks. Its fields are `direct_children`, `direct_items`, `hooks`, `nested_collectors_ns`, and `outside_observed_hooks_ns`.
- Fan-out values are integers or `null` when unavailable. Hook lists are empty arrays when no matching hooks were observed.
- Hook entries contain `name`, `duration_ns`, and `call_count`. Both collector and collection-level hook lists use the same 3-plus-folded-remainder bound as the text report; `other observed hooks` is a synthetic aggregate entry, not an actual hook name.
- All durations, including `outside_observed_hooks_ns`, are unrounded integer nanoseconds. `total_collection_ns` is measured independently, and `item_count` is the selected item count at the reporting boundary.
- The root session keeps its raw empty `nodeid` in JSON; the text report displays it as `<session>`.

Pytest diagnostics and framing remain in the terminal stream, so the complete stdout is not a JSON document. Consumers should locate the line whose `schema` is `pytest-collect-profile` and parse that object. The serialized line is ASCII-only so it remains valid JSON across terminal encodings; parsing restores the original Unicode strings.

If pytest's terminal plugin is disabled, the profiler has no terminal destination and emits neither the text report nor JSON.

The modifier alone is a usage error; combine it with `--collect-profile` or `--collect-profile-only`.

For xdist projects, collect serially when consuming JSON:

```bash
pytest -n0 --collect-profile-only --collect-profile-json
```

Active distributed collection is not aggregated. Profile-only mode rejects it; regular profiling can otherwise produce a controller-local report with `item_count: 0` and no collectors.

## Compatibility and boundaries

The plugin requires Python 3.10 or newer and pytest 8.0 or newer. CI covers Python 3.10 through 3.14 on Linux, macOS, and Windows with representative pytest 8.x and 9.x releases.

Pytest continues to own selection, diagnostics, warnings, verbosity, and exit status. The plugin is silent unless a profiling mode is selected, stores no history or cache, and makes no network requests.

The project profiles collection only. It does not diagnose a root cause, profile test execution, fixtures, functions, or call stacks, or provide file exports, history, comparisons, thresholds, advice, or configurable rankings.

See the [contribution guide](https://github.com/janmrow/pytest-collect-profile/blob/main/CONTRIBUTING.md) for contribution guidance. This project is available under the terms of the [MIT License](https://github.com/janmrow/pytest-collect-profile/blob/main/LICENSE).
