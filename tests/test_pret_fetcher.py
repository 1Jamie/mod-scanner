import io
import tarfile
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw
import pytest

from mod_scanner.config import ImageRules, PretSource
from mod_scanner.core.image_scanner import compute_image_hash
from mod_scanner.pret_fetcher import ReferenceDatabase, index_pret_archive


def create_test_sprite(color=(200, 50, 50), shape="circle", size=(56, 56)) -> bytes:
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 2 if min(size) <= 8 else 8
    box = (margin, margin, max(margin, size[0] - margin), max(margin, size[1] - margin))
    if shape == "circle":
        draw.ellipse(box, fill=color, outline=(0, 0, 0, 255))
    else:
        draw.rectangle(box, fill=color, outline=(0, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_index_pret_archive_matches_flat_and_nested_directories(tmp_path):
    """
    Tests that patterns like 'gfx/sprites/**/*.png' and 'gfx/trainers/**/*.png'
    correctly match flat files (e.g., gfx/sprites/cook.png) as well as nested files.
    """
    tar_path = tmp_path / "test_repo.tar.gz"
    output_img_dir = tmp_path / "ref_images"

    cook_bytes = create_test_sprite(color=(180, 100, 50), shape="circle")
    officer_bytes = create_test_sprite(color=(50, 100, 200), shape="square")
    trainer_bytes = create_test_sprite(color=(20, 150, 50), shape="circle")
    bulba_bytes = create_test_sprite(color=(0, 200, 100), shape="circle")
    battle_bytes = create_test_sprite(color=(50, 50, 50), shape="square")
    tiny_bytes = create_test_sprite(color=(255, 255, 0), size=(8, 8))

    with tarfile.open(tar_path, "w:gz") as tar:
        def add_file(arcname, data):
            ti = tarfile.TarInfo(name=arcname)
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))

        # Flat sprite in gfx/sprites/
        add_file("pokered-master/gfx/sprites/cook.png", cook_bytes)
        add_file("pokered-master/gfx/sprites/officer_jenny.png", officer_bytes)
        # Flat trainer in gfx/trainers/
        add_file("pokered-master/gfx/trainers/brock.png", trainer_bytes)
        # Nested pokemon sprite in gfx/pokemon/bulbasaur/
        add_file("pokered-master/gfx/pokemon/bulbasaur/front.png", bulba_bytes)
        # Unmatched directory
        add_file("pokered-master/gfx/battle/hud.png", battle_bytes)
        # Tiny icon (< 16x16) should be filtered out
        add_file("pokered-master/gfx/sprites/tiny.png", tiny_bytes)

    source = PretSource(
        name="pokered",
        repo="pret/pokered",
        branch="master",
        image_patterns=[
            "gfx/sprites/**/*.png",
            "gfx/pokemon/**/*.png",
            "gfx/trainers/**/*.png",
        ],
    )

    image_rules = ImageRules(hash_type="dhash", hash_size=16)
    indexed = index_pret_archive(source, tar_path, image_rules, output_img_dir)

    # Verify flat directories matched
    assert "pokered/gfx/sprites/cook.png" in indexed
    assert "pokered/gfx/sprites/officer_jenny.png" in indexed
    assert "pokered/gfx/trainers/brock.png" in indexed

    # Verify nested matched
    assert "pokered/gfx/pokemon/bulbasaur/front.png" in indexed

    # Verify unmatched and tiny were filtered
    assert "pokered/gfx/battle/hud.png" not in indexed
    assert "pokered/gfx/sprites/tiny.png" not in indexed

    # Verify reference images were cached on disk
    assert (output_img_dir / "pokered" / "gfx" / "sprites" / "cook.png").exists()
    assert (output_img_dir / "pokered" / "gfx" / "trainers" / "brock.png").exists()

    # Verify ReferenceDatabase wrapper
    db = ReferenceDatabase(hashes=indexed, image_dir=output_img_dir)
    ref_img = db.get_reference_image("pokered/gfx/sprites/cook.png")
    assert ref_img is not None
    assert ref_img.size == (56, 56)
