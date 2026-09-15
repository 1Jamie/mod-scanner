"""
WebAssembly-optimized scanner engine for Pyodide in the browser.
Executes 100% client-side with zero NumPy/SciPy overhead.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import math
import os
import time
import zipfile
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from PIL import Image, ImageChops, ImageDraw
import yaml

logger = logging.getLogger("pyodide_scanner")

IMAGE_EXTENSIONS = {".png", ".bmp", ".jpg", ".jpeg", ".webp", ".tga"}
RAW_TEXTURE_EXTENSIONS = {".rgba", ".rgb", ".bgra", ".raw"}
TEXT_SOURCE_EXTENSIONS = {
    ".lua", ".py", ".md", ".txt", ".json", ".yml", ".yaml",
    ".toml", ".ini", ".c", ".h", ".cpp", ".hpp", ".rs", ".go", ".js", ".ts", ".html", ".css",
    ".patch", ".diff", ".log", ".csv", ".tsv", ".xml", ".svg", ".card"
}


# ====================================================================
# Configuration Data Structures
# ====================================================================

@dataclass
class MagicByteRule:
    name: str
    offset: int
    raw_bytes: bytes


@dataclass
class BinaryRules:
    blacklisted_extensions: set[str] = field(default_factory=set)
    magic_bytes: list[MagicByteRule] = field(default_factory=list)
    contained_signatures: list[MagicByteRule] = field(default_factory=list)


@dataclass
class ImageRules:
    hash_size: int = 16
    threshold_auto_reject: int = 14
    threshold_flag_for_review: int = 30
    generate_diff_preview: bool = True
    preview_panel_size: int = 64


@dataclass
class PretSource:
    name: str
    repo: str
    branch: str


# ====================================================================
# Perceptual Image Hashing & Diff Generator (Pure Pillow)
# ====================================================================

def normalize_image_for_hashing(img: Image.Image) -> Image.Image:
    """Normalizes transparency over solid white background before converting to 8-bit luminance."""
    if img.mode != "RGBA":
        rgba_img = img.convert("RGBA")
    else:
        rgba_img = img

    white_bg = Image.new("RGBA", rgba_img.size, (255, 255, 255, 255))
    composited = Image.alpha_composite(white_bg, rgba_img)
    return composited.convert("L")


def compute_dhash_pillow(img: Image.Image, hash_size: int = 16) -> str:
    """
    Computes a 16x16 difference hash (256 bits) using only standard Pillow.
    Produces 100% bit-for-bit identical hashes to imagehash.dhash without NumPy or SciPy.
    """
    resized = img.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    pixels = list(resized.getdata())
    diff = []
    for row in range(hash_size):
        row_offset = row * (hash_size + 1)
        for col in range(hash_size):
            diff.append(pixels[row_offset + col + 1] > pixels[row_offset + col])

    bit_string = "".join("1" if b else "0" for b in diff)
    width = (len(bit_string) + 3) // 4
    return f"{int(bit_string, 2):0{width}x}"


def calculate_hamming_distance(hex_hash1: str, hex_hash2: str) -> int:
    """Computes bitwise Hamming distance between two hex hashes."""
    try:
        val1 = int(hex_hash1, 16)
        val2 = int(hex_hash2, 16)
        return bin(val1 ^ val2).count("1")
    except Exception:
        return 999999


def _create_checkerboard_panel(size: Tuple[int, int], grid_size: int = 8) -> Image.Image:
    """Creates a subtle light-gray neutral backdrop for crisp 1:1 sprite display."""
    panel = Image.new("RGBA", size, (238, 241, 246, 255))
    draw = ImageDraw.Draw(panel)
    c2 = (226, 232, 240, 255)
    for y in range(0, size[1], grid_size):
        for x in range(0, size[0], grid_size):
            if ((x // grid_size) + (y // grid_size)) % 2 == 1:
                draw.rectangle((x, y, x + grid_size - 1, y + grid_size - 1), fill=c2)
    return panel


def _fit_image_centered(img: Image.Image, target_size: Tuple[int, int]) -> Image.Image:
    """Centers sprite 1:1 or scales down if exceeding panel size."""
    canvas = _create_checkerboard_panel(target_size)
    img_rgba = img.convert("RGBA")

    if img_rgba.width <= target_size[0] and img_rgba.height <= target_size[1]:
        offset_x = (target_size[0] - img_rgba.width) // 2
        offset_y = (target_size[1] - img_rgba.height) // 2
        canvas.alpha_composite(img_rgba, (offset_x, offset_y))
    else:
        scale = min(target_size[0] / img_rgba.width, target_size[1] / img_rgba.height)
        new_w = max(1, int(img_rgba.width * scale))
        new_h = max(1, int(img_rgba.height * scale))
        resized = img_rgba.resize((new_w, new_h), Image.Resampling.NEAREST)
        offset_x = (target_size[0] - new_w) // 2
        offset_y = (target_size[1] - new_h) // 2
        canvas.alpha_composite(resized, (offset_x, offset_y))

    return canvas


def generate_diff_preview(
    mod_img: Image.Image,
    ref_img: Image.Image,
    panel_size: int = 64,
    upscale_factor: int = 2
) -> Image.Image:
    """Generates a crisp 3-panel comparison preview: [Mod] [Canonical Ref] [Difference]."""
    base_dim = max(panel_size, mod_img.width, mod_img.height, ref_img.width, ref_img.height)
    base_dim = ((base_dim + 7) // 8) * 8
    target_size = (base_dim, base_dim)

    mod_norm = _fit_image_centered(mod_img, target_size)
    ref_norm = _fit_image_centered(ref_img, target_size)
    diff = ImageChops.difference(mod_norm.convert("RGB"), ref_norm.convert("RGB"))

    pad = 4
    canvas_width = base_dim * 3 + pad * 4
    canvas_height = base_dim + pad * 2
    canvas = Image.new("RGB", (canvas_width, canvas_height), (24, 25, 28))

    canvas.paste(mod_norm.convert("RGB"), (pad, pad))
    canvas.paste(ref_norm.convert("RGB"), (base_dim + pad * 2, pad))
    canvas.paste(diff, (base_dim * 2 + pad * 3, pad))

    if upscale_factor > 1:
        canvas = canvas.resize(
            (canvas.width * upscale_factor, canvas.height * upscale_factor),
            Image.Resampling.NEAREST
        )

    return canvas


# ====================================================================
# Web Scanner Controller
# ====================================================================

class WebModScanner:
    def __init__(self, config_yaml_str: str, reference_hashes_json_str: str):
        self.config_raw = yaml.safe_load(config_yaml_str) or {}
        
        # Parse pret sources
        self.pret_sources: Dict[str, PretSource] = {}
        for s in self.config_raw.get("pret_sources", []):
            name = s.get("name", "")
            if name:
                self.pret_sources[name] = PretSource(
                    name=name,
                    repo=s.get("repo", ""),
                    branch=s.get("branch", "master"),
                )

        # Parse binary rules
        b_cfg = self.config_raw.get("binary_rules", {})
        blacklisted = {ext.lower() for ext in b_cfg.get("blacklisted_extensions", [])}
        
        magic_rules = []
        for r in b_cfg.get("magic_bytes", []):
            hex_str = r.get("hex", "").replace(" ", "").replace("0x", "").strip()
            if hex_str:
                try:
                    raw = bytes.fromhex(hex_str)
                    if raw:
                        magic_rules.append(MagicByteRule(name=r.get("name", "Unknown"), offset=int(r.get("offset", 0)), raw_bytes=raw))
                except Exception:
                    pass

        contained_rules = []
        for r in b_cfg.get("contained_signatures", []):
            raw_b = None
            if "hex" in r and r["hex"]:
                try:
                    raw_b = bytes.fromhex(r["hex"].replace(" ", "").replace("0x", "").strip())
                except Exception:
                    pass
            elif "pattern" in r and r["pattern"]:
                raw_b = r["pattern"].encode("utf-8")

            if raw_b:
                contained_rules.append(MagicByteRule(name=r.get("name", "Unknown"), offset=0, raw_bytes=raw_b))

        self.binary_rules = BinaryRules(
            blacklisted_extensions=blacklisted,
            magic_bytes=magic_rules,
            contained_signatures=contained_rules,
        )

        # Parse image rules
        i_cfg = self.config_raw.get("image_rules", {})
        thresholds = i_cfg.get("thresholds", {})
        self.image_rules = ImageRules(
            hash_size=i_cfg.get("hash_size", 16),
            threshold_auto_reject=thresholds.get("auto_reject", 14),
            threshold_flag_for_review=thresholds.get("flag_for_review", 30),
            generate_diff_preview=i_cfg.get("generate_diff_preview", True),
            preview_panel_size=i_cfg.get("preview_panel_size", 64),
        )

        # Parse reference hashes and pre-compile integer lookup table for high-speed bit_count
        ref_data = json.loads(reference_hashes_json_str) if isinstance(reference_hashes_json_str, str) else reference_hashes_json_str
        self.ref_hashes: Dict[str, str] = ref_data.get("hashes", {}) if isinstance(ref_data, dict) else {}
        self.ref_int_table: List[Tuple[str, int, str]] = []
        for k, h in self.ref_hashes.items():
            try:
                self.ref_int_table.append((k, int(h, 16), h))
            except Exception:
                pass
        self.whitelist: set[str] = set()

    def add_whitelist_hashes(self, hashes: list[str]):
        """Adds approved hashes to whitelist."""
        for h in hashes:
            self.whitelist.add(str(h).strip().lower())

    def get_canonical_image_url(self, ref_key: str) -> Optional[str]:
        """Maps a ref_key like 'pokered/gfx/pokemon/front.png' to a raw GitHub CDN URL."""
        parts = ref_key.split("/", 1)
        if len(parts) == 2:
            source_name, rel_path = parts
            source = self.pret_sources.get(source_name)
            if source:
                return f"https://raw.githubusercontent.com/{source.repo}/{source.branch}/{rel_path}"
        return None

    def check_file_stream(self, stream: io.BytesIO, filename: str) -> Optional[Dict[str, str]]:
        """Checks stream for binary/ROM header violations."""
        _, ext = os.path.splitext(filename)
        ext_lower = ext.lower()

        if ext_lower in self.binary_rules.blacklisted_extensions:
            return {
                "file_path": filename,
                "rule_type": "Blacklisted Extension",
                "message": f"File '{filename}' has prohibited console ROM/container extension '{ext_lower}'"
            }

        header_chunk = stream.read(65536)
        if not header_chunk:
            return None

        header_len = len(header_chunk)

        # Check fixed-offset magic bytes
        for rule in self.binary_rules.magic_bytes:
            req_len = rule.offset + len(rule.raw_bytes)
            if header_len >= req_len:
                if header_chunk[rule.offset : req_len] == rule.raw_bytes:
                    return {
                        "file_path": filename,
                        "rule_type": rule.name,
                        "message": f"File matches console ROM header '{rule.name}' at offset 0x{rule.offset:04X}"
                    }

        # Check contained signatures in non-text files
        if ext_lower not in TEXT_SOURCE_EXTENSIONS and self.binary_rules.contained_signatures:
            for c_rule in self.binary_rules.contained_signatures:
                pos = header_chunk.find(c_rule.raw_bytes)
                if pos != -1:
                    return {
                        "file_path": filename,
                        "rule_type": c_rule.name,
                        "message": f"Binary contains prohibited proprietary asset signature '{c_rule.name}' at offset 0x{pos:04X}"
                    }

        return None

    async def scan_zip(
        self,
        zip_bytes: bytes,
        archive_name: str = "mod.zip",
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        image_fetcher: Optional[Callable[[str], Any]] = None,
    ) -> Dict[str, Any]:
        """
        Sequentially scans a zip archive in memory without extracting files to disk.
        Frees memory after each entry to adhere to 32-bit WebAssembly limits.
        """
        start_time = time.time()
        violations: list[dict[str, str]] = []
        flags: list[dict[str, Any]] = []
        scanned_count = 0

        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                namelist = zf.namelist()
                total_files = len(namelist)

                for idx, entry_name in enumerate(namelist):
                    if entry_name.endswith("/"):
                        continue

                    scanned_count += 1
                    if progress_callback:
                        progress_callback(scanned_count, total_files, entry_name)

                    # Tier 1: Binary & Magic Byte Check
                    with zf.open(entry_name) as f:
                        file_stream = io.BytesIO(f.read(65536))
                        v = self.check_file_stream(file_stream, entry_name)
                        if v:
                            violations.append(v)
                            continue

                    # Tier 2: Image Perceptual Hashing Check
                    _, ext = os.path.splitext(entry_name)
                    ext_lower = ext.lower()

                    if ext_lower in IMAGE_EXTENSIONS:
                        try:
                            with zf.open(entry_name) as f:
                                img_bytes = f.read()
                            
                            img = Image.open(io.BytesIO(img_bytes))
                            img.load()

                            # Ignore single-color masks or sub-16px helper tiles
                            if img.width >= 16 and img.height >= 16:
                                extrema = img.convert("L").getextrema()
                                if extrema[0] != extrema[1]:
                                    norm = normalize_image_for_hashing(img)
                                    mod_hash = compute_dhash_pillow(norm, hash_size=self.image_rules.hash_size)

                                    if mod_hash.lower() not in self.whitelist:
                                        mod_int = int(mod_hash, 16)
                                        best_match = None
                                        best_dist = 999999
                                        best_ref_hash = None

                                        for ref_key, ref_int, ref_hex in self.ref_int_table:
                                            dist = (mod_int ^ ref_int).bit_count()
                                            if dist < best_dist:
                                                best_dist = dist
                                                best_match = ref_key
                                                best_ref_hash = ref_hex
                                                if dist == 0:
                                                    break

                                        total_bits = self.image_rules.hash_size ** 2
                                        sim_pct = max(0.0, (total_bits - best_dist) / total_bits * 100)

                                        if best_match and best_dist <= self.image_rules.threshold_auto_reject:
                                            violations.append({
                                                "file_path": entry_name,
                                                "rule_type": "DirectAssetRip",
                                                "message": f"Asset matches canonical sprite '{best_match}' ({best_dist}/{total_bits} bits, {sim_pct:.1f}% similarity)"
                                            })
                                        elif best_match and best_dist <= self.image_rules.threshold_flag_for_review:
                                            preview_data_url = None
                                            # Fetch canonical reference sprite for diff preview
                                            if self.image_rules.generate_diff_preview and image_fetcher:
                                                ref_url = self.get_canonical_image_url(best_match)
                                                if ref_url:
                                                    try:
                                                        ref_bytes = await image_fetcher(ref_url)
                                                        if ref_bytes:
                                                            ref_img = Image.open(io.BytesIO(ref_bytes))
                                                            ref_img.load()
                                                            diff_canvas = generate_diff_preview(
                                                                mod_img=img,
                                                                ref_img=ref_img,
                                                                panel_size=self.image_rules.preview_panel_size,
                                                            )
                                                            buf = io.BytesIO()
                                                            diff_canvas.save(buf, format="PNG")
                                                            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                                                            preview_data_url = f"data:image/png;base64,{b64}"
                                                    except Exception as e:
                                                        logger.debug(f"Failed to fetch ref image for diff: {e}")

                                            flags.append({
                                                "file_path": entry_name,
                                                "matched_ref": best_match,
                                                "hamming_distance": best_dist,
                                                "similarity_pct": f"{sim_pct:.1f}%",
                                                "mod_hash": mod_hash,
                                                "ref_hash": best_ref_hash or "",
                                                "preview_data_url": preview_data_url,
                                            })
                        except Exception as e:
                            logger.debug(f"Could not parse image {entry_name}: {e}")

        except Exception as e:
            violations.append({
                "file_path": archive_name,
                "rule_type": "ArchiveError",
                "message": f"Archive extraction or scanning failed: {str(e)}"
            })

        elapsed = time.time() - start_time
        
        # Determine overall status
        if violations:
            status = "REJECT"
            summary = f"REJECTED: Found {len(violations)} prohibited ROM binary / asset rip violation(s)."
        elif flags:
            status = "FLAGGED"
            summary = f"FLAGGED: Found {len(flags)} asset(s) with high similarity to canonical sprites needing review."
        else:
            status = "CLEAN"
            summary = f"CLEAN: Passed all checks with 0 violations across {scanned_count} files."

        return {
            "status": status,
            "summary": summary,
            "archive_name": archive_name,
            "scanned_file_count": scanned_count,
            "elapsed_seconds": round(elapsed, 2),
            "violations": violations,
            "flags": flags,
        }
