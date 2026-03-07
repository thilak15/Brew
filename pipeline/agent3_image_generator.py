import os
import io
import json
import logging
import re
import time
from pathlib import Path
from PIL import Image
from google import genai

logger = logging.getLogger(__name__)

def slug(s: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def generate_images(restaurant_id: str, progress_callback=None):
    output_dir = Path(f"/pipeline/output/{restaurant_id}")
    menu_path = output_dir / "menu.json"
    images_dir = output_dir / "images"
    
    if not menu_path.exists():
        logger.error("Menu JSON not found: %s", menu_path)
        return

    images_dir.mkdir(parents=True, exist_ok=True)
    with open(menu_path, "r", encoding="utf-8") as f:
        menu_data = json.load(f)

    rest_name = menu_data.get("restaurant", {}).get("name", restaurant_id)
    items = menu_data.get("items", []) + menu_data.get("combos", [])
    
    client = genai.Client()
    
    generated_count = 0
    for item in items:
        name = item.get("name")
        if not name:
            continue
            
        file_slug = slug(name)
        img_path = images_dir / f"{file_slug}.png"
        
        if img_path.exists():
            continue 

        desc = item.get("description", "")[:100]
        cat = item.get("category", "")
        cat_context = f"This item is from the '{cat}' menu category." if cat else ""
        
        prompt = f"Professional studio food photography of {rest_name} {name}. {cat_context} {desc}. Delicious, highly detailed, photorealistic, 4k resolution, clean minimal background. If it is a drink, show it in a clear plastic cup."
        
        models_to_try = [
            'imagen-4.0-fast-generate-001',
            'imagen-4.0-generate-001',
            'imagen-4.0-ultra-generate-001',
            'gemini-2.5-flash-image',
            'gemini-2.0-pro-exp-image'
        ]
        
        success = False
        for model_name in models_to_try:
            try:
                logger.info("Generating image for '%s' using %s...", name, model_name)
                response = client.models.generate_images(
                    model=model_name,
                    prompt=prompt,
                    config=dict(
                        number_of_images=1,
                        aspect_ratio="1:1"
                    )
                )
                for gen_img in response.generated_images:
                    image = Image.open(io.BytesIO(gen_img.image.image_bytes))
                    if image.mode in ("RGBA", "P"):
                        image = image.convert("RGB")
                    image.save(img_path, format="PNG")
                    
                generated_count += 1
                success = True
                time.sleep(1.5) # respectful rate limiting
                break # Break out of model fallback loop on success
                
            except Exception as e:
                error_str = str(e)
                if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str or 'quota' in error_str.lower():
                    logger.warning("%s quota exhausted. Falling back to next model...", model_name)
                    continue # Try the next model
                elif '404' in error_str or 'not found' in error_str.lower():
                    logger.warning("%s not available to this API key. Falling back...", model_name)
                    continue # Try the next model
                else:
                    logger.error("Failed to generate image for %s using %s: %s", name, model_name, e)
                    break # Unhandled error, stop trying models for this item
                    
        if not success:
            logger.error("All models failed or quota exhausted for item: %s", name)
            
    if generated_count > 0:
        logger.info("Successfully generated %d images.", generated_count)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
        generate_images(sys.argv[1])
    else:
        print("Usage: python agent3_image_generator.py <restaurant_id>")
