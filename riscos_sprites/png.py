"""
Convert a decoded RISC OS sprite to a PNG file.

Follows the mask-handling strategy of the RISC OS ConvertPNG module's
``c/reverse``: a masked sprite first tries to find an unused palette
index (indexed sprites) or an unused coarse RGB colour-cube cell
(true-colour/CMYK sprites) to use as a colour-key, only falling back to
promoting the image to a larger palette, true-colour, or a full alpha
channel when no such colour-key is available. A sprite that already
carries a genuine alpha channel (new-format alpha-masked sprites) always
uses that alpha data directly -- there is no promotion decision to make.

Where ConvertPNG works on packed RISC OS bytes and needs bit-twiddling
(``mask_findunused_1248bpp`` etc) to search for an unused value, this
module works from the already-unpacked pixel/mask grids produced by
:mod:`riscos_sprites.pixels`, so the same algorithm is expressed as
plain grid operations.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from .errors import SpriteFormatError
from .pixels import DecodedMask, DecodedPixels
from .sprite import Sprite

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

COLOUR_TYPE_RGB = 2
COLOUR_TYPE_PALETTE = 3
COLOUR_TYPE_RGBA = 6

# ConvertPNG's dpi -> pixels-per-metre scale: (1<<12) / 0.0254, as a
# 12-bit fixed point integer, used with the same `(scale*dpi)>>12 + 1`
# formula it uses.
_DPI_TO_PIXELS_PER_METRE_SCALE = 0x275EB


@dataclass
class PngImage:
    """
    An in-memory description of a PNG image, ready to be encoded.
    """

    width: int
    height: int
    bit_depth: int
    colour_type: int
    rows: list
    palette: list[tuple[int, int, int]] | None = None
    trns_palette: list[int] | None = None
    trns_colour: tuple[int, int, int] | None = None
    dpi: tuple[int, int] | None = None
    sbit: tuple[int, ...] | None = None


def _dpi_to_pixels_per_metre(dpi: int) -> int:
    return ((_DPI_TO_PIXELS_PER_METRE_SCALE * dpi) >> 12) + 1


def _palette_rgb_list(sprite: Sprite, size: int) -> list[tuple[int, int, int]]:
    entries = sprite.effective_palette()
    colours = [(entry.red, entry.green, entry.blue) for entry in entries[:size]]
    while len(colours) < size:
        colours.append((0, 0, 0))
    return colours


def _find_unused_index(size: int, used: set[int]) -> int | None:
    for index in range(size):
        if index not in used:
            return index
    return None


def _find_unused_colour_cell(pixels: DecodedPixels, mask: DecodedMask) -> tuple[int, int, int] | None:
    used = set()
    for pixel_row, mask_row in zip(pixels.rows, mask.rows):
        for (red, green, blue), opaque in zip(pixel_row, mask_row):
            if opaque:
                used.add((red >> 4, green >> 4, blue >> 4))
    for red in range(16):
        for green in range(16):
            for blue in range(16):
                if (red, green, blue) not in used:
                    return (red << 4, green << 4, blue << 4)
    return None


def _build_indexed(sprite: Sprite, pixels: DecodedPixels, mask: DecodedMask | None) -> PngImage:
    bpp = sprite.mode.bpp
    size = 1 << bpp
    palette = _palette_rgb_list(sprite, size)

    if mask is None:
        rows = [list(row) for row in pixels.rows]
        return PngImage(pixels.width, pixels.height, bpp, COLOUR_TYPE_PALETTE, rows, palette=palette)

    if mask.kind == "alpha":
        rows = [
            [(*palette[index], alpha) for index, alpha in zip(pixel_row, mask_row)]
            for pixel_row, mask_row in zip(pixels.rows, mask.rows)
        ]
        return PngImage(pixels.width, pixels.height, 8, COLOUR_TYPE_RGBA, rows)

    # Classic 1bpp mask: transparent pixels always become index 0 in the
    # output; any *visible* pixel whose own index is 0 is remapped to the
    # colour-key index so it doesn't get masked out by mistake.
    used = {
        index
        for pixel_row, mask_row in zip(pixels.rows, mask.rows)
        for index, opaque in zip(pixel_row, mask_row)
        if opaque
    }
    key = _find_unused_index(size, used)

    if key is not None:
        new_palette = list(palette)
        new_palette[key] = palette[0]
        rows = [
            [0 if not opaque else (key if index == 0 else index) for index, opaque in zip(pixel_row, mask_row)]
            for pixel_row, mask_row in zip(pixels.rows, mask.rows)
        ]
        trns = [0] + [255] * (size - 1)
        return PngImage(pixels.width, pixels.height, bpp, COLOUR_TYPE_PALETTE, rows, palette=new_palette, trns_palette=trns)

    if bpp < 8:
        new_bpp = bpp * 2
        new_size = 1 << new_bpp
        new_palette = palette + [(0, 0, 0)] * (new_size - size)
        new_palette[size] = palette[0]
        rows = [
            [0 if not opaque else (size if index == 0 else index) for index, opaque in zip(pixel_row, mask_row)]
            for pixel_row, mask_row in zip(pixels.rows, mask.rows)
        ]
        trns = [0] + [255] * (new_size - 1)
        return PngImage(pixels.width, pixels.height, new_bpp, COLOUR_TYPE_PALETTE, rows, palette=new_palette, trns_palette=trns)

    # 8bpp with every index already in use: no room to grow the palette,
    # give up and promote straight to true colour with an alpha channel.
    rows = [
        [(*palette[index], 255 if opaque else 0) for index, opaque in zip(pixel_row, mask_row)]
        for pixel_row, mask_row in zip(pixels.rows, mask.rows)
    ]
    return PngImage(pixels.width, pixels.height, 8, COLOUR_TYPE_RGBA, rows)


def _build_rgb(sprite: Sprite, pixels: DecodedPixels, mask: DecodedMask | None) -> PngImage:
    if mask is None:
        rows = [list(row) for row in pixels.rows]
        return PngImage(pixels.width, pixels.height, 8, COLOUR_TYPE_RGB, rows)

    if mask.kind == "alpha":
        rows = [
            [(red, green, blue, alpha) for (red, green, blue), alpha in zip(pixel_row, mask_row)]
            for pixel_row, mask_row in zip(pixels.rows, mask.rows)
        ]
        return PngImage(pixels.width, pixels.height, 8, COLOUR_TYPE_RGBA, rows)

    # CMYK sprites never attempt a colour-key search (matching ConvertPNG,
    # which only supports alpha promotion for CMYK); true-colour sprites
    # try one first.
    key = None if sprite.mode.data_format == "CMYK" else _find_unused_colour_cell(pixels, mask)

    if key is not None:
        rows = [
            [pixel if opaque else key for pixel, opaque in zip(pixel_row, mask_row)]
            for pixel_row, mask_row in zip(pixels.rows, mask.rows)
        ]
        return PngImage(pixels.width, pixels.height, 8, COLOUR_TYPE_RGB, rows, trns_colour=key)

    rows = [
        [(red, green, blue, 255 if opaque else 0) for (red, green, blue), opaque in zip(pixel_row, mask_row)]
        for pixel_row, mask_row in zip(pixels.rows, mask.rows)
    ]
    return PngImage(pixels.width, pixels.height, 8, COLOUR_TYPE_RGBA, rows)


def build_png_image(sprite: Sprite) -> PngImage:
    pixels = sprite.decode_pixels()
    mask = sprite.decode_mask()

    if pixels.kind == "indexed":
        image = _build_indexed(sprite, pixels, mask)
    else:
        image = _build_rgb(sprite, pixels, mask)

    if sprite.mode.x_dpi is not None and sprite.mode.y_dpi is not None:
        image.dpi = (
            _dpi_to_pixels_per_metre(sprite.mode.x_dpi),
            _dpi_to_pixels_per_metre(sprite.mode.y_dpi),
        )

    if sprite.mode.bpp == 16:
        image.sbit = (5, 5, 5, 8) if image.colour_type == COLOUR_TYPE_RGBA else (5, 5, 5)

    return image


def _pack_scanline(row, colour_type: int, bit_depth: int) -> bytes:
    if colour_type == COLOUR_TYPE_PALETTE and bit_depth < 8:
        per_byte = 8 // bit_depth
        out = bytearray()
        for start in range(0, len(row), per_byte):
            chunk = row[start : start + per_byte]
            byte = 0
            for position, value in enumerate(chunk):
                shift = 8 - bit_depth * (position + 1)
                byte |= (value & ((1 << bit_depth) - 1)) << shift
            out.append(byte)
        return bytes(out)
    if colour_type == COLOUR_TYPE_PALETTE:
        return bytes(row)
    if colour_type == COLOUR_TYPE_RGB:
        out = bytearray()
        for red, green, blue in row:
            out.extend((red, green, blue))
        return bytes(out)
    if colour_type == COLOUR_TYPE_RGBA:
        out = bytearray()
        for red, green, blue, alpha in row:
            out.extend((red, green, blue, alpha))
        return bytes(out)
    raise SpriteFormatError("unsupported PNG colour type: {0}".format(colour_type))


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def encode_png(image: PngImage) -> bytes:
    parts = [PNG_SIGNATURE]

    ihdr = struct.pack(
        ">IIBBBBB",
        image.width,
        image.height,
        image.bit_depth,
        image.colour_type,
        0,
        0,
        0,
    )
    parts.append(_chunk(b"IHDR", ihdr))

    if image.palette is not None:
        plte = b"".join(struct.pack("BBB", *colour) for colour in image.palette)
        parts.append(_chunk(b"PLTE", plte))

    if image.trns_palette is not None:
        parts.append(_chunk(b"tRNS", bytes(image.trns_palette)))
    elif image.trns_colour is not None:
        parts.append(_chunk(b"tRNS", struct.pack(">HHH", *image.trns_colour)))

    if image.dpi is not None:
        x_ppu, y_ppu = image.dpi
        parts.append(_chunk(b"pHYs", struct.pack(">IIB", x_ppu, y_ppu, 1)))

    if image.sbit is not None:
        parts.append(_chunk(b"sBIT", bytes(image.sbit)))

    parts.append(_chunk(b"tEXt", b"Creator\x00riscos-sprites"))

    raw = bytearray()
    for row in image.rows:
        raw.append(0)  # filter type: None
        raw.extend(_pack_scanline(row, image.colour_type, image.bit_depth))
    parts.append(_chunk(b"IDAT", zlib.compress(bytes(raw), 9)))

    parts.append(_chunk(b"IEND", b""))
    return b"".join(parts)


def raw_scanline_bytes(image: PngImage) -> bytes:
    """*image*'s own pixel/index data as concatenated raw scanlines --
    no PNG per-row filter-type byte, no PNG chunk framing, not
    compressed. For a consumer that wants the decoded raster data
    itself rather than a PNG file (e.g. a PDF Image XObject, which
    wants its own image stream -- typically zlib-compressed via
    /FlateDecode, with no PNG predictor needed since there's no PNG
    framing involved -- built directly from the same width/height/
    bit_depth/colour_type/palette this describes)."""
    raw = bytearray()
    for row in image.rows:
        raw.extend(_pack_scanline(row, image.colour_type, image.bit_depth))
    return bytes(raw)


def sprite_to_png_bytes(sprite: Sprite) -> bytes:
    return encode_png(build_png_image(sprite))


def sprite_to_png_file(sprite: Sprite, path: Path) -> None:
    path.write_bytes(sprite_to_png_bytes(sprite))
