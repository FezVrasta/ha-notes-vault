# Brand assets

> **The icon here is a placeholder — replace it before the first release.** It ships
> because the HACS CI job fails outright on a missing `icon.png`, and a new repository
> should not start red. It is a generic chip glyph; it says nothing about your device.

Home Assistant serves these. Since **2026.3** a custom integration ships its own brand
images in a `brand/` folder inside the integration, and Home Assistant exposes them at
`/api/brands/integration/<domain>/`, taking priority over the brands CDN. The central
[home-assistant/brands](https://github.com/home-assistant/brands) repository no longer
accepts custom integrations, so there is nothing to submit anywhere — the files here are
the whole story.

See the [Brands Proxy API announcement](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/).

On Home Assistant older than 2026.3 the integration shows the generic puzzle-piece icon.
Nothing breaks.

## What to put here

| File | Size | Used for |
| --- | --- | --- |
| `icon.png` | 256×256 | The integration tile, the device page, the "add integration" list |
| `icon@2x.png` | 512×512 | The same, on a retina display |
| `logo.png` | ≤256 tall | The wordmark, shown in the config flow header when present |
| `logo@2x.png` | ≤512 tall | The same, on a retina display |
| `dark_icon.png` | 256×256 | Optional: a variant for dark themes |

`icon.png` must be square and transparent-safe on both themes. The usual way to get that
without shipping a `dark_` variant is a self-contained tile — an app-icon-style squircle
with its own background — rather than a bare glyph.

## Regenerating

`icon.svg` is generated, not hand-edited. Change `tools/make_icon.py` and re-run it — it
writes the source and renders every PNG:

```sh
python tools/make_icon.py
```

To render an SVG you drew elsewhere, skip the generator and use:

```sh
python tools/render_brand.py custom_components/<domain>/brand/icon.svg
```

Both need `rsvg-convert` (`brew install librsvg`).

## The tile shape

A **squircle** — a superellipse with exponent 5, so the curvature eases into the straight
edges rather than meeting them at a tangent the way a rounded rectangle's circular arcs
do. That is the difference between an iOS app icon and a CSS `border-radius`, and it is
visible at 256px once you know to look. `squircle()` in `tools/make_icon.py` emits the
path; it takes the exponent as an argument if you want a boxier or rounder tile.

It is drawn full-bleed, inscribed in the whole 1024 artboard rather than inset, because
that is how an app icon fills its mask.

## Two things that will bite you

**`feComponentTransfer` renders with a visible rectangular seam in librsvg**, which is
what Home Assistant's tooling and most Linux boxes use. If you need a glow, stack two
blurred passes instead — it looks the same and renders consistently.

**Blur radii live in the coordinate space of whatever transform encloses them.** Writing
the pixel radius you want directly, inside a group that is scaled up, gives a blur that
overruns its filter region and leaves a hard rectangular clip edge.
