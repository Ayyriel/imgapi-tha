import json
import os
import sqlite3
import logging

from pathlib import Path

from app.utils.exifparser import extractExif
from app.utils.caption import extractCaption
from app.utils.thumbnail import generateThumbnail

DB_PATH = Path(os.getenv("DB_PATH", "/srv/database.db"))

logger = logging.getLogger("worker.jobs")

def exif_job(sha256: str, image_path: str) -> None:
    logger.info("exif_job_start sha256=%s image_path=%s", sha256, image_path)

    try:
        exif_json = extractExif(Path(image_path))
        logger.info("exif_extracted sha256=%s exif_len=%s", sha256, len(exif_json or ""))

        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            cur = conn.execute(
                "UPDATE metadata SET exif_json = ? WHERE sha256 = ?",
                (exif_json, sha256),
            )
            conn.commit()

        logger.info("exif_db_updated sha256=%s rows_updated=%s", sha256, cur.rowcount)

    except Exception:
        logger.exception("exif_job_failed sha256=%s image_path=%s", sha256, image_path)
        raise
    
def caption_job(sha256: str, image_path: str, image_id: str)-> None:
    caption = extractCaption(Path(image_path))
    with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            cur = conn.execute(
                "UPDATE metadata SET caption = ? WHERE sha256 = ?",
                (caption, sha256),
            )
            conn.execute(
                """
                UPDATE stats
                SET status = ?, end_time = datetime('now')
                WHERE image_id = ?
                """,
                (1, image_id),
            )
            
            conn.execute(
                """
                UPDATE images
                SET processed_at = datetime('now')
                WHERE image_id = ?
                """,
                (image_id,)
            )
            conn.commit()

def thumbnail_job(sha256: str, image_path: str)-> None:
    logger.info("thumbnail_job_start sha256=%s image_path=%s", sha256, image_path)
    try:
        generateThumbnail(Path(image_path),sha256)
        logger.info("thumbnail_made sha256=%s", sha256)
    except Exception:
        logger.exception("thumbnail_job_fail sha256=%s image_path=%s", sha256, image_path)
        raise
    
