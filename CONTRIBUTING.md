# Contributing

Thanks for your interest in `pytest-collect-profile`. The project has one
purpose: find what makes pytest collection slow. Its only user-facing interface
is `pytest --collect-profile`.

## Scope

Before proposing a change, make sure it:

- helps users find slow pytest collection (not slow tests or general CI costs);
- works through the single `--collect-profile` interface;
- does not change pytest's test selection, execution, or exit status;
- uses public pytest hooks and the standard library where possible.

Changes that add options, configuration, or new subsystems without a clear
product justification are out of scope.

## Workflow

1. Start from the default branch (`main`).
2. Create a short-lived topic branch with one of these prefixes:

   ```text
   feat/<short-slug>    new behavior
   fix/<short-slug>     defect fix
   docs/<short-slug>    documentation only
   test/<short-slug>    tests only
   chore/<short-slug>   tooling, packaging, maintenance
   ```

   Keep the slug short and use lowercase kebab-case, for example
   `fix/slow-module-import`.

3. Keep the branch focused on one logical change.
4. Bring in changes from `main` by rebasing or merging when needed.

## Local checks

Create and activate a virtual environment, then install the project and its
development tools:

```bash
python -m pip install --editable . build "ruff==0.16.6"
```

Run the Python lint, formatting, and test checks before opening a pull request:

```bash
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
```

## Commits

Use Conventional Commit subjects:

```text
feat: rank custom collectors without special casing
fix: keep report silent when the flag is absent
docs: document interpretation of the summary line
test: cover fewer-than-10 collector output
chore: set up minimal packaging
```

- Write the subject in the imperative mood, in lowercase, without a trailing
  period, and keep it to 72 characters or fewer.
- The body is optional. Use it to explain *why*, not *what*, and wrap it at
  about 72 characters.
- Write commits and pull requests in English.

## Releases

Versions follow [SemVer](https://semver.org/) (`MAJOR.MINOR.PATCH`) and each
release is tagged `v<major>.<minor>.<patch>`, e.g. `v0.1.0`.

## Pull requests

Use a Conventional Commit-style pull request title that describes the primary
change, for example `docs: add contribution workflow`.

Briefly explain the purpose of the change, summarize what changed, and record
which checks were run.

Pull requests are squash-merged into `main`. Use the pull request title as the
squash commit subject. Delete the topic branch after merging.

Before opening a pull request:

- Run the project's test suite (and any documented lint/build checks once
  tooling is established).
- Add tests for new behavior. For a defect fix, add the smallest regression
  check.
- Update the documentation the change affects.
- Verify the diff contains no secrets, machine-specific paths, or unrelated
  work.

Keep pull requests small and self-contained.
