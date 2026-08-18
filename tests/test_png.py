from __future__ import annotations

import struct
import unittest
import zlib
from pathlib import Path

from riscos_sprites import SpriteFile
from riscos_sprites.palette import PaletteEntry
from riscos_sprites.png import (
    COLOUR_TYPE_PALETTE,
    COLOUR_TYPE_RGB,
    COLOUR_TYPE_RGBA,
    build_png_image,
    encode_png,
    raw_scanline_bytes,
)
from riscos_sprites.pixels import DecodedMask, DecodedPixels


ROOT = Path(__file__).resolve().parents[1]


def sprite_named(sprite_file: SpriteFile, name: str):
    return next(sprite for sprite in sprite_file.sprites if sprite.name == name)


def read_png_chunks(data: bytes) -> dict[bytes, list[bytes]]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    chunks: dict[bytes, list[bytes]] = {}
    offset = 8
    while offset < len(data):
        (length,) = struct.unpack_from(">I", data, offset)
        tag = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        crc_stored = struct.unpack_from(">I", data, offset + 8 + length)[0]
        crc_actual = zlib.crc32(tag + payload) & 0xFFFFFFFF
        assert crc_stored == crc_actual, f"bad CRC for chunk {tag!r}"
        chunks.setdefault(tag, []).append(payload)
        offset += 12 + length
        if tag == b"IEND":
            break
    return chunks


def decode_png_rows(data: bytes) -> tuple[dict, list[list[int]]]:
    """A minimal, filter-type-0-only PNG decoder, just enough to verify
    our own writer's output round-trips correctly."""
    chunks = read_png_chunks(data)
    width, height, bit_depth, colour_type, _, _, _ = struct.unpack(">IIBBBBB", chunks[b"IHDR"][0])
    raw = zlib.decompress(b"".join(chunks.get(b"IDAT", [])))

    channels = {COLOUR_TYPE_PALETTE: 1, COLOUR_TYPE_RGB: 3, COLOUR_TYPE_RGBA: 4}[colour_type]
    if colour_type == COLOUR_TYPE_PALETTE and bit_depth < 8:
        row_bytes = (width * bit_depth + 7) // 8
    else:
        row_bytes = width * channels

    rows = []
    offset = 0
    for _ in range(height):
        filter_type = raw[offset]
        assert filter_type == 0, "test decoder only supports filter type 0"
        row_data = raw[offset + 1 : offset + 1 + row_bytes]
        offset += 1 + row_bytes

        if colour_type == COLOUR_TYPE_PALETTE and bit_depth < 8:
            per_byte = 8 // bit_depth
            values = []
            for byte in row_data:
                for position in range(per_byte):
                    shift = 8 - bit_depth * (position + 1)
                    values.append((byte >> shift) & ((1 << bit_depth) - 1))
            rows.append(values[:width])
        elif colour_type == COLOUR_TYPE_PALETTE:
            rows.append(list(row_data))
        else:
            pixels = []
            for i in range(0, len(row_data), channels):
                pixels.append(tuple(row_data[i : i + channels]))
            rows.append(pixels)

    info = {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "colour_type": colour_type,
        "palette": chunks.get(b"PLTE"),
        "trns": chunks.get(b"tRNS"),
    }
    return info, rows


class _FakeMode:
    def __init__(self, bpp: int, data_format: str) -> None:
        self.bpp = bpp
        self.data_format = data_format


class _FakeSprite:
    """A minimal Sprite stand-in exposing just what png.py's internal
    _build_indexed/_build_rgb helpers need, for exercising promotion
    branches that aren't reachable from the real sample sprite files."""

    def __init__(self, bpp: int, data_format: str, palette: tuple[PaletteEntry, ...]) -> None:
        self.mode = _FakeMode(bpp, data_format)
        self._palette = palette

    def effective_palette(self) -> tuple[PaletteEntry, ...]:
        return self._palette


def _palette(colours: list[tuple[int, int, int]]) -> tuple[PaletteEntry, ...]:
    return tuple(
        PaletteEntry(index=i, word1=0, word2=0, red=r, green=g, blue=b, words_match=True)
        for i, (r, g, b) in enumerate(colours)
    )


