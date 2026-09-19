"""
Command line interface for riscos-dumpsprites.

Kept as a thin, backward-compatible shim: all sprite decoding lives in the
``riscos_sprites`` package now, this module just wires it up behind the
same argparse flags and text/JSON output riscos-dumpsprites has always had.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from riscos_sprites import SpriteFile, SpriteFormatError, SpriteMode, SpriteSelection

from . import __version__


def parse_sprite_mode(raw_mode: int) -> SpriteMode:
    return SpriteMode.decode(raw_mode)


def parse_sprite_file(path: Path) -> SpriteFile:
    return SpriteFile.parse(path)


def select_sprites(
    sprite_file: SpriteFile,
    *,
    name_pattern: str | None = None,
    mode_filter: str | None = None,
    type_filter: str | None = None,
    has_mask: bool = False,
) -> SpriteSelection:
    return sprite_file.select(
        name_pattern=name_pattern,
        mode_filter=mode_filter,
        type_filter=type_filter,
        has_mask=has_mask,
    )


def build_summary(selection: SpriteSelection, verbose: bool = False) -> str:
    return selection.summary_text(verbose=verbose)


def build_details(selection: SpriteSelection, sprite_name: str, verbose: bool = False) -> str:
    return selection.details_text(sprite_name, verbose=verbose)


def build_check_report(selection: SpriteSelection, verbose: bool = False) -> str:
    return selection.check_text(verbose=verbose)


def build_json(selection: SpriteSelection, sprite_name: str | None = None) -> str:
    return selection.json_text(sprite_name)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="riscos-dumpsprites",
        description="Display information about a RISC OS sprite file.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("sprite_file", type=Path, help="Path to the sprite file")
    parser.add_argument(
        "sprite_name",
        nargs="?",
        help="Optional sprite name for a field-by-field description",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of text output",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the sprite file structure and report warnings",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show more fields in text output",
    )
    parser.add_argument(
        "--name",
        dest="name_pattern",
        help="Filter sprites by shell-style name pattern",
    )
    parser.add_argument(
        "--mode",
        dest="mode_filter",
        help="Filter by mode number, base mode number, raw mode value, or type string",
    )
    parser.add_argument(
        "--type",
        dest="type_filter",
        help="Filter by sprite type label such as old, 8bpp, 8bpp+a, 32bpp, RGB, or CMYK",
    )
    parser.add_argument(
        "--has-mask",
        action="store_true",
        help="Show only sprites which contain mask data",
    )
    parser.add_argument(
        "--extract",
        type=Path,
        metavar="OUTPUT",
        help="Write the selected sprite to its own sprite file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.extract is not None and not args.sprite_name:
        print("riscos-dumpsprites: --extract requires a sprite name", file=sys.stderr)
        return 1
    try:
        sprite_file = parse_sprite_file(args.sprite_file)
        selection = select_sprites(
            sprite_file,
            name_pattern=args.name_pattern,
            mode_filter=args.mode_filter,
            type_filter=args.type_filter,
            has_mask=args.has_mask,
        )
        if args.extract is not None:
            selection.extract(args.sprite_name, args.extract)
            output = "Extracted {0} to {1}".format(args.sprite_name, args.extract)
        elif args.check and args.json:
            output = selection.check_json_text()
        elif args.check:
            output = build_check_report(selection, verbose=args.verbose)
        elif args.json:
            output = build_json(selection, args.sprite_name)
        elif args.sprite_name:
            output = build_details(selection, args.sprite_name, verbose=args.verbose)
        else:
            output = build_summary(selection, verbose=args.verbose)
    except (OSError, SpriteFormatError) as exc:
        print("riscos-dumpsprites: {0}".format(exc), file=sys.stderr)
        return 1

    print(output)
    if args.check and selection.warnings():
        return 1
    return 0
