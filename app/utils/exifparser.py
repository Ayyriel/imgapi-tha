import json
from pathlib import Path
from typing import Any
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

def _json_safe(v: Any) -> Any:
    if isinstance(v, bytes):
        return v.hex()
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _json_safe(val) for k, val in v.items()}
    return str(v)

def extractExif(image_path: Path) -> str:
    with Image.open(image_path) as im:
        exif = im.getexif()
        if not exif:
            return "{}"

        out: dict[str, Any] = {}
        for tag_id, value in exif.items():
            name = TAGS.get(tag_id, str(tag_id))
            if name == "GPSInfo" and isinstance(value, dict):
                gps = {}
                for gps_id, gps_val in value.items():
                    gps_name = GPSTAGS.get(gps_id, str(gps_id))
                    gps[gps_name] = _json_safe(gps_val)
                out["GPSInfo"] = gps
            else:
                out[name] = _json_safe(value)

        return json.dumps(out, ensure_ascii=False)