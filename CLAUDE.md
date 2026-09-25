# Working in this repository

A Home Assistant custom integration, installed through HACS. `custom_components/<domain>/`
is the whole product; everything else supports it.

## Before writing integration code

Read `.claude/skills/ha-integration-conventions`. It carries the rules that are cheap now
and expensive later — unique IDs, entity naming, `entry.runtime_data`, which exception the
coordinator raises for which failure.

Other skills: `integration-tests`, `readme-style`, `brand-assets`, `cut-release`,
`hacs-publish`.

## Invariants

- **`manifest.json`'s `version` belongs to the release commit.** Set it with
  `scripts/bump-version X.Y.Z`, which writes and commits it, *before* creating the
  release. HACS serves the tagged tree, so a version applied after the tag exists is
  a version nobody installs. CI checks the two agree and will fail the release if they
  do not.
- **`strings.json` and `translations/en.json` must be identical.** `strings.json` is the
  source; the copy in `translations/` is what Home Assistant serves. CI diffs them.
- **Unique IDs are permanent.** Changing one orphans every user's history for that
  entity.
- **`api.py` (or whatever the protocol layer is called) imports nothing from Home
  Assistant.** That is what keeps it testable without Home Assistant and liftable into
  its own package.
- The `homeassistant` floor in `hacs.json`, the pin in `requirements-test.txt` and
  `PYTHON_VERSION` in `.github/workflows/ci.yml` move together.

## Checks

```bash
scripts/setup   # once
scripts/test    # ruff, the translations diff, pytest
```

CI additionally runs hassfest and the HACS action. Ruff is configured to mirror Home
Assistant core's own settings, so code here needs no reformatting if it is ever
upstreamed.

## Commits

Present-tense summary line, and a body that says *why* rather than restating the diff —
match the surrounding `git log`. Never amend, squash or rebase a commit already pushed to
a PR branch.
