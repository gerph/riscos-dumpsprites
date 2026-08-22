"""Unit tests for SpriteFile.from_bytes()/parse()."""

from __future__ import annotations

from pathlib import Path

from riscos_sprites import SpriteFile

SPRITES_DIR = Path(__file__).resolve().parent.parent / "sprites"


def test_from_bytes_matches_parse_for_the_same_data():
    path = SPRITES_DIR / "manysprites,ff9"
    from_path = SpriteFile.parse(path)
    from_bytes = SpriteFile.from_bytes(path.read_bytes())

    assert from_bytes.sprite_count == from_path.sprite_count
    assert from_bytes.sprites == from_path.sprites
    assert from_bytes.warnings == from_path.warnings


def test_from_bytes_defaults_to_a_placeholder_path():
    data = (SPRITES_DIR / "manysprites,ff9").read_bytes()
    sprite_file = SpriteFile.from_bytes(data)
    assert sprite_file.path == Path("<memory>")


def test_from_bytes_accepts_an_explicit_path_for_diagnostics():
    data = (SPRITES_DIR / "manysprites,ff9").read_bytes()
    sprite_file = SpriteFile.from_bytes(data, path=Path("embedded-in-drawfile"))
    assert sprite_file.path == Path("embedded-in-drawfile")
