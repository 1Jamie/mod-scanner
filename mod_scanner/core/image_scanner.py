"""
Image normalization, 256-bit dHash computation, Hamming distance, and 3-panel diff generation.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Optional, Tuple
from PIL import Image, ImageChops
import imagehash
from ..config import ImageRules


@dataclass
class ImageMatchResult:
    filename: str
    matched_ref_key: str
    hamming_distance: int
    mod_hash: str
    ref_hash: str
    status: str  # "REJECT", "FLAGGED", or "PASS"
    preview_image: Optional[Image.Image] = None


def normalize_image_for_hashing(img: Image.Image) -> Image.Image:
    """
    Normalizes any RGBA/palette/grayscale image by compositing any transparency
    onto a solid white background before converting to 8-bit grayscale luminance.
    This prevents transparent alpha channels from collapsing into black.
    """
    if img.mode != "RGBA":
        rgba_img = img.convert("RGBA")
    else:
        rgba_img = img

    # Composite over pure white canvas
    white_bg = Image.new("RGBA", rgba_img.size, (255, 255, 255, 255))
    composited = Image.alpha_composite(white_bg, rgba_img)
    return composited.convert("L")


def compute_image_hash(
    img: Image.Image,
    hash_size: int = 16,
    hash_type: str = "dhash"
) -> str:
    """
    Computes a perceptual hash (default 16x16 dHash = 256 bits) on the normalized grayscale image.
    Returns the hash as a hexadecimal string.
    """
    normalized = normalize_image_for_hashing(img)
    if hash_type == "phash":
        h = imagehash.phash(normalized, hash_size=hash_size)
    else:
        h = imagehash.dhash(normalized, hash_size=hash_size)

    return str(h)


def calculate_hamming_distance(hex_hash1: str, hex_hash2: str) -> int:
    """
    Computes the Hamming distance between two hexadecimal hash strings
    via bitwise XOR and bit-count.
    """
    val1 = int(hex_hash1, 16)
    val2 = int(hex_hash2, 16)
    return bin(val1 ^ val2).count("1")


def generate_diff_preview(
    mod_img: Image.Image,
    ref_img: Image.Image,
    panel_size: int = 64
) -> Image.Image:
    """
    Generates a crisp 3-panel comparison preview:
    [ Mod Asset ] [ Canonical Reference ] [ Pixel Difference ]
    Resized using NEAREST neighbor to preserve pixel art fidelity.
    """
    size = (panel_size, panel_size)

    # 1. Normalize both images for visual comparison
    mod_norm = Image.new("RGBA", size, (35, 39, 42, 255))
    ref_norm = Image.new("RGBA", size, (35, 39, 42, 255))

    # Resize preserving aspect ratio or fitting
    mod_resized = mod_img.convert("RGBA").resize(size, Image.Resampling.NEAREST)
    ref_resized = ref_img.convert("RGBA").resize(size, Image.Resampling.NEAREST)

    mod_norm.alpha_composite(mod_resized)
    ref_norm.alpha_composite(ref_resized)

    # 2. Compute visual difference
    diff = ImageChops.difference(mod_norm.convert("RGB"), ref_norm.convert("RGB"))

    # 3. Assemble 3-panel canvas
    canvas_width = panel_size * 3 + 16  # 16px padding between panels
    canvas_height = panel_size + 24     # header/footer space
    canvas = Image.new("RGB", (canvas_width, canvas_height), (24, 25, 28))

    # Paste panels
    canvas.paste(mod_norm.convert("RGB"), (4, 12))
    canvas.paste(ref_norm.convert("RGB"), (panel_size + 8, 12))
    canvas.paste(diff, (panel_size * 2 + 12, 12))

    return canvas
