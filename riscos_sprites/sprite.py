"""
A single decoded RISC OS sprite.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from .errors import SpriteFormatError
from .modes import NEW_SPRITE_TYPES, SpriteMode
from .palette import PaletteEntry, default_palette_entries, expand_64_entry_palette
from .pixels import DecodedMask, DecodedPixels
from .pixels import decode_mask as _decode_mask
from .pixels import decode_pixels as _decode_pixels

SPRITE_HEADER_SIZE = 44


def _read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _compute_width_pixels(
    width_words: int,
    first_bit_used: int,
    last_bit_used: int,
    bits_per_pixel: int | None,
) -> int | None:
    if bits_per_pixel is None or bits_per_pixel <= 0:
        return None

    total_bits = width_words * 32
    used_bits = total_bits - first_bit_used - (31 - last_bit_used)
    if used_bits <= 0 or used_bits % bits_per_pixel != 0:
        return None
    return used_bits // bits_per_pixel


def _unknown_or(value: str, present: object | None) -> str:
    return value if present is not None else "unknown"


def _format_pair(first: int | None, second: int | None) -> str:
    if first is None or second is None:
        return "unknown"
    return "{0} x {1}".format(first, second)


def _format_memory_kb(value: int | None) -> str:
    if value is None:
        return "unknown"
    return "{0}K".format(value)


def _format_hz(value: int | None) -> str:
    if value is None:
        return "unknown"
    return "{0} Hz".format(value)


def _format_monitors(monitors: tuple[int, ...]) -> str:
    if not monitors:
        return "unknown"
    return ", ".join(str(monitor) for monitor in monitors)


@dataclass(frozen=True)
class Sprite:
    """
    A single sprite decoded from a RISC OS sprite file.
    """

    name: str
    file_offset: int
    size_bytes: int
    width_words: int
    height: int
    first_bit_used: int
    last_bit_used: int
    image_offset: int
    mask_offset: int
    image_bytes: int
    mask_bytes: int
    image_data: bytes
    mask_data: bytes
    palette_bytes: int
    palette_entries: int
    palette: tuple[PaletteEntry, ...]
    has_mask: bool
    mode: SpriteMode
    width_pixels: int | None
    warnings: tuple[str, ...]

    @classmethod
    def parse(cls, data: bytes, path: Path, sprite_offset: int) -> "Sprite":
        if sprite_offset + SPRITE_HEADER_SIZE > len(data):
            raise SpriteFormatError(
                "{0} has a truncated sprite header at 0x{1:x}".format(path, sprite_offset)
            )

        next_offset = _read_u32(data, sprite_offset)
        if next_offset < SPRITE_HEADER_SIZE:
            raise SpriteFormatError(
                "{0} has a sprite with invalid size at 0x{1:x}".format(path, sprite_offset)
            )

        sprite_end = sprite_offset + next_offset
        if sprite_end > len(data):
            raise SpriteFormatError("{0} has a sprite that runs past end of file".format(path))

        name = data[sprite_offset + 4 : sprite_offset + 16].split(b"\0", 1)[0].decode("latin-1")
        width_words = _read_u32(data, sprite_offset + 16) + 1
        height = _read_u32(data, sprite_offset + 20) + 1
        first_bit_used = _read_u32(data, sprite_offset + 24)
        last_bit_used = _read_u32(data, sprite_offset + 28)
        image_offset = _read_u32(data, sprite_offset + 32)
        mask_offset = _read_u32(data, sprite_offset + 36)
        raw_mode = _read_u32(data, sprite_offset + 40)
        mode = SpriteMode.decode(raw_mode)

        if image_offset < SPRITE_HEADER_SIZE or image_offset > next_offset:
            raise SpriteFormatError(
                "{0} has a sprite with invalid image offset: {1}".format(path, name)
            )
        if mask_offset < image_offset or mask_offset > next_offset:
            raise SpriteFormatError(
                "{0} has a sprite with invalid mask offset: {1}".format(path, name)
            )

        palette_bytes = image_offset - SPRITE_HEADER_SIZE
        if palette_bytes % 8 != 0:
            raise SpriteFormatError(
                "{0} has a sprite with a malformed palette: {1}".format(path, name)
            )

        palette = PaletteEntry.decode_all(data, sprite_offset + SPRITE_HEADER_SIZE, palette_bytes)
        has_mask = mask_offset != image_offset
        image_bytes = (mask_offset if has_mask else next_offset) - image_offset
        mask_bytes = next_offset - mask_offset if has_mask else 0
        image_data = data[sprite_offset + image_offset : sprite_offset + image_offset + image_bytes]
        mask_data = (
            data[sprite_offset + mask_offset : sprite_offset + mask_offset + mask_bytes]
            if has_mask
            else b""
        )
        width_pixels = _compute_width_pixels(width_words, first_bit_used, last_bit_used, mode.bpp)
        warnings = _validate(
            name=name,
            first_bit_used=first_bit_used,
            last_bit_used=last_bit_used,
            width_words=width_words,
            height=height,
            image_bytes=image_bytes,
            mask_bytes=mask_bytes,
            palette=palette,
            palette_entries=palette_bytes // 8,
            has_mask=has_mask,
            mode=mode,
            width_pixels=width_pixels,
        )

        return cls(
            name=name,
            file_offset=sprite_offset,
            size_bytes=next_offset,
            width_words=width_words,
            height=height,
            first_bit_used=first_bit_used,
            last_bit_used=last_bit_used,
            image_offset=image_offset,
            mask_offset=mask_offset,
            image_bytes=image_bytes,
            mask_bytes=mask_bytes,
            image_data=image_data,
            mask_data=mask_data,
            palette_bytes=palette_bytes,
            palette_entries=palette_bytes // 8,
            palette=palette,
            has_mask=has_mask,
            mode=mode,
            width_pixels=width_pixels,
            warnings=tuple(warnings),
        )

    def effective_palette(self) -> tuple[PaletteEntry, ...]:
        """
        The sprite's own palette, or the standard default palette for
        its bits-per-pixel if it has none of its own.
        """
        if self.palette:
            if self.mode.bpp == 8 and len(self.palette) == 64:
                return expand_64_entry_palette(self.palette)
            return self.palette
        if self.mode.data_format in {"monochrome", "indexed"} and self.mode.bpp is not None:
            return default_palette_entries(self.mode.bpp)
        return ()

    def decode_pixels(self) -> DecodedPixels:
        if self.width_pixels is None:
            raise SpriteFormatError(
                "{0}: cannot decode pixels without a known pixel width".format(self.name)
            )
        if self.mode.bpp is None:
            raise SpriteFormatError(
                "{0}: cannot decode pixels without a known bits-per-pixel".format(self.name)
            )
        if self.mode.data_format is None:
            raise SpriteFormatError(
                "{0}: cannot decode pixels without a known data format".format(self.name)
            )
        return _decode_pixels(
            image_bytes=self.image_data,
            width_words=self.width_words,
            height=self.height,
            first_bit_used=self.first_bit_used,
            width_pixels=self.width_pixels,
            bpp=self.mode.bpp,
            data_format=self.mode.data_format,
        )

    def decode_mask(self) -> DecodedMask | None:
        if not self.has_mask:
            return None
        if self.width_pixels is None:
            raise SpriteFormatError(
                "{0}: cannot decode mask without a known pixel width".format(self.name)
            )
        if self.mode.mask_kind is None:
            raise SpriteFormatError(
                "{0}: cannot decode mask without a known mask kind".format(self.name)
            )
        if self.mode.bpp is None:
            raise SpriteFormatError(
                "{0}: cannot decode mask without a known bits-per-pixel".format(self.name)
            )
        return _decode_mask(
            mask_bytes=self.mask_data,
            height=self.height,
            width_pixels=self.width_pixels,
            first_bit_used=self.first_bit_used,
            mask_kind=self.mode.mask_kind,
            format_name=self.mode.format_name,
            image_bpp=self.mode.bpp,
            image_width_words=self.width_words,
        )

    def summary_mask(self) -> str:
        if not self.has_mask:
            return "none"
        return self.mode.mask_kind or "yes"

    def summary_row(self, verbose: bool = False) -> list[str]:
        row = [
            self.name,
            _unknown_or("{0}x{1}".format(self.width_pixels, self.height), self.width_pixels),
            self.mode.summary_type(),
            _unknown_or(str(self.mode.bpp), self.mode.bpp),
            self.summary_mask(),
            str(self.palette_entries),
        ]
        if verbose:
            row.extend(
                [
                    str(self.image_bytes),
                    str(self.mask_bytes),
                    _unknown_or(self.mode.colour_model, self.mode.colour_model),
                    self.mode.summary_dpi(),
                    self.mode.summary_mode(),
                ]
            )
            return row
        row.extend([self.mode.summary_dpi(), self.mode.summary_mode()])
        return row

    def palette_lines(self, verbose: bool = False) -> list[str]:
        lines = [
            "Palette entries decoded: {0}".format(len(self.palette)),
        ]
        if not self.palette:
            return lines

        lines.append("Palette preview:")
        preview_count = len(self.palette) if verbose else min(len(self.palette), 16)
        for entry in self.palette[:preview_count]:
            lines.append(
                "  "
                "{0:3d}: "
                "rgb=({1:3d},{2:3d},{3:3d}) "
                "word1=0x{4:08x} "
                "word2=0x{5:08x}".format(
                    entry.index, entry.red, entry.green, entry.blue, entry.word1, entry.word2
                )
            )
        if len(self.palette) > preview_count:
            lines.append("  ... {0} more entries omitted".format(len(self.palette) - preview_count))
        return lines

    def warning_lines(self) -> list[str]:
        lines = ["Warnings: {0}".format(len(self.warnings))]
        for warning in self.warnings:
            lines.append("  {0}".format(warning))
        return lines

    def details_lines(self, verbose: bool = False) -> list[str]:
        lines = [
            "Sprite: {0}".format(self.name),
            "File offset: 0x{0:x}".format(self.file_offset),
            "Sprite size: {0} bytes".format(self.size_bytes),
            "Dimensions: {0} x {1} pixels".format(
                _unknown_or(str(self.width_pixels), self.width_pixels), self.height
            ),
            "Width in words: {0}".format(self.width_words),
            "First bit used: {0}".format(self.first_bit_used),
            "Last bit used: {0}".format(self.last_bit_used),
            "Image offset: 0x{0:x}".format(self.image_offset),
            "Mask offset: 0x{0:x}".format(self.mask_offset),
            "Image bytes: {0}".format(self.image_bytes),
            "Mask bytes: {0}".format(self.mask_bytes),
            "Has mask: {0}".format("yes" if self.has_mask else "no"),
            "Palette bytes: {0}".format(self.palette_bytes),
            "Palette entries: {0}".format(self.palette_entries),
            "Mode format: {0}".format(self.mode.format_name),
            "Mode description: {0}".format(self.mode.description),
            "Mode raw value: 0x{0:08x}".format(self.mode.raw_value),
            "Mode number: {0}".format(_unknown_or(str(self.mode.mode_number), self.mode.mode_number)),
            "Base mode number: {0}".format(
                _unknown_or(str(self.mode.base_mode_number), self.mode.base_mode_number)
            ),
            "Shadow mode: {0}".format("yes" if self.mode.shadow_mode else "no"),
            "Sprite type: {0}".format(self.mode.sprite_type),
            "Alpha channel: {0}".format("yes" if self.mode.has_alpha else "no"),
            "Mode kind: {0}".format(_unknown_or(self.mode.kind, self.mode.kind)),
            "Bits per pixel: {0}".format(_unknown_or(str(self.mode.bpp), self.mode.bpp)),
            "Mask kind: {0}".format(_unknown_or(self.mode.mask_kind, self.mode.mask_kind)),
            "Logical colours: {0}".format(
                _unknown_or(str(self.mode.logical_colours), self.mode.logical_colours)
            ),
            "Text resolution: {0}".format(_format_pair(self.mode.text_columns, self.mode.text_rows)),
            "Mode pixel resolution: {0}".format(
                _format_pair(self.mode.pixel_width, self.mode.pixel_height)
            ),
            "Mode OS units: {0}".format(_format_pair(self.mode.os_unit_width, self.mode.os_unit_height)),
            "Mode memory: {0}".format(_format_memory_kb(self.mode.memory_kb)),
            "Mode refresh: {0}".format(_format_hz(self.mode.refresh_hz)),
            "Supported monitors: {0}".format(_format_monitors(self.mode.monitor_types)),
            "Mask bits per pixel: {0}".format(_unknown_or(str(self.mode.mask_bpp), self.mode.mask_bpp)),
            "Horizontal dpi: {0}".format(_unknown_or(str(self.mode.x_dpi), self.mode.x_dpi)),
            "Vertical dpi: {0}".format(_unknown_or(str(self.mode.y_dpi), self.mode.y_dpi)),
            "Data format: {0}".format(_unknown_or(self.mode.data_format, self.mode.data_format)),
            "Colour model: {0}".format(_unknown_or(self.mode.colour_model, self.mode.colour_model)),
        ]
        if self.mode.data_format == "CMYK":
            lines.extend(
                [
                    "CMYK channels: 8 bits each",
                    "CMYK byte order: cyan, magenta, yellow, black",
                ]
            )
        lines.extend(self.palette_lines(verbose=verbose))
        return lines

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "file_offset": self.file_offset,
            "size_bytes": self.size_bytes,
            "width_words": self.width_words,
            "width_pixels": self.width_pixels,
            "height": self.height,
            "first_bit_used": self.first_bit_used,
            "last_bit_used": self.last_bit_used,
            "image_offset": self.image_offset,
            "mask_offset": self.mask_offset,
            "image_bytes": self.image_bytes,
            "mask_bytes": self.mask_bytes,
            "has_mask": self.has_mask,
            "palette_bytes": self.palette_bytes,
            "palette_entries": self.palette_entries,
            "palette": [entry.to_dict() for entry in self.palette],
            "mode": self.mode.to_dict(),
            "warnings": list(self.warnings),
        }


def _validate(
    *,
    name: str,
    width_words: int,
    height: int,
    first_bit_used: int,
    last_bit_used: int,
    image_bytes: int,
    mask_bytes: int,
    palette: tuple[PaletteEntry, ...],
    palette_entries: int,
    has_mask: bool,
    mode: SpriteMode,
    width_pixels: int | None,
) -> list[str]:
    warnings: list[str] = []

    if first_bit_used > 31 or last_bit_used > 31:
        warnings.append("bit usage fields exceed the valid 0..31 range")
    if first_bit_used > last_bit_used:
        warnings.append("first bit used is greater than last bit used")
    if width_pixels is None:
        warnings.append("pixel width could not be derived from width words and mode")

    expected_row_bytes = width_words * 4
    expected_image_bytes = expected_row_bytes * height
    if image_bytes != expected_image_bytes:
        warnings.append(
            "image data is {0} bytes, expected {1} from width/height".format(
                image_bytes, expected_image_bytes
            )
        )

    expected_mask_bytes = 0
    if has_mask:
        if mode.format_name == "old":
            # Old-format masks are stored at the image's own bpp (a whole
            # pixel-sized slot per pixel), reusing its row width exactly.
            expected_mask_bytes = expected_image_bytes
        elif width_pixels is not None and mode.mask_bpp is not None:
            # New-format masks (1bpp classic, or 8bpp alpha) are packed
            # into their own word-aligned rows, independent of the
            # image's row width.
            bits_per_row = width_pixels * mode.mask_bpp
            expected_mask_bytes = (((bits_per_row + 31) // 32) * 4) * height
    if has_mask and mask_bytes != expected_mask_bytes:
        warnings.append(
            "mask data is {0} bytes, expected {1} for this sprite type".format(
                mask_bytes, expected_mask_bytes
            )
        )

    if mode.format_name == "old" and mode.bpp is None:
        warnings.append("old-format mode {0} is not in the known mode table".format(mode.raw_value))
    if mode.format_name == "old" and mode.kind in {"text", "teletext"}:
        warnings.append(
            "old-format mode {0} is a {1} mode, not a graphics mode".format(mode.raw_value, mode.kind)
        )
    if mode.format_name == "new" and mode.sprite_type not in NEW_SPRITE_TYPES:
        warnings.append("new-format sprite type {0} is not recognised".format(mode.sprite_type))

    expected_palette_sizes = mode.expected_palette_entry_counts()
    if palette_entries and expected_palette_sizes and palette_entries not in expected_palette_sizes:
        expected_text = ", ".join(str(size) for size in sorted(expected_palette_sizes))
        warnings.append(
            "palette has {0} entries; expected one of {1}".format(palette_entries, expected_text)
        )

    mismatch_entries = [entry.index for entry in palette if not entry.words_match]
    if mismatch_entries:
        preview = ", ".join(str(index) for index in mismatch_entries[:8])
        if len(mismatch_entries) > 8:
            preview += ", ..."
        warnings.append("palette entry words differ at indexes {0}".format(preview))

    if mode.data_format == "indexed" and mode.bpp == 8 and palette_entries == 64:
        warnings.append("64-entry 8bpp palette detected; this is valid but non-standard")

    if mode.data_format in {"RGB", "CMYK"} and palette_entries:
        warnings.append("true-colour sprite contains palette entries")

    if not has_mask and mode.has_alpha:
        warnings.append("alpha-capable sprite type has no mask data")

    return ["{0}: {1}".format(name, warning) for warning in warnings]
