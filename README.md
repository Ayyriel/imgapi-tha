# imgapi — FastAPI Image Upload API
FastAPI endpoint that accepts image uploads, stores originals on disk, stores metadata in SQLite, and runs background processing jobs (thumbnails, EXIF extraction, captioning) using Redis + RQ workers.

## Key Features
- **Queue-based processing** *(Redis + RQ workers)*: Heavy tasks (thumbnailing, EXIF extraction, captioning) run in background jobs so POST /api/images stays fast and responsive.

- **Multi-layer upload validation**: Files are verified by extension, MIME type, and magic-byte signature *(optionally Pillow integrity check + decompression-bomb guard)* to catch spoofed or corrupted uploads early.

- **SHA256 content hashing for dedup + efficiency**: Each image is hashed (SHA256) and stored in a separate metadata table keyed by the hash, enabling a *many-images to one metadata relationship*. Duplicate uploads reuse existing metadata instead of reprocessing.
- **Smart job triggering**: Background jobs only enqueue when a new SHA256 metadata row is created, avoiding repeated work on duplicate images.
- **Traceability + audit-friendly:** Both successful and failed uploads are recorded, including error messages, making it easy to monitor reliability and investigate issues.

## 🧰 Installation & Environment Setup

### Prerequisites
- Python 3.11+ (project currently uses Python in Docker)
- Docker + Docker Compose
- **Hugging Face Access Token** to download/use models.
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
### 3) Run with Docker!
```bash
git clone https://github.com/ayyriel/imgapi.git
cd imgapi
docker compose up --build
```

## API Endpoints

Base URL: http://localhost:8000

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/images` | Upload an image (records success/failure) |
| GET | `/api/images` | List all upload records |
| GET | `/api/images/{image_id}` | Retrieve a single record |
| GET | `/api/images/{image_id}/thumbnails/{size}` | Get a thumbnail (`small`/`medium`) |
| GET | `/api/stats` | Upload stats summary |

---

## API Documentation + Example Usage

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
		"image_id": "ea1e40863522443fada63c5ea23154bb",
		"original_name": "picturelol.jpg",
		"processed_at": "2026-02-22T04:53:29.671154+00:00",
		"metadata": {
			"width": 1920,
			"height": 2560,
			"format": "jpeg",
			"size_bytes": 496532,
			"sha256": "b5bb50df2ae36b6f245d37734db0ea045266bd7ebbf2b4d44e99210b23ef82fa",
			"first_upload": "2026-02-22T04:53:29.671154+00:00"
		},
		"thumbnails": {
			"small": "http://localhost:8000/api/images/ea1e40863522443fada63c5ea23154bb/thumbnails/small",
			"medium": "http://localhost:8000/api/images/ea1e40863522443fada63c5ea23154bb/thumbnails/medium"
		}
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
		"image_id": "806c1132278f46a0b0c10472a56a8d52",
		"original_name": "notaphoto.png",
		"processed_at": "2026-02-22T05:16:16.673900+00:00",
		"metadata": {},
		"thumbnails": {}
	},
	"error": "File bytes do not match image type"
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
Sample Complete Output (EXIF + Captions)
```json
{
	"status": "success",
	"data": {
		"image_id": "697f78df53264ae39c1bba4d01d2d73b",
		"original_name": "exifsample.jpg",
		"processed_at": "2026-02-22T05:17:28.616149+00:00",
		"image_path": "/srv/media/originals/697f78df53264ae39c1bba4d01d2d73b.jpg",
		"metadata": {
			"width": 1200,
			"height": 800,
			"format": "jpeg",
			"size_bytes": 189345,
			"first_upload": "2026-02-22 05:17:28",
			"exif_json": {
				"ResolutionUnit": 2,
				"ExifOffset": 226,
				"Make": "FUJIFILM",
				"Model": "X100F",
				"Software": "Adobe Photoshop Lightroom Classic 10.0 (Macintosh)",
				"Orientation": 1,
				"DateTime": "2020:11:20 15:46:49",
				"XResolution": "240.0",
				"YResolution": "240.0"
			},
			"sha256": "7cd6f3b85f20d011c9ada1ef7890602e5b3833e54c8018a3ac3487fd718746e7",
			"caption": null
		},
		"thumbnails": {
			"small": "http://localhost:8000/api/images/697f78df53264ae39c1bba4d01d2d73b/thumbnails/small",
			"medium": "http://localhost:8000/api/images/697f78df53264ae39c1bba4d01d2d73b/thumbnails/medium"
		}
	},
	"error": null
}
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
## Processing Pipeline Explanation

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
## Database Schema (SQLite)

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

## Testing

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


