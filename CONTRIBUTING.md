# Contributing

Bug reports from real installations are the most useful thing — especially ones with the
diagnostics file attached (integration page → ⋮ → *Download diagnostics*; serials and
credentials are redacted automatically).

## Running the tests

```bash
scripts/setup
scripts/test
```

`scripts/setup` creates `.venv` and installs `pytest-homeassistant-custom-component`,
which packages Home Assistant's own test fixtures — so the suite needs nothing but the
installed package and runs identically here and in CI. It pins the Home Assistant version
the suite exercises; bump it in `requirements-test.txt` to test against a newer one.

`scripts/test` runs everything CI runs except hassfest and the HACS action, which need a
container.

Lint and format use the same configuration Home Assistant core does:

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

## Before opening a pull request

- Tests pass, and new behaviour has a test. One test per way something has broken before
  is worth more than broad coverage.
- If you touched the config flow, `strings.json` changed too — and
  `translations/en.json` is a copy of it. CI diffs them.
- Don't bump `manifest.json`'s `version`. CI sets it from the release tag.
- Don't amend, squash or rebase commits already pushed to the branch; the history is
  meant to be followed during review.
