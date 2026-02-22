import os
import logging
import subprocess
from huggingface_hub import login
from transformers.utils import logging as tlog

tlog.set_verbosity_error()

logger = logging.getLogger("worker.boot")


logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("torch").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

def warmup_model():
    from app.utils.caption import get_blip
    logger.info("Warming up BLIP...")
    get_blip()
    logger.info("BLIP warmed.")

if __name__ == "__main__":
    warmup_model()
    login(token = (os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN") or "").strip() or None)
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    logger.info("Starting RQ worker...")
    subprocess.run(["rq", "worker", "image-jobs", "--url", redis_url], check=True)