class RealSpriteConversionTests(unittest.TestCase):
    def test_indexed_no_mask_round_trips(self) -> None:
        sprite_file = SpriteFile.parse(ROOT / "sprites" / "basi3p02,ff9")
        sprite = sprite_file.sprites[0]
        png_bytes = encode_png(build_png_image(sprite))
        info, rows = decode_png_rows(png_bytes)

        self.assertEqual((info["width"], info["height"]), (32, 32))
        self.assertEqual(info["colour_type"], COLOUR_TYPE_PALETTE)
        self.assertEqual(info["bit_depth"], 2)
        self.assertIsNone(info["trns"])

        pixels = sprite.decode_pixels()
        self.assertEqual(rows, [list(row) for row in pixels.rows])

    def test_alpha_masked_indexed_sprite_becomes_rgba(self) -> None:
        sprite_file = SpriteFile.parse(ROOT / "sprites" / "manysprites,ff9")
        sprite = sprite_named(sprite_file, "basi4a08")
        png_bytes = encode_png(build_png_image(sprite))
        info, rows = decode_png_rows(png_bytes)

        self.assertEqual(info["colour_type"], COLOUR_TYPE_RGBA)
        mask = sprite.decode_mask()
        self.assertEqual([alpha for _, _, _, alpha in rows[0]], list(mask.rows[0]))

    def test_raw_scanline_bytes_matches_pngs_own_idat_without_filter_bytes(self) -> None:
        # raw_scanline_bytes exists for a non-PNG consumer (e.g. a PDF
        # Image XObject) that wants the same decoded pixel/index bytes
        # a PNG's own IDAT stream carries, minus PNG's own per-row
        # filter-type byte and chunk/zlib framing -- confirm it's
        # exactly that, not some independently-computed value that
        # could quietly drift out of sync with the real PNG encoder.
        sprite_file = SpriteFile.parse(ROOT / "sprites" / "basi3p02,ff9")
        sprite = sprite_file.sprites[0]
        image = build_png_image(sprite)
        png_bytes = encode_png(image)
        info, _ = decode_png_rows(png_bytes)

        raw = raw_scanline_bytes(image)
        bytes_per_row = len(raw) // image.height
        self.assertEqual(len(raw) % image.height, 0)

        # Reconstruct what encode_png's own IDAT payload looks like
        # (filter type 0 prefixed to each row) and confirm it's the
        # bytes raw_scanline_bytes is missing, nothing else.
        chunks = read_png_chunks(png_bytes)
        idat = zlib.decompress(b"".join(chunks[b"IDAT"]))
        stride = bytes_per_row + 1  # +1 for the filter-type byte
        self.assertEqual(len(idat), stride * image.height)
        for row in range(image.height):
            self.assertEqual(idat[row * stride], 0)  # filter type: None
            self.assertEqual(
                idat[row * stride + 1:(row + 1) * stride],
                raw[row * bytes_per_row:(row + 1) * bytes_per_row],
            )

    def test_classic_masked_indexed_sprite_uses_colour_key_when_available(self) -> None:
        sprite_file = SpriteFile.parse(ROOT / "sprites" / "wavytile,ff9")
        sprite = sprite_file.sprites[0]
        image = build_png_image(sprite)
        # tile_1r is a small icon in a 16-colour palette; a free index
        # should always be available, so it should stay palette+tRNS
        # rather than needing to promote.
        self.assertEqual(image.colour_type, COLOUR_TYPE_PALETTE)
        self.assertIsNotNone(image.trns_palette)
        self.assertEqual(image.trns_palette[0], 0)

        png_bytes = encode_png(image)
        info, rows = decode_png_rows(png_bytes)
        mask = sprite.decode_mask()
        pixels = sprite.decode_pixels()
        for row_out, row_pixels, row_mask in zip(rows, pixels.rows, mask.rows):
            for out_index, source_index, opaque in zip(row_out, row_pixels, row_mask):
                if not opaque:
                    self.assertEqual(out_index, 0)
                elif source_index != 0:
                    self.assertEqual(out_index, source_index)

    def test_rgb_no_mask_round_trips(self) -> None:
        sprite_file = SpriteFile.parse(ROOT / "sprites" / "manysprites,ff9")
        sprite = sprite_named(sprite_file, "basi2c08")
        png_bytes = encode_png(build_png_image(sprite))
        info, rows = decode_png_rows(png_bytes)

        self.assertEqual(info["colour_type"], COLOUR_TYPE_RGB)
        pixels = sprite.decode_pixels()
        self.assertEqual(rows, [list(row) for row in pixels.rows])

    def test_alpha_masked_rgb_sprite_becomes_rgba(self) -> None:
        sprite_file = SpriteFile.parse(ROOT / "sprites" / "manysprites,ff9")
        sprite = sprite_named(sprite_file, "basi6a08")
        png_bytes = encode_png(build_png_image(sprite))
        info, _rows = decode_png_rows(png_bytes)
        self.assertEqual(info["colour_type"], COLOUR_TYPE_RGBA)

    def test_16bpp_sprite_gets_sbit_chunk(self) -> None:
        sprite_file = SpriteFile.parse(ROOT / "sprites" / "manysprites,ff9")
        sprite = sprite_named(sprite_file, "32k")
        image = build_png_image(sprite)
        self.assertEqual(image.sbit, (5, 5, 5))


