from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from redis import Redis
from rq import Queue

from app.jobs import caption_job, exif_job, thumbnail_job
from app.utils.validator import validate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("imgapi")

DB_PATH = Path(os.getenv("DB_PATH", "database.db"))
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "media"))
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg"}
MAX_BYTES = 100 * 1024 * 1024 #100mb

def get_queue() -> Queue:
    return Queue("image-jobs", connection=Redis.from_url(REDIS_URL))

def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                sha256 TEXT PRIMARY KEY,
                width INTEGER,
                height INTEGER,
                format TEXT,
                size_bytes INTEGER,
                first_upload TEXT DEFAULT (datetime('now')),
                exif_json TEXT,
                caption TEXT
            );

            CREATE TABLE IF NOT EXISTS images (
                image_id TEXT PRIMARY KEY,
                original_name TEXT NOT NULL,
                processed_at TEXT DEFAULT (datetime('now')),
                image_path TEXT,
                metadata_sha256 TEXT,
                error TEXT,
                FOREIGN KEY (metadata_sha256) REFERENCES metadata(sha256)
            );

            CREATE TABLE IF NOT EXISTS stats (
                image_id TEXT PRIMARY KEY,
                start_time TEXT DEFAULT (datetime('now')),
                end_time TEXT,
                status INTEGER NOT NULL, -- 1 = success, 0 = failed
                FOREIGN KEY (image_id) REFERENCES images(image_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_stats_status ON stats(status);
            CREATE INDEX IF NOT EXISTS idx_stats_start_time ON stats(start_time);

            CREATE INDEX IF NOT EXISTS idx_images_metadata_sha256
            ON images(metadata_sha256);
            """
        )
        conn.commit()
        
def build_item(
    *,
    request: Request,
    status: str,
    image_id: str,
    original_name: str,
    processed_at: str,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = str(request.base_url).rstrip("/")
    thumbs = (
        {
            "small": f"{base}/api/images/{image_id}/thumbnails/small",
            "medium": f"{base}/api/images/{image_id}/thumbnails/medium",
        }
        if status == "success"
        else {}
    )

    return {
        "status": status,
        "data": {
            "image_id": image_id,
            "original_name": original_name,
            "processed_at": processed_at,
            "metadata": metadata or {},
            "thumbnails": thumbs,
        },
        "error": error,
    }

        
@asynccontextmanager
async def lifespan(app: FastAPI):
    init()
    yield
    

app = FastAPI(title="Image Upload", lifespan=lifespan)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    logger.info("%s %s -> %s (%.1fms)", request.method, request.url.path, response.status_code, ms)
    return response

@app.post("/api/images")
async def upload_img(request: Request, file: UploadFile = File(...)):
    original_name = (file.filename or "upload")
    ext = Path(original_name).suffix.lower()
    
    image_id = uuid4().hex
    stored_filename = f"{image_id}{ext}"
    
    destination = MEDIA_DIR / "originals" / stored_filename
    processed_at = datetime.now(timezone.utc).isoformat()
    try:
        v = await validate(file)
    except HTTPException as e:
        err_msg = str(e.detail)
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO images (image_id, original_name, error)
                VALUES (?, ?, ?)
                """,
                (image_id, original_name, err_msg),
            )
            
            conn.execute(
                """
                INSERT INTO stats (image_id, status)
                VALUES (?,?)
                """,
                (image_id, 0)
                )
            conn.commit()

        return build_item(
            request=request,
            status="failed",
            image_id=image_id,
            original_name=original_name,
            processed_at=processed_at,
            error=err_msg,
        )
    data = v.bytes
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    except Exception:
        destination.unlink(missing_ok=True)
        raise HTTPException(500,"Failed to save image")
    
    image_path = str(destination)
    size = len(data)
    
    with connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO metadata (sha256,width,height,format,size_bytes) VALUES (?,?,?,?,?)",
            (v.sha256,v.width,v.height,v.format, size),
        )
        if cur.rowcount == 0:
            pass
        else:
            try:
                q = get_queue()
                q.enqueue(thumbnail_job, v.sha256, image_path)
                q.enqueue(exif_job, v.sha256, image_path)
                q.enqueue(caption_job, v.sha256, image_path, image_id)
            except Exception:
                logger.exception("failed_to_enqueue sha256=%s image_id=%s", v.sha256, image_id)


        conn.execute(
            "INSERT INTO images (image_id, original_name, processed_at, image_path, metadata_sha256) "
            "VALUES (?, ?, ?, ?, ?)",
            (image_id, original_name, processed_at, image_path, v.sha256),
        )
        conn.execute(
                """
                INSERT INTO stats (image_id, status)
                VALUES (?,?)
                """,
                (image_id, 1)
        )
        conn.commit()
    return build_item(
    request=request,
        status="success",
        image_id=image_id,
        original_name=original_name,
        processed_at=processed_at,
        metadata={
            "width": v.width,
            "height": v.height,
            "format": v.format,
            "size_bytes": size,
            "sha256": v.sha256,
            "first_upload": processed_at
        },
    )
    
