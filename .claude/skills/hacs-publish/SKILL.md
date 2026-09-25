---
name: hacs-publish
description: >-
  Getting a custom integration installable — the HACS custom-repository route, the
  requirements the HACS action checks, submitting to the HACS default list, and the
  route to upstreaming into Home Assistant core. Use when the HACS CI job fails, when
  asked how users install this, or when considering listing it publicly.
---

# Publishing

## How people install it today

As a **custom repository** in HACS: HACS → ⋮ → Custom repositories → the repo URL,
category *Integration*. The `my.home-assistant.io` badge in the README does this in two
clicks, which is why it belongs at the top.

HACS then offers each GitHub **release** as a version. There is no separate publish step —
see `.claude/skills/cut-release`.

## What the HACS action checks

The `hacs` CI job fails on repository metadata as often as on code. It requires:

- A repository **description**, and **topics** — at minimum `home-assistant`. Set both:
  ```bash
  gh repo edit --description "…" \
               --add-topic home-assistant --add-topic hacs \
               --add-topic home-assistant-custom-component
  ```
- `hacs.json` at the root with `name`, and `content_in_root: false` for the
  `custom_components/<domain>/` layout.
- Exactly one directory under `custom_components/`, containing a valid `manifest.json`.
- A `README.md`.
- At least one published release (for the default-list check; the plain action tolerates
  none).

`homeassistant` in `hacs.json` is a *floor*: HACS hides the integration from anyone
running older. Set it to the oldest version actually tested, not the newest available —
and keep it in step with the pin in `requirements-test.txt`.

## Getting into the HACS default list

Optional, and a slow queue. It means users find it by searching HACS rather than pasting
a URL. Requirements beyond the above: the repository must not be a fork, must have a
description and topics, must have a release, and must pass the action. Submit a PR to
[hacs/default](https://github.com/hacs/default) adding `owner/repo` to `integration`.

Most of these projects work fine as custom repositories indefinitely. Do it when the
project is stable and you want the discovery, not before.

## Upstreaming into Home Assistant core

A different and much longer road. The parts to know before starting:

- **The protocol code must move out** into its own PyPI package. Core integrations are
  not allowed to carry their own device library. This is why `api.py` in this template is
  free of Home Assistant imports — that is the seam.
- The manifest gains a `quality_scale` and must meet the tier's checklist:
  strings for everything, full test coverage of the config flow, discovery, diagnostics,
  reauth.
- Brand images *do* go to [home-assistant/brands](https://github.com/home-assistant/brands)
  for a core integration — the "custom integrations not accepted" rule is only about
  custom ones.
- Documentation is a separate PR to
  [home-assistant.io](https://github.com/home-assistant/home-assistant.io), and the two
  PRs reference each other.

Expect several rounds of review. Keep the custom repository alive during it; users are
already running it.
