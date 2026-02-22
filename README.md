# imgapi — FastAPI Image Upload API

FastAPI endpoint that accepts image uploads, stores originals on disk, stores metadata in SQLite, and runs background processing jobs (thumbnails, EXIF extraction, captioning) using Redis + RQ workers.

## 🚀 Quick Start

### Prerequisites
- Python 3.11+ (project currently uses Python in Docker)
- Docker + Docker Compose

---

# imgapi

A lightweight image-generation API + RQ worker setup.

---

## 🧰 Installation & Environment Setup


This project requires a **Hugging Face access token** to download/use models.

### Prerequisites
- Docker + Docker Compose installed

### 1) Create a local `.env` file

From the project root:

```bash
touch .env
```
### 2) Add your Hugging Face token to .env

Open .env and add:
```ini
HF_TOKEN=hf_your_token_here
```

Get your token from your **Hugging Face account settings (Access Tokens).**

⸻

### 🚀 Run with Docker
```bash
git clone https://github.com/ayyriel/imgapi.git
cd imgapi
docker compose up --build
```

## 📋 API Endpoints

Base URL: http://localhost:8000

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/images` | Upload an image (records success/failure) |
| GET | `/api/images` | List all upload records |
| GET | `/api/images/{image_id}` | Retrieve a single record |
| GET | `/api/images/{image_id}/thumbnails/{size}` | Get a thumbnail (`small`/`medium`) |
| GET | `/api/stats` | Upload stats summary |

---

## 📖 API Documentation + Example Usage

### Upload Image

```bash
curl -X POST "http://localhost:8000/api/images" \
  -F "file=@/path/to/photo.jpg"
```

Success response (example):

```json
{
  "status": "success",
  "data": {
    "image_id": "img123",
    "original_name": "photo.jpg",
    "processed_at": "2026-02-22 12:00:00",
    "metadata": {
      "width": 1920,
      "height": 1080,
      "format": "jpeg",
      "size_bytes": 2048576
    }
  },
  "thumbnails": {
    "small": "http://localhost:8000/api/images/img123/thumbnails/small",
    "medium": "http://localhost:8000/api/images/img123/thumbnails/medium"
  },
  "error": null
}
```

---

### Upload Invalid File (still recorded in DB)

```bash
curl -X POST "http://localhost:8000/api/images" \
  -F "file=@/path/to/file.xlsx"
```

Failure response (example):

```json
{
  "status": "failed",
  "data": {
    "image_id": "img789",
    "original_name": "file.xlsx",
    "processed_at": "2026-02-22 12:02:00",
    "metadata": {},
    "thumbnails": {}
  },
  "error": "invalid file format"
}
```

---

### List Images

```bash
curl "http://localhost:8000/api/images"
```

### Get Image by ID

```bash
curl "http://localhost:8000/api/images/<IMAGE_ID>"
```

### Download Thumbnail

```bash
curl -o small.jpg "http://localhost:8000/api/images/<IMAGE_ID>/thumbnails/small"
```

### Get Stats

```bash
curl "http://localhost:8000/api/stats"
```

Example response:

```json
{
  "total": 4,
  "failed": 1,
  "success_rate": "75.00%",
  "average_processing_time_seconds": 0
}
```
## 🔄 Processing Pipeline Explanation

1. **Upload**: Client sends `multipart/form-data` to `POST /api/images`.
2. **Validation** (`app/utils/validator.py`):
   - File extension allowlist  
   - MIME type allowlist  
   - "Magic-bytes" signature check  
   - Optional Pillow verify + decompression bomb guard
3. **On failure**:
   - Insert into `images` with error
   - Insert into `stats` with `status=0`
   - Return `{ "status": "failed", ... }`
4. **On success**:
   - Save original to `media/originals/{image_id}.{ext}`
   - Upsert metadata keyed by SHA256 into `metadata`
   - Insert upload into `images` referencing `metadata_sha256`
   - Insert into `stats` with `status=1`
5. **Background jobs** (Redis + RQ worker):
   - `thumbnail_job` saves thumbnails under `media/thumbnails/{size}/{sha256}.jpeg`
   - `exif_job` extracts EXIF and updates `metadata.exif_json`
   - `caption_job` generates a caption (BLIP) and updates `metadata.caption`
## 🗃️ Database Schema (SQLite)

Created automatically at app startup.

```sql
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
  status INTEGER NOT NULL,
  FOREIGN KEY (image_id) REFERENCES images(image_id) ON DELETE CASCADE
);
```

## 🧪 Testing

### Run tests in Docker (recommended)

```bash
docker compose run --rm test
```

### Run tests locally

```bash
pytest -q
```

Tests include:
- Unit tests for validator functions
- API tests for:
  - successful upload
  - failed upload still recorded
  - listing images
  - get image by id
  - stats endpoint

---

## 🐳 Docker

### Build + run

```bash
docker compose up --build
```

### Services
- `api`: FastAPI server
- `worker`: RQ worker processing background jobs
- `redis`: job queue backend
- `test`: runs pytest against an isolated test DB


