from pathlib import Path
from dataclasses import dataclass
from fastapi import HTTPException, UploadFile

from io import BytesIO
from PIL import Image, UnidentifiedImageError


import hashlib

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
ALLOWED_MIME = {"image/jpeg", "image/png"}
SIGNATURES = {
    "image/jpeg": [b"\xFF\xD8\xFF"],
    "image/png": [b"\x89PNG\r\n\x1a\n"]
}

def get_ext(filename: str) -> str:
    return Path(filename or "").suffix.lower()

def match_signature(mime: str, data:bytes) -> bool:
    return any(data.startswith(signature) for signature in SIGNATURES.get(mime, []))

def pil_validate(data: bytes, *, max_pixels: int=50_000_000) -> tuple[int,int,str]:
    try:
        img = Image.open(BytesIO(data))
        w, h = img.size
        if w * h > max_pixels:
            return (0,0,"")
        img.verify()
        return (w, h, img.format.lower())
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, "Invalid or corrupted image")
    
@dataclass
class ValidatedUpload:
    ext: str
    mime: str
    bytes: bytes
    sha256: str
    width: int
    height: int
    format: str
    
async def validate(
    file: UploadFile,
) -> ValidatedUpload:
    extension = get_ext(file.filename or "")
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Bad Extension {extension or 'none'}")
    
    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_MIME:
        raise HTTPException(400, f"Bad MIME type: {mime or '(none)'}")
    
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty upload")
    if not match_signature(mime, data):
        raise HTTPException(400,"File bytes do not match image type")
    width, height, format = pil_validate(data, max_pixels=50_000_000)
    
    return ValidatedUpload(
        ext= extension,
        mime= mime,
        bytes=data,
        sha256=hashlib.sha256(data).hexdigest(),
        width=width,
        height=height,
        format=format)