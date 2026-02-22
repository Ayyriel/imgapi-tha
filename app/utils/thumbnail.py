from pathlib import Path
from PIL import Image

THUMBS_DIR = Path("media") / "thumbnails"

def generateThumbnail(image_path: Path, sha256: str) -> dict[str, str]:
    small_path = THUMBS_DIR / "small" / f"{sha256}.jpeg"
    medium_path = THUMBS_DIR / "medium" / f"{sha256}.jpeg"

    small_path.parent.mkdir(parents=True, exist_ok=True)
    medium_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(image_path) as im:
        im = im.convert("RGB")

        small = im.copy()
        small.thumbnail((256, 256))
        small.save(small_path, format="JPEG", quality=85, optimize=True)

        medium = im.copy()
        medium.thumbnail((768, 768))
        medium.save(medium_path, format="JPEG", quality=85, optimize=True)

    return {
        "small": str(small_path),
        "medium": str(medium_path),
    }