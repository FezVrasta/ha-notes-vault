---
name: readme-style
description: >-
  The house style for a Home Assistant integration README and its release notes — the
  layout, the badges, the voice, and what belongs above the fold. Use when writing or
  rewriting README.md, adding screenshots, or drafting release notes for one of these
  repositories.
---

# README style

The README is the product page. HACS renders it inside Home Assistant, so it is what
someone reads while deciding whether to install — before any documentation, and often
instead of it.

## Layout, in order

```markdown
<p align="center">
  <img src="custom_components/<domain>/brand/icon.png" width="128" alt="">
</p>

<h1 align="center">Trakt Scrobbler for Home Assistant</h1>

<p align="center">
  One line saying what it does for the reader.<br>
  A second line for the thing that makes it different.
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=FezVrasta&repository=<repo>&category=integration">
    <img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open this repository in HACS">
  </a>
</p>

<p align="center">
  <img src="https://github.com/FezVrasta/<repo>/actions/workflows/ci.yml/badge.svg" alt="CI">
  <img src="https://img.shields.io/badge/HACS-custom-41BDF5.svg" alt="HACS custom repository">
  <img src="https://img.shields.io/badge/Home%20Assistant-2026.8%2B-41BDF5" alt="Home Assistant">
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT">
</p>

---
```

The my.home-assistant.io badge is the important one — it adds the repo to the reader's
own HACS in two clicks. It is not the same thing as the shields.io HACS badge, which is
decoration. Include both, in that order.

Then, still above the fold: two or three sentences on the problem, in the reader's terms.
What they have, what it doesn't do today, what this changes. Not "this integration
provides an interface to…".

Then `## What you get` — a table of entities, or a two-up screenshot table. Then
`## Install`, `## Options`, and the specifics.

Add `status-alpha` and `config-no%20YAML` badges when they are true. A `Home Assistant
2026.8+` badge should match the `homeassistant` floor in `hacs.json`; if you bump one,
bump the other.

## Screenshots

Two side by side, in a `<table>`, with an `<em>` caption under each, beats one big one.
Put them in `docs/images/` and reference them relatively — HACS renders the README from
the repository, so relative paths work; absolute `raw.githubusercontent.com` URLs are
only needed for a `<picture>` with light and dark sources.

Write real `alt` text describing what is in the shot. It is what someone gets on a slow
connection, and it is what a search engine indexes.

## Voice

Plain, direct, second person. Short declarative sentences. Say what it does and what it
does not; a stated limitation up front ("**It can't start a coffee.** Vertuo machines
read a barcode on the capsule…") earns more trust than an omitted one and prevents the
issue being filed as a bug.

Avoid: "seamlessly", "powerful", "simply", "leverage", "robust", exclamation marks, and
any sentence that would survive being deleted. British spelling ("behaviour",
"authorise", "colour"), en dashes for ranges — but **"license"**, spelled the American
way, because it matches the `LICENSE` file and every SPDX identifier.

## What not to put in the README

Architecture, protocol details, and reverse-engineering notes go in `docs/` —
`ARCHITECTURE.md`, `PROTOCOL.md`, `DESIGN.md` — and get linked from the bottom. The
README stays the thing a user reads; `docs/` is what a contributor reads.
