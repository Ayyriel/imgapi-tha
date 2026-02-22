from pathlib import Path
import os
from PIL import Image

import torch
from transformers import BlipProcessor, BlipForConditionalGeneration



_MODEL = None
_PROCESSOR = None

def get_blip():
    global _MODEL, _PROCESSOR
    if _MODEL is None or _PROCESSOR is None:
        model_id = "Salesforce/blip-image-captioning-base"  # faster/lighter than large
        _PROCESSOR = BlipProcessor.from_pretrained(model_id)
        _MODEL = BlipForConditionalGeneration.from_pretrained(model_id,output_loading_info=False,).eval()
    return _MODEL, _PROCESSOR

def extractCaption(image_path: Path) -> str:
    model, processor = get_blip()

    with Image.open(image_path) as im:
        im = im.convert("RGB")

        im.thumbnail((1024, 1024))

        inputs = processor(images=im, return_tensors="pt")

        out_ids = model.generate(
            **inputs,
            max_new_tokens=30, 
            num_beams=1, 
        )

        caption = processor.decode(out_ids[0], skip_special_tokens=True).strip()
        return caption