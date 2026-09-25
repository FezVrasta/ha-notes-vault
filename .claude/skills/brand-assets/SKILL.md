---
name: brand-assets
description: >-
  Icons and logos for a Home Assistant custom integration — where they live since
  2026.3, the filenames and sizes Home Assistant recognises, rendering them from SVG, and
  the librsvg quirks that produce visible seams. Use when adding or changing an
  integration's icon, or when the integration shows the generic puzzle-piece.
---

# Brand assets

## Where they go

Since **Home Assistant 2026.3** a custom integration ships its own brand images in a
`brand/` folder inside the integration, and Home Assistant serves them from
`/api/brands/integration/<domain>/`, taking priority over the brands CDN.

The central [home-assistant/brands](https://github.com/home-assistant/brands) repository
**no longer accepts custom integrations**. There is nothing to submit anywhere; the files
in `brand/` are the whole story. On Home Assistant older than 2026.3 the integration
shows the generic puzzle-piece icon and nothing breaks.

See the [Brands Proxy API announcement](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/).

## The placeholder

A fresh repository from the template ships a generic chip icon. It is there because the
HACS CI job fails outright on a missing `icon.png` — not because it is good enough.
Replace it before the first release; it says nothing about the device and every
integration that ships it looks like every other one.

## Filenames and sizes

| File | Size | Used for |
| --- | --- | --- |
| `icon.png` | 256×256 | The integration tile, the device page, the add-integration list |
| `icon@2x.png` | 512×512 | The same, on a retina display |
| `logo.png` | ≤256 tall | The wordmark, shown in the config flow header when present |
| `logo@2x.png` | ≤512 tall | The same, on a retina display |
| `dark_icon.png` / `dark_logo.png` | as above | Optional dark-theme variants |

`icon.png` must be square. Keep `icon.svg` as the source and render the PNGs, so the
raster files are never hand-edited:

```bash
python tools/make_icon.py                                        # generate + render
python tools/render_brand.py custom_components/<domain>/brand/icon.svg   # render only
```

Both need `rsvg-convert` (`brew install librsvg`). Use it rather than Chromium or
Inkscape — librsvg is what Home Assistant's own tooling uses, and the three disagree
about filters.

## Design

A self-contained tile — an app-icon-style squircle with its own background — reads
correctly on light and dark themes alike, which is how to avoid shipping a `dark_`
variant at all. A bare glyph needs one.

**Use a squircle, and get the squircle right.** A circular rounded rectangle is wrong
for the reason you would guess: curvature jumps from 0 along the edge to 1/r at the arc,
and the join is visible. But the usual fix is also wrong.

A superellipse — `|x|^n + |y|^n = 1`, n around 5 — is what most people mean by
"squircle", and it is *not* the shape iOS uses. It curves continuously everywhere, which
means the edges that should be flat bow outward; against a real app icon it reads as
pillowed. Apple's mask is a rounded rectangle with **continuous curvature**, as produced
by `UIBezierPath(roundedRect:cornerRadius:)`: genuinely straight edges, with the corner
easing curvature in over a longer run than an arc would. Figma exposes the same
construction as "corner smoothing".

Two numbers define it, and `squircle()` in `tools/make_icon.py` implements it:

```python
CORNER_RADIUS_RATIO = 0.2237   # corner radius as a fraction of the width
CORNER_SMOOTHING = 0.6         # Figma's corner-smoothing value
```

The tell, if you are ever unsure which one you are looking at: put the shape on a light
background and sight along an edge. A superellipse bows; the iOS shape is dead straight
until the corner starts.

Draw it full-bleed, inscribed in the whole artboard rather than inset, the way an app
icon fills its mask.

The SVG is build output: change `tools/make_icon.py` and re-run it. Editing generated SVG
by hand and then regenerating it is how icons quietly revert.

## Optical centring

A shape whose mass is off to one side is not centred by centring its bounding box. Render
the artwork, weigh the pixels, and correct part of the way toward the ink centroid —
correcting all the way crowds the silhouette against an edge, because a shape's *extent*
counts perceptually as well as its weight. Roughly 70% of the correction is a good
default. Also lift the artwork a little: the perceived centre of a frame sits slightly
above its geometric centre, so content centred purely by measurement looks sunken.

## Two things that will bite you

**`feComponentTransfer` renders with a visible rectangular seam in librsvg.** If you need
a glow, stack two blurred passes instead — it looks the same and renders consistently
everywhere.

**Blur radii are in the coordinate space of the enclosing transform.** Writing the pixel
radius you want directly, inside a group that is scaled up, gives a blur many times too
large; it overruns its filter region and leaves a hard rectangular clip edge. Convert
explicitly.

(And XML comments cannot contain `--`, which is easy to trip over when writing prose into
a generated SVG.)
