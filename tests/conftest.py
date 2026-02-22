import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


class DummyQueue:
    def enqueue(self, *args, **kwargs):
        return None


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test.db"
    media_dir = tmp_path / "media"
    (media_dir / "originals").mkdir(parents=True, exist_ok=True)
    (media_dir / "thumbnails" / "small").mkdir(parents=True, exist_ok=True)
    (media_dir / "thumbnails" / "medium").mkdir(parents=True, exist_ok=True)

    os.environ["DB_PATH"] = str(db_path)
    os.environ["MEDIA_DIR"] = str(media_dir)
    os.environ["REDIS_URL"] = "redis://invalid:6379/0" 

    import app.main as main

    monkeypatch.setattr(main, "get_queue", lambda: DummyQueue())

    with TestClient(main.app) as c:
        yield c