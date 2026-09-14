import io
import tempfile
import zipfile
from pathlib import Path
import pytest
from PIL import Image, ImageDraw
from mod_scanner.config import Config
from mod_scanner.core.image_scanner import compute_image_hash
from mod_scanner.pret_fetcher import ReferenceDatabase
from mod_scanner.scanner import ModScanner, WhitelistManager


def create_test_image(color=(100, 150, 200)) -> bytes:
    img = Image.new("RGBA", (56, 56), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 48, 48), fill=color, outline=(0, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def mock_scanner(tmp_path):
    config = Config.from_file("config.yaml")
    config.paths.cache_dir = tmp_path / ".cache"
    config.paths.whitelist_file = tmp_path / "whitelist.json"

    # Setup mock reference database
    ref_img_data = create_test_image(color=(255, 0, 0))
    ref_img = Image.open(io.BytesIO(ref_img_data))
    ref_hash = compute_image_hash(ref_img, hash_size=16)

    ref_images_dir = tmp_path / ".cache" / "reference_images"
    ref_images_dir.mkdir(parents=True, exist_ok=True)
    (ref_images_dir / "pokered" / "gfx" / "pokemon").mkdir(parents=True, exist_ok=True)
    ref_img.save(ref_images_dir / "pokered" / "gfx" / "pokemon" / "bulbasaur.png")

    ref_db = ReferenceDatabase(
        hashes={"pokered/gfx/pokemon/bulbasaur.png": ref_hash},
        image_dir=ref_images_dir
    )

    return ModScanner(config=config, ref_db=ref_db)


def test_pipeline_clean_mod(mock_scanner):
    # Zip with unrelated custom art (e.g. square) and clean text
    square_img = Image.new("RGBA", (56, 56), (0, 0, 0, 0))
    draw = ImageDraw.Draw(square_img)
    draw.rectangle((5, 5, 50, 50), fill=(0, 255, 0, 255))
    img_buf = io.BytesIO()
    square_img.save(img_buf, format="PNG")

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as z:
        z.writestr("README.md", b"# Custom Mod")
        z.writestr("textures/custom_block.png", img_buf.getvalue())

    result = mock_scanner.scan_archive_sync(zip_buf.getvalue())
    assert result.is_clean
    assert result.status == "CLEAN"


def test_pipeline_reject_rom_header(mock_scanner):
    # Zip containing file with GBA fixed complement byte
    header = bytearray(512)
    header[0x00B2] = 0x96

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as z:
        z.writestr("assets/game_core.bin", bytes(header))

    result = mock_scanner.scan_archive_sync(zip_buf.getvalue())
    assert result.is_rejected
    assert any("GBA" in v.message for v in result.violations)


def test_pipeline_reject_direct_asset_rip(mock_scanner):
    # Exact recolor of reference bulbasaur
    rip_data = create_test_image(color=(0, 0, 255))  # Same shape, blue

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as z:
        z.writestr("gfx/bulbasaur_shiny.png", rip_data)

    result = mock_scanner.scan_archive_sync(zip_buf.getvalue())
    assert result.is_rejected
    assert any("bulbasaur.png" in v.message for v in result.violations)


def test_whitelist_allows_previously_flagged(mock_scanner):
    rip_data = create_test_image(color=(0, 0, 255))
    img = Image.open(io.BytesIO(rip_data))
    img_hash = compute_image_hash(img, hash_size=16)

    # Approve hash into whitelist
    mock_scanner.whitelist.approve(img_hash)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as z:
        z.writestr("gfx/bulbasaur_shiny.png", rip_data)

    result = mock_scanner.scan_archive_sync(zip_buf.getvalue())
    assert result.is_clean
