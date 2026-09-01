"""
Regression tests for old-format 8bpp sprites carrying only a 64-entry
palette.

Such sprites (e.g. the "yes"/"no" validation icons found in the
Wimp resources) use the classic RISC OS 8bpp tint scheme: the pixel
byte's low 6 bits index the stored 64-entry base palette, and its top
2 bits select a "tint" that is added on top of the base colour rather
than looked up. Before this was handled, ``effective_palette()``
zero-padded the missing 192 entries, so every pixel with a value of 64
or higher decoded as black instead of its real (tinted) colour.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from riscos_sprites import SpriteFile
from riscos_sprites.palette import default_palette_entries, expand_64_entry_palette
from riscos_sprites.png import build_png_image

ROOT = Path(__file__).resolve().parents[1]


class ExpandSixtyFourEntryPaletteTests(unittest.TestCase):
    def test_first_64_entries_are_unchanged(self) -> None:
        base = default_palette_entries(8)[:64]
        expanded = expand_64_entry_palette(base)
        self.assertEqual(len(expanded), 256)
        self.assertEqual(expanded[:64], base)

    def test_matches_the_standard_256_entry_default_palette(self) -> None:
        # The built-in 256-entry default 8bpp palette is itself just the
        # 64-entry base tinted the same way -- so expanding the base
        # should reproduce it exactly, entry for entry.
        base = default_palette_entries(8)[:64]
        expanded = expand_64_entry_palette(base)
        full_default = default_palette_entries(8)
        for index, (got, want) in enumerate(zip(expanded, full_default)):
            self.assertEqual(
                (got.red, got.green, got.blue),
                (want.red, want.green, want.blue),
                "mismatch at index {0}".format(index),
            )

    def test_tint_bits_add_green_and_blue_with_saturation(self) -> None:
        base = default_palette_entries(8)[:64]
        expanded = expand_64_entry_palette(base)

        # base index 63 is (255, 119, 119); tint bit 0 (green) and bit 1
        # (blue) should each add 136, clamped to 255.
        plain = expanded[63]
        green_tint = expanded[1 * 64 + 63]
        blue_tint = expanded[2 * 64 + 63]
        both_tint = expanded[3 * 64 + 63]

        self.assertEqual((plain.red, plain.green, plain.blue), (255, 119, 119))
        self.assertEqual((green_tint.red, green_tint.green, green_tint.blue), (255, 255, 119))
        self.assertEqual((blue_tint.red, blue_tint.green, blue_tint.blue), (255, 119, 255))
        self.assertEqual((both_tint.red, both_tint.green, both_tint.blue), (255, 255, 255))


class SixtyFourEntryPaletteSpriteTests(unittest.TestCase):
    """Uses a real "yes" validation-icon sprite extracted with a
    non-standard 64-entry palette (fixture: sprites/tinted64,ff9)."""

    def setUp(self) -> None:
        sprite_file = SpriteFile.parse(ROOT.joinpath("sprites", "tinted64,ff9"))
        self.sprite = sprite_file.sprites[0]

    def test_sprite_is_flagged_as_a_non_standard_64_entry_palette(self) -> None:
        self.assertEqual(self.sprite.palette_entries, 64)
        self.assertIn(
            "yes: 64-entry 8bpp palette detected; this is valid but non-standard",
            self.sprite.warnings,
        )

    def test_effective_palette_expands_to_256_entries(self) -> None:
        palette = self.sprite.effective_palette()
        self.assertEqual(len(palette), 256)

    def test_high_pixel_indices_decode_to_tinted_colour_not_black(self) -> None:
        # Pixel value 96 (tint 1, base colour 32) is used for the tick's
        # green fill; with the palette zero-padded instead of tinted it
        # used to come out as black.
        palette = self.sprite.effective_palette()
        pixels = self.sprite.decode_pixels()
        used_indices = {index for row in pixels.rows for index in row}
        self.assertIn(96, used_indices)

        green = palette[96]
        self.assertEqual((green.red, green.green, green.blue), (0, 204, 0))

    def test_rendered_png_is_not_a_solid_black_square(self) -> None:
        image = build_png_image(self.sprite)
        # Palette-indexed rows; resolve through the image's own palette
        # to get at the actual displayed colours.
        seen_colours = {image.palette[index] for row in image.rows for index in row}
        self.assertIn((0, 204, 0), seen_colours)
        self.assertNotEqual(seen_colours, {(0, 0, 0)})


if __name__ == "__main__":
    unittest.main()
