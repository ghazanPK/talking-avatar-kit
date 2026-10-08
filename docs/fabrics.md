# Fabric and pattern library

Tileable, tintable fabric and pattern textures for garments, in `assets/fabrics/` and `assets/patterns/` (CC BY 4.0, see [../CREDITS.md](../CREDITS.md)).

## Fabrics

`assets/fabrics/fabrics.json` lists 15 fabrics: canvas, corduroy, cotton jersey, cotton poplin, denim twill, fleece, knit, smooth leather, linen, rubber, satin, scrubs twill, sport mesh, suede and wool suiting. Each folder `assets/fabrics/<name>/` holds:

| File | Content |
|---|---|
| `albedo.jpg` | 1024 px greyscale albedo, neutral (no colour cast), mean sRGB value 0.80 |
| `normal.png` | 512 px tangent-space normal map, OpenGL / glTF convention (+X right, +Y up the image), derived from the fabric's height at its real size |
| `roughness.png` | optional, 512 px roughness variation around 0.5; add `(value - 0.5) * amount` to the fabric's `roughness` |

Every entry gives `patch_cm` (the real width of one tile), a default `roughness` and `sheen`, `albedo_mean_linear` and the sha256 of its sources and outputs.

**Tiling at real size:** for a garment whose UV layout spans `m` metres per UV unit (surface area over UV area, square-rooted), repeat the tile `m / (patch_cm / 100)` times per UV unit.

**Tinting:** colour = tint (linear RGB) x albedo / `albedo_mean_linear`, so the tint is the fabric's average colour. Multiply by the garment's own shading (ambient occlusion) if it has one.

**three.js:** load the textures with `flipY = false` and `RepeatWrapping` so they line up with glTF UVs; set `colorSpace = SRGBColorSpace` on the albedo only. Without vertex tangents, use `normalScale = (s, -s)` as the glTF loader does.

## Patterns

`assets/patterns/patterns.json` lists five 1024 px pattern masks with their real tile size (`patch_cm`, width and height):

| Pattern | Kind | Colours |
|---|---|---|
| `stripes_pinstripe`, `stripes_breton`, `houndstooth` | `mask` | white areas = colour A, black areas = colour B |
| `gingham`, `tartan_plaid` | `rgb` | red, green and blue areas = colours A, B and C |

Final colour = pattern colour x fabric albedo detail, so any pattern works with any fabric. Edges are anti-aliased; for `rgb` masks divide by `r + g + b` before mixing.

## Rebuilding (maintainers)

The library is committed; you never need to rebuild it to use it. To process new source swatches (`<fabric>_albedo.png`, `<fabric>_height.png`, optional `<fabric>_roughness.png` and `<pattern>.png`, any square size) with NumPy and Pillow installed:

```sh
python -m tak.pipeline.fabrics --src path/to/swatches [--only denim_twill,gingham]
```

The tool converts every map to luminance, removes low-frequency shading, takes the weave structure of the albedo from the height map (separately generated albedo and height images do not register pixel for pixel), repairs the tile edges once for all maps by offsetting the tile and quilting the moved seams along minimum-error cuts, normalises the albedo brightness, resamples periodically and derives the normal map. Pattern masks are snapped to their exact palette, cropped to a whole number of pattern periods and resampled with soft edges. Fabrics and patterns not in the tool's recipe table are ignored; the run is deterministic.
