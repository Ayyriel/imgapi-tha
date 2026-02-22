import pytest
from io import BytesIO

from fastapi import HTTPException
from PIL import Image
from starlette.datastructures import Headers, UploadFile

from app.utils.validator import get_ext, match_signature, pil_validate, validate


def make_png_bytes(w: int = 10, h: int = 10) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (w, h)).save(buf, format="PNG")
    return buf.getvalue()


def make_jpg_bytes(w: int = 10, h: int = 10) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (w, h)).save(buf, format="JPEG")
    return buf.getvalue()


def make_upload(filename: str, data: bytes, mime: str) -> UploadFile:
    return UploadFile(
        file=BytesIO(data),
        filename=filename,
        headers=Headers({"content-type": mime}),
    )


def test_get_ext():
    assert get_ext("photo.JPG") == ".jpg"
    assert get_ext("x.png") == ".png"
    assert get_ext("noext") == ""


def test_match_signature_png():
    data = make_png_bytes()
    assert match_signature("image/png", data) is True
    assert match_signature("image/jpeg", data) is False


def test_pil_validate_ok():
    data = make_png_bytes(12, 7)
    w, h, fmt = pil_validate(data, max_pixels=50_000_000)
    assert (w, h) == (12, 7)
    assert fmt == "png"


def test_pil_validate_decompression_guard_returns_zero_dims():
    data = make_png_bytes(200, 200)
    w, h, fmt = pil_validate(data, max_pixels=10)
    assert (w, h, fmt) == (0, 0, "")


@pytest.mark.anyio
async def test_validate_success_png():
    data = make_png_bytes()
    uf = make_upload("ok.png", data, "image/png")

    v = await validate(uf)
    assert v.ext == ".png"
    assert v.mime == "image/png"
    assert v.width > 0 and v.height > 0
    assert len(v.sha256) == 64


@pytest.mark.anyio
async def test_validate_bad_extension():
    data = make_png_bytes()
    uf = make_upload("bad.txt", data, "image/png")

    with pytest.raises(HTTPException) as e:
        await validate(uf)
    assert e.value.status_code == 400


@pytest.mark.anyio
async def test_validate_bad_signature():
    uf = make_upload("x.png", b"notapng", "image/png")

    with pytest.raises(HTTPException) as e:
        await validate(uf)
    assert "File bytes do not match" in str(e.value.detail)