class PromotionChainTests(unittest.TestCase):
    """Exercises the promotion branches that aren't reachable from the
    small real sample sprites, using synthetic pixel/mask grids."""

    def test_promote_palette_when_1bpp_palette_fully_used(self) -> None:
        from riscos_sprites.png import _build_indexed

        sprite = _FakeSprite(1, "monochrome", _palette([(255, 0, 0), (0, 255, 0)]))
        # Both palette indices are used by *visible* pixels, and a third,
        # masked pixel means there's still something to make transparent
        # -- so no free index exists and promotion is forced.
        pixels = DecodedPixels(width=3, height=1, kind="indexed", rows=((0, 1, 0),))
        mask = DecodedMask(width=3, height=1, kind="1bpp", rows=((255, 255, 0),))

        image = _build_indexed(sprite, pixels, mask)
        self.assertEqual(image.colour_type, COLOUR_TYPE_PALETTE)
        self.assertEqual(image.bit_depth, 2)
        self.assertEqual(len(image.palette), 4)
        self.assertEqual(image.palette[2], (255, 0, 0))  # copy of original index 0
        self.assertEqual(image.rows[0][0], 2)  # visible index-0 pixel remapped
        self.assertEqual(image.rows[0][1], 1)  # visible, non-zero index unchanged
        self.assertEqual(image.rows[0][2], 0)  # transparent pixel -> index 0

    def test_promote_true_when_8bpp_palette_fully_used(self) -> None:
        from riscos_sprites.png import _build_indexed

        colours = [(i, i, i) for i in range(256)]
        sprite = _FakeSprite(8, "indexed", _palette(colours))
        # All 256 indices are used by visible pixels; one extra masked
        # pixel means there's still something to make transparent, so
        # no free index exists and promotion is forced.
        pixels = DecodedPixels(width=257, height=1, kind="indexed", rows=(tuple(range(256)) + (0,),))
        mask_row = tuple([255] * 256 + [0])
        mask = DecodedMask(width=257, height=1, kind="1bpp", rows=(mask_row,))

        image = _build_indexed(sprite, pixels, mask)
        self.assertEqual(image.colour_type, COLOUR_TYPE_RGBA)
        self.assertEqual(image.rows[0][1][3], 255)  # visible pixel: alpha 255
        self.assertEqual(image.rows[0][1][:3], (1, 1, 1))
        self.assertEqual(image.rows[0][-1][3], 0)  # masked pixel: alpha 0

    def test_cmyk_always_promotes_to_alpha(self) -> None:
        from riscos_sprites.png import _build_rgb

        sprite = _FakeSprite(32, "CMYK", ())
        # Only two distinct colours used -> a colour-key would normally
        # be found for a plain RGB sprite, but CMYK must skip straight
        # to alpha promotion.
        pixels = DecodedPixels(width=2, height=1, kind="rgb", rows=(((10, 10, 10), (20, 20, 20)),))
        mask = DecodedMask(width=2, height=1, kind="1bpp", rows=((0, 255),))

        image = _build_rgb(sprite, pixels, mask)
        self.assertEqual(image.colour_type, COLOUR_TYPE_RGBA)
        self.assertEqual(image.rows[0][0][3], 0)
        self.assertEqual(image.rows[0][1][3], 255)

    def test_rgb_colour_key_found_stays_rgb(self) -> None:
        from riscos_sprites.png import _build_rgb

        sprite = _FakeSprite(32, "RGB", ())
        pixels = DecodedPixels(width=2, height=1, kind="rgb", rows=(((10, 10, 10), (20, 20, 20)),))
        mask = DecodedMask(width=2, height=1, kind="1bpp", rows=((0, 255),))

        image = _build_rgb(sprite, pixels, mask)
        self.assertEqual(image.colour_type, COLOUR_TYPE_RGB)
        self.assertIsNotNone(image.trns_colour)
        self.assertEqual(image.rows[0][0], image.trns_colour)
        self.assertEqual(image.rows[0][1], (20, 20, 20))

    def test_rgb_promotes_to_alpha_when_colour_cube_exhausted(self) -> None:
        from riscos_sprites.png import _build_rgb

        sprite = _FakeSprite(32, "RGB", ())
        # Fill every one of the 16x16x16 coarse colour-cube cells with a
        # visible pixel, so no colour-key can be found.
        colours = [(r << 4, g << 4, b << 4) for r in range(16) for g in range(16) for b in range(16)]
        colours.append((0, 0, 0))  # one masked-out pixel too
        pixels = DecodedPixels(width=len(colours), height=1, kind="rgb", rows=(tuple(colours),))
        mask_row = tuple([255] * (len(colours) - 1) + [0])
        mask = DecodedMask(width=len(colours), height=1, kind="1bpp", rows=(mask_row,))

        image = _build_rgb(sprite, pixels, mask)
        self.assertEqual(image.colour_type, COLOUR_TYPE_RGBA)
        self.assertEqual(image.rows[0][-1][3], 0)
        self.assertEqual(image.rows[0][0][3], 255)


if __name__ == "__main__":
    unittest.main()
