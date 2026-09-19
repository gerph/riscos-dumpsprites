"""
Decode RISC OS sprite files and convert them to other formats.
"""

# Replaced with the real version by the Makefile at build time.
__version__ = "dev"

from .errors import SpriteFormatError
from .modes import NEW_SPRITE_TYPES, OLD_MODE_INFO, SpriteMode
from .palette import PaletteEntry
from .sprite import Sprite
from .spritefile import SpriteFile, SpriteSelection

__all__ = [
    "__version__",
    "SpriteFormatError",
    "SpriteMode",
    "OLD_MODE_INFO",
    "NEW_SPRITE_TYPES",
    "PaletteEntry",
    "Sprite",
    "SpriteFile",
    "SpriteSelection",
]
