from io import BytesIO
from PIL import Image


def make_png_bytes(w=10, h=10) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (w, h)).save(buf, format="PNG")
    return buf.getvalue()


def test_post_image_success(client):
    data = make_png_bytes()
    res = client.post(
        "/api/images",
        files={"file": ("photo.png", data, "image/png")},
    )
    assert res.status_code == 200
    j = res.json()
    assert j["status"] == "success"
    assert j["error"] is None
    assert "image_id" in j["data"]
    assert j["data"]["metadata"]["sha256"] is not None
    assert j["data"]["metadata"]["width"] > 0


def test_post_image_failed_validation_still_records(client):
    res = client.post(
        "/api/images",
        files={"file": ("evil.xlsx", b"junk", "application/vnd.ms-excel")},
    )
    assert res.status_code == 200
    j = res.json()
    assert j["status"] == "failed"
    assert j["data"]["metadata"] == {}
    assert j["data"]["thumbnails"] == {}
    assert j["error"]


def test_get_images_list_returns_items(client):
    data = make_png_bytes()
    client.post("/api/images", files={"file": ("a.png", data, "image/png")})

    res = client.get("/api/images")
    assert res.status_code == 200
    items = res.json()
    assert isinstance(items, list)
    assert len(items) >= 1
    assert "status" in items[0]
    assert "data" in items[0]


def test_get_image_by_id(client):
    data = make_png_bytes()
    up = client.post("/api/images", files={"file": ("a.png", data, "image/png")}).json()
    image_id = up["data"]["image_id"]

    res = client.get(f"/api/images/{image_id}")
    assert res.status_code == 200
    j = res.json()
    assert j["status"] == "success"
    assert j["data"]["image_id"] == image_id


def test_get_stats(client):
    data = make_png_bytes()
    client.post("/api/images", files={"file": ("a.png", data, "image/png")})
    client.post("/api/images", files={"file": ("b.xlsx", b"x", "application/octet-stream")})

    res = client.get("/api/stats")
    assert res.status_code == 200
    j = res.json()
    assert j["total"] >= 2
    assert j["failed"] >= 1
    assert "success_rate" in j
    assert "average_processing_time_seconds" in j