@app.get("/api/images")
def list_images(request: Request) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                i.image_id,
                i.original_name,
                i.processed_at,
                i.metadata_sha256,
                i.error AS err_msg,
                m.width,
                m.height,
                m.format,
                m.size_bytes,
                m.first_upload,
                m.caption,
                m.exif_json
            FROM images i
            LEFT JOIN metadata m ON m.sha256 = i.metadata_sha256
            ORDER BY i.processed_at DESC
            """
        ).fetchall()

    base = str(request.base_url).rstrip("/")
    items: list[dict[str, Any]] = []

    for r in rows:
        image_id = r["image_id"]

        if r["metadata_sha256"] is None:
            items.append(
                build_item(
                request=request,
                    status="failed",
                    image_id=image_id,
                    original_name=r["original_name"],
                    processed_at=r["processed_at"],
                    error=r["err_msg"],
                )
            )
            continue
        exif_obj = None
        exif = r["exif_json"]
        if exif:
            try:
                exif_obj = json.loads(exif)
            except json.JSONDecodeError:
                exif_obj = {"_raw": exif}  
        items.append(
            build_item(
                request=request,
                status="success",
                image_id=image_id,
                original_name=r["original_name"],
                processed_at=r["processed_at"],
                metadata={
                    "width": r["width"],
                    "height": r["height"],
                    "format": r["format"],
                    "size_bytes": r["size_bytes"],
                    "sha256": r["metadata_sha256"],
                    "first_upload": r["first_upload"],
                    "caption": r["caption"],
                    "exif_json": exif_obj,
                },
            )
        )

    return items

@app.get("/api/images/{image_id}")
def get_image(request: Request, image_id: str) -> dict[str, Any]:
    with connect() as conn:
        r = conn.execute(
            """
            SELECT
            i.image_id,
            i.original_name,
            i.processed_at,
            i.image_path,
            i.metadata_sha256,
            i.error,
            m.width,
            m.height,
            m.format,
            m.size_bytes,
            m.first_upload,
            m.exif_json,
            m.caption
            FROM images i
            LEFT JOIN metadata m ON m.sha256 = i.metadata_sha256
            WHERE i.image_id = ?
            """,
            (image_id,),
        ).fetchone()

        if not r:
            raise HTTPException(status_code=404, detail="Image not found")

        exif_obj = None
        exif = r["exif_json"]
        if exif:
            try:
                exif_obj = json.loads(exif)
            except json.JSONDecodeError:
                exif_obj = {"_raw": exif}  
        img_id = r["image_id"]
        base = str(request.base_url).rstrip("/")
        if r["metadata_sha256"] is None:
            err_msg = r["error"] or "unknown error"
            data = {
                "image_id": r["image_id"],
                "original_name": r["original_name"],
                "processed_at": r["processed_at"],
                "image_path": r["image_path"],
                "metadata": {},
                "thumbnails": {},
            }
            return {"status": "failed", "data": data, "error": err_msg}
        
        data = {
            "image_id": r["image_id"],
            "original_name": r["original_name"],
            "processed_at": r["processed_at"],
            "image_path": r["image_path"],
            "metadata": {
                "width": r["width"],
                "height": r["height"],
                "format": r["format"],
                "size_bytes": r["size_bytes"],
                "first_upload": r["first_upload"],
                "exif_json": exif_obj, 
                "sha256": r["metadata_sha256"],
                "caption": r["caption"]
            },
            "thumbnails": {
                "small": f"{base}/api/images/{img_id}/thumbnails/small",
                "medium": f"{base}/api/images/{img_id}/thumbnails/medium",
            },
        }

    return {"status": "success", "data": data, "error": None}

@app.get("/api/images/{image_id}/thumbnails/{size}")
def get_thumbnail(image_id: str, size: str):
    if size not in {"small","medium"}:
        raise HTTPException(400, "Invalid thumbnail size")
    
    with connect() as conn:
        row = conn.execute(
            "SELECT metadata_sha256 FROM images WHERE image_id=?",
            (image_id,),
        ).fetchone()
        
    if not row:
        raise HTTPException(404, "Image not found")
    
    sha256 = row["metadata_sha256"]
    if sha256 is None:
        raise HTTPException(404, "No thumbnail for failed upload")
    thumb_path = MEDIA_DIR / "thumbnails" / size / f"{sha256}.jpeg"
    
    if not thumb_path.exists():
        raise HTTPException(404, "Thumbnail not generated yet")

    return FileResponse(
        path=str(thumb_path),
        media_type="image/jpeg",
        filename=f"{sha256}_{size}.jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )

@app.get("/api/stats")
def get_stats() -> dict[str, Any]:
    fmt = "%Y-%m-%d %H:%M:%S"

    with connect() as conn:
        rows = conn.execute("SELECT start_time, end_time, status FROM stats").fetchall()

    total = len(rows)
    failed = sum(1 for r in rows if r["status"] == 0)

    durations = [
        (datetime.strptime(r["end_time"], fmt) - datetime.strptime(r["start_time"], fmt)).total_seconds()
        for r in rows
        if r["end_time"] is not None
    ]
    avg_seconds = int(round(sum(durations) / len(durations))) if durations else 0

    completed = [r for r in rows]
    completed_total = len(completed)
    completed_success = sum(1 for r in completed if r["status"] == 1)
    success_rate = f"{(completed_success / completed_total) * 100:.2f}%" if completed_total else "0.00%"

    return {
        "total": total,
        "failed": failed,
        "success_rate": success_rate,
        "average_processing_time_seconds": avg_seconds,
    }