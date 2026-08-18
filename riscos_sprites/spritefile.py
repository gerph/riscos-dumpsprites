"""A parsed RISC OS sprite file, and selections/filters/reports over it."""

from __future__ import annotations

import fnmatch
import json
import struct
from dataclasses import dataclass
from pathlib import Path

from .errors import SpriteFormatError
from .sprite import Sprite

FILE_HEADER_SIZE = 12


def _area_to_file_offset(area_offset: int) -> int:
    if area_offset < 4:
        raise SpriteFormatError(f"invalid area offset 0x{area_offset:x}")
    return area_offset - 4


def _format_extension_words(words: tuple[int, ...]) -> str:
    if not words:
        return "none"
    return ", ".join(f"0x{word:08x}" for word in words)


@dataclass(frozen=True)
class SpriteFile:
    """A parsed RISC OS sprite file."""

    path: Path
    sprite_count: int
    first_sprite_offset: int
    free_offset: int
    extension_words: tuple[int, ...]
    sprites: tuple[Sprite, ...]
    warnings: tuple[str, ...]

    @classmethod
    def parse(cls, path: Path) -> "SpriteFile":
        return cls.from_bytes(path.read_bytes(), path=path)

    @classmethod
    def from_bytes(cls, data: bytes, path: Path | None = None) -> "SpriteFile":
        """Parse sprite file data already held in memory -- a sprite
        area embedded in another file's own bytes (a DrawFile Sprite
        object, an Impression PICTURE dictionary entry, an ArtWorks
        SpriteRecord's own palette+pixel data, ...) never was a real
        file on disk, so callers with only bytes shouldn't need to
        write a temporary file just to call parse(). *path* is used
        only for diagnostics (error messages, the returned SpriteFile's
        own `.path`, `.to_dict()`'s "path" field); a caller with no
        real path can leave it as the default placeholder."""
        if path is None:
            path = Path("<memory>")
        if len(data) < FILE_HEADER_SIZE:
            raise SpriteFormatError(f"{path} is too small to be a sprite file")

        sprite_count, first_sprite_offset, free_offset = struct.unpack_from("<III", data, 0)
        first_sprite_file_offset = _area_to_file_offset(first_sprite_offset)
        free_file_offset = _area_to_file_offset(free_offset)

        if first_sprite_file_offset < FILE_HEADER_SIZE:
            raise SpriteFormatError(f"{path} has an invalid first sprite offset")
        if free_file_offset > len(data):
            raise SpriteFormatError(f"{path} has an invalid free offset")

        extension_bytes = first_sprite_file_offset - FILE_HEADER_SIZE
        if extension_bytes % 4 != 0:
            raise SpriteFormatError(f"{path} has a misaligned file header")
        extension_words = tuple(
            struct.unpack_from("<I", data, FILE_HEADER_SIZE + index)[0]
            for index in range(0, extension_bytes, 4)
        )

        warnings: list[str] = []
        sprites: list[Sprite] = []
        sprite_offset = first_sprite_file_offset
        for _ in range(sprite_count):
            sprite = Sprite.parse(data, path, sprite_offset)
            sprites.append(sprite)
            sprite_offset += sprite.size_bytes

        if sprite_offset != free_file_offset:
            raise SpriteFormatError(
                f"{path} ended sprite parsing at 0x{sprite_offset:x}, expected 0x{free_file_offset:x}"
            )

        if free_file_offset != len(data):
            warnings.append(
                f"file free offset 0x{free_offset:x} does not match file size 0x{len(data) + 4:x}"
            )

        return cls(
            path=path,
            sprite_count=sprite_count,
            first_sprite_offset=first_sprite_offset,
            free_offset=free_offset,
            extension_words=extension_words,
            sprites=tuple(sprites),
            warnings=tuple(warnings),
        )

    def select(
        self,
        *,
        name_pattern: str | None = None,
        mode_filter: str | None = None,
        type_filter: str | None = None,
        has_mask: bool = False,
    ) -> "SpriteSelection":
        sprites = list(self.sprites)
        if name_pattern:
            sprites = [sprite for sprite in sprites if fnmatch.fnmatch(sprite.name, name_pattern)]
        if mode_filter:
            sprites = [sprite for sprite in sprites if sprite.mode.matches_mode_filter(mode_filter)]
        if type_filter:
            sprites = [sprite for sprite in sprites if sprite.mode.matches_type_filter(type_filter)]
        if has_mask:
            sprites = [sprite for sprite in sprites if sprite.has_mask]
        return SpriteSelection(sprite_file=self, sprites=tuple(sprites))


@dataclass(frozen=True)
class SpriteSelection:
    """A sprite file together with a (possibly filtered) subset of its sprites."""

    sprite_file: SpriteFile
    sprites: tuple[Sprite, ...]

    def find(self, sprite_name: str) -> Sprite:
        for sprite in self.sprites:
            if sprite.name == sprite_name:
                return sprite
        available = ", ".join(sprite.name for sprite in self.sprites)
        raise SpriteFormatError(f"sprite '{sprite_name}' not found; available sprites: {available}")

    def warnings(self) -> list[str]:
        warnings = list(self.sprite_file.warnings)
        for sprite in self.sprites:
            warnings.extend(sprite.warnings)
        return warnings

    def extract(self, sprite_name: str, output_path: Path) -> None:
        sprite = self.find(sprite_name)
        source = self.sprite_file.path.read_bytes()
        sprite_bytes = source[sprite.file_offset : sprite.file_offset + sprite.size_bytes]
        first_sprite_offset = 16
        free_offset = first_sprite_offset + sprite.size_bytes
        output = struct.pack("<III", 1, first_sprite_offset, free_offset) + sprite_bytes
        output_path.write_bytes(output)

    def summary_text(self, verbose: bool = False) -> str:
        headers = _summary_headers(verbose)
        rows = [headers]
        for sprite in self.sprites:
            rows.append(sprite.summary_row(verbose))

        widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
        table = "\n".join(
            "  ".join(value.ljust(widths[index]) for index, value in enumerate(row)) for row in rows
        )
        if verbose:
            return (
                f"File: {self.sprite_file.path}\n"
                f"Sprites shown: {len(self.sprites)} of {self.sprite_file.sprite_count}\n{table}"
            )
        return table

    def details_text(self, sprite_name: str, verbose: bool = False) -> str:
        sprite = self.find(sprite_name)
        lines = [f"File: {self.sprite_file.path}"]
        lines.extend(sprite.details_lines(verbose=verbose))
        if verbose:
            lines.extend(
                [
                    f"File sprite count: {self.sprite_file.sprite_count}",
                    f"File first sprite offset: 0x{self.sprite_file.first_sprite_offset:x}",
                    f"File free offset: 0x{self.sprite_file.free_offset:x}",
                    f"File extension words: {_format_extension_words(self.sprite_file.extension_words)}",
                ]
            )
        lines.extend(sprite.warning_lines())
        return "\n".join(lines)

    def check_text(self, verbose: bool = False) -> str:
        warnings = self.warnings()
        if not warnings:
            suffix = (
                f" ({len(self.sprites)} of {self.sprite_file.sprite_count} sprites checked)"
                if verbose
                else ""
            )
            return f"{self.sprite_file.path}: OK{suffix}"
        lines = [f"{self.sprite_file.path}: {len(warnings)} warning(s)"]
        if verbose:
            lines.append(f"Sprites checked: {len(self.sprites)} of {self.sprite_file.sprite_count}")
        lines.extend(warnings)
        return "\n".join(lines)

    def check_json_text(self) -> str:
        warnings = self.warnings()
        payload = {
            "path": str(self.sprite_file.path),
            "filtered_sprite_count": len(self.sprites),
            "warnings": warnings,
            "ok": not warnings,
        }
        return json.dumps(payload, indent=2)

    def to_dict(self, sprite_name: str | None = None) -> dict[str, object]:
        if sprite_name:
            return self.find(sprite_name).to_dict()
        return {
            "path": str(self.sprite_file.path),
            "sprite_count": self.sprite_file.sprite_count,
            "filtered_sprite_count": len(self.sprites),
            "first_sprite_offset": self.sprite_file.first_sprite_offset,
            "free_offset": self.sprite_file.free_offset,
            "extension_words": list(self.sprite_file.extension_words),
            "warnings": list(self.sprite_file.warnings),
            "sprites": [sprite.to_dict() for sprite in self.sprites],
        }

    def json_text(self, sprite_name: str | None = None) -> str:
        return json.dumps(self.to_dict(sprite_name), indent=2)


def _summary_headers(verbose: bool) -> list[str]:
    if not verbose:
        return ["Name", "Size", "Type", "BPP", "Mask", "Palette", "DPI", "Mode"]
    return [
        "Name",
        "Size",
        "Type",
        "BPP",
        "Mask",
        "Palette",
        "Image",
        "MaskBytes",
        "Colour",
        "DPI",
        "Mode",
    ]
