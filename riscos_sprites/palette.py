"""
Decoding of RISC OS sprite palettes.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class PaletteEntry:
    """
    A single decoded palette entry (two RISC OS palette words).
    """

    index: int
    word1: int
    word2: int
    red: int
    green: int
    blue: int
    words_match: bool

    @classmethod
    def decode_all(cls, data: bytes, palette_offset: int, palette_bytes: int) -> tuple["PaletteEntry", ...]:
        entries: list[PaletteEntry] = []
        for index in range(palette_bytes // 8):
            word1, word2 = struct.unpack_from("<II", data, palette_offset + (index * 8))
            entries.append(
                cls(
                    index=index,
                    word1=word1,
                    word2=word2,
                    red=(word1 >> 8) & 0xFF,
                    green=(word1 >> 16) & 0xFF,
                    blue=(word1 >> 24) & 0xFF,
                    words_match=word1 == word2,
                )
            )
        return tuple(entries)

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "word1": self.word1,
            "word2": self.word2,
            "rgb": {
                "red": self.red,
                "green": self.green,
                "blue": self.blue,
            },
            "words_match": self.words_match,
        }

    @classmethod
    def from_word(cls, index: int, word: int) -> "PaletteEntry":
        return cls(
            index=index,
            word1=word,
            word2=word,
            red=(word >> 8) & 0xFF,
            green=(word >> 16) & 0xFF,
            blue=(word >> 24) & 0xFF,
            words_match=True,
        )


# Default palettes used when a sprite has no palette of its own, ported
# from the RISC OS ConvertPNG module's c/palette.
DEFAULT_PALETTE_WORDS: dict[int, tuple[int, ...]] = {
    1: (0xFFFFFF00, 0x00000000),
    2: (0xFFFFFF00, 0xBBBBBB00, 0x77777700, 0x00000000),
    4: (
        0xFFFFFF00, 0xDDDDDD00, 0xBBBBBB00, 0x99999900,
        0x77777700, 0x55555500, 0x33333300, 0x00000000,
        0x99440000, 0x00EEEE00, 0x00CC0000, 0x0000DD00,
        0xBBEEEE00, 0x00885500, 0x00BBFF00, 0xFFBB0000,
    ),
    8: (
        0x00000000, 0x11111100, 0x22222200, 0x33333300,
        0x00004400, 0x11115500, 0x22226600, 0x33337700,
        0x44000000, 0x55111100, 0x66222200, 0x77333300,
        0x44004400, 0x55115500, 0x66226600, 0x77337700,
        0x00008800, 0x11119900, 0x2222AA00, 0x3333BB00,
        0x0000CC00, 0x1111DD00, 0x2222EE00, 0x3333FF00,
        0x44008800, 0x55119900, 0x6622AA00, 0x7733BB00,
        0x4400CC00, 0x5511DD00, 0x6622EE00, 0x7733FF00,
        0x00440000, 0x11551100, 0x22662200, 0x33773300,
        0x00444400, 0x11555500, 0x22666600, 0x33777700,
        0x44440000, 0x55551100, 0x66662200, 0x77773300,
        0x44444400, 0x55555500, 0x66666600, 0x77777700,
        0x00448800, 0x11559900, 0x2266AA00, 0x3377BB00,
        0x0044CC00, 0x1155DD00, 0x2266EE00, 0x3377FF00,
        0x44448800, 0x55559900, 0x6666AA00, 0x7777BB00,
        0x4444CC00, 0x5555DD00, 0x6666EE00, 0x7777FF00,
        0x00880000, 0x11991100, 0x22AA2200, 0x33BB3300,
        0x00884400, 0x11995500, 0x22AA6600, 0x33BB7700,
        0x44880000, 0x55991100, 0x66AA2200, 0x77BB3300,
        0x44884400, 0x55995500, 0x66AA6600, 0x77BB7700,
        0x00888800, 0x11999900, 0x22AAAA00, 0x33BBBB00,
        0x0088CC00, 0x1199DD00, 0x22AAEE00, 0x33BBFF00,
        0x44888800, 0x55999900, 0x66AAAA00, 0x77BBBB00,
        0x4488CC00, 0x5599DD00, 0x66AAEE00, 0x77BBFF00,
        0x00CC0000, 0x11DD1100, 0x22EE2200, 0x33FF3300,
        0x00CC4400, 0x11DD5500, 0x22EE6600, 0x33FF7700,
        0x44CC0000, 0x55DD1100, 0x66EE2200, 0x77FF3300,
        0x44CC4400, 0x55DD5500, 0x66EE6600, 0x77FF7700,
        0x00CC8800, 0x11DD9900, 0x22EEAA00, 0x33FFBB00,
        0x00CCCC00, 0x11DDDD00, 0x22EEEE00, 0x33FFFF00,
        0x44CC8800, 0x55DD9900, 0x66EEAA00, 0x77FFBB00,
        0x44CCCC00, 0x55DDDD00, 0x66EEEE00, 0x77FFFF00,
        0x88000000, 0x99111100, 0xAA222200, 0xBB333300,
        0x88004400, 0x99115500, 0xAA226600, 0xBB337700,
        0xCC000000, 0xDD111100, 0xEE222200, 0xFF333300,
        0xCC004400, 0xDD115500, 0xEE226600, 0xFF337700,
        0x88008800, 0x99119900, 0xAA22AA00, 0xBB33BB00,
        0x8800CC00, 0x9911DD00, 0xAA22EE00, 0xBB33FF00,
        0xCC008800, 0xDD119900, 0xEE22AA00, 0xFF33BB00,
        0xCC00CC00, 0xDD11DD00, 0xEE22EE00, 0xFF33FF00,
        0x88440000, 0x99551100, 0xAA662200, 0xBB773300,
        0x88444400, 0x99555500, 0xAA666600, 0xBB777700,
        0xCC440000, 0xDD551100, 0xEE662200, 0xFF773300,
        0xCC444400, 0xDD555500, 0xEE666600, 0xFF777700,
        0x88448800, 0x99559900, 0xAA66AA00, 0xBB77BB00,
        0x8844CC00, 0x9955DD00, 0xAA66EE00, 0xBB77FF00,
        0xCC448800, 0xDD559900, 0xEE66AA00, 0xFF77BB00,
        0xCC44CC00, 0xDD55DD00, 0xEE66EE00, 0xFF77FF00,
        0x88880000, 0x99991100, 0xAAAA2200, 0xBBBB3300,
        0x88884400, 0x99995500, 0xAAAA6600, 0xBBBB7700,
        0xCC880000, 0xDD991100, 0xEEAA2200, 0xFFBB3300,
        0xCC884400, 0xDD995500, 0xEEAA6600, 0xFFBB7700,
        0x88888800, 0x99999900, 0xAAAAAA00, 0xBBBBBB00,
        0x8888CC00, 0x9999DD00, 0xAAAAEE00, 0xBBBBFF00,
        0xCC888800, 0xDD999900, 0xEEAAAA00, 0xFFBBBB00,
        0xCC88CC00, 0xDD99DD00, 0xEEAAEE00, 0xFFBBFF00,
        0x88CC0000, 0x99DD1100, 0xAAEE2200, 0xBBFF3300,
        0x88CC4400, 0x99DD5500, 0xAAEE6600, 0xBBFF7700,
        0xCCCC0000, 0xDDDD1100, 0xEEEE2200, 0xFFFF3300,
        0xCCCC4400, 0xDDDD5500, 0xEEEE6600, 0xFFFF7700,
        0x88CC8800, 0x99DD9900, 0xAAEEAA00, 0xBBFFBB00,
        0x88CCCC00, 0x99DDDD00, 0xAAEEEE00, 0xBBFFFF00,
        0xCCCC8800, 0xDDDD9900, 0xEEEEAA00, 0xFFFFBB00,
        0xCCCCCC00, 0xDDDDDD00, 0xEEEEEE00, 0xFFFFFF00,
    ),
}


def default_palette_entries(bpp: int) -> tuple[PaletteEntry, ...]:
    """
    The default palette for `bpp` bits per pixel, or an empty tuple
    if there is no default palette for that depth.
    """
    words = DEFAULT_PALETTE_WORDS.get(bpp)
    if not words:
        return ()
    return tuple(PaletteEntry.from_word(index, word) for index, word in enumerate(words))


# Old-format 8bpp modes with a 64-entry palette store only the base
# (untinted) colours; the top two pixel bits select a hardware "tint"
# that is added on top of the base colour rather than looked up, adding
# 136 to green when bit 6 is set and 136 to blue when bit 7 is set
# (each clamped to 255). This lets a 64-entry palette expand to the
# full 256 colours an 8bpp pixel byte can address.
_TINT_STEP = 136


def expand_64_entry_palette(entries: tuple[PaletteEntry, ...]) -> tuple[PaletteEntry, ...]:
    """
    Expand a 64-entry old-format 8bpp sprite palette to the full 256
    entries a pixel byte can index, applying the standard tint formula
    to the top two (tint) bits of the pixel value.
    """
    expanded: list[PaletteEntry] = list(entries)
    for tint in (1, 2, 3):
        green_bump = _TINT_STEP if tint & 1 else 0
        blue_bump = _TINT_STEP if tint & 2 else 0
        for base in entries:
            index = tint * 64 + base.index
            expanded.append(
                PaletteEntry(
                    index=index,
                    word1=base.word1,
                    word2=base.word2,
                    red=base.red,
                    green=min(255, base.green + green_bump),
                    blue=min(255, base.blue + blue_bump),
                    words_match=base.words_match,
                )
            )
    return tuple(expanded)
