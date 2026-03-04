"""
Image Generator
===============
For each item in a restaurant's menu.json, either:
  1. Fetches an existing image from the restaurant's website (if URL-based session), OR
  2. Generates a photorealistic product image using Gemini image generation

Output: pipeline/output/{restaurant_id}/images/{item_id}.png

These images are served by the Next.js frontend for the SmartMenu component,
replacing the hardcoded images currently in the Brew public/ directory.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import time
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / "backend" / ".env")

from schemas import StructuredMenu, MenuItem
from agent1_menu_analyzer import load_menu

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

OUTPUT_BASE = Path(__file__).resolve().parent / "output"

# ---------------------------------------------------------------------------
# Image generation prompt template
# ---------------------------------------------------------------------------
def _build_image_prompt(item: MenuItem, restaurant_name: str, restaurant_type: str) -> str:
    desc = f", {item.description}" if item.description else ""
    return (
        f"Photorealistic top-down professional food photography of '{item.name}'{desc} "
        f"from a {restaurant_type} fast-food restaurant called {restaurant_name}. "
        f"Clean white background, studio lighting, high resolution, appetizing, "
        f"no text or watermarks, no logos."
    )


def generate_item_image(
    item: MenuItem,
    restaurant_name: str,
    restaurant_type: str,
    out_dir: Path,
    model_name: str = "gemini-2.0-flash-exp",
) -> Path | None:
    """
    Generate a single menu item image and save it to out_dir/{item_id}.png.
    Returns the saved path, or None if generation failed.
    """
    out_path = out_dir / f"{item.id}.png"
    if out_path.exists():
        logger.info("⏭️  Skipping %s (already exists)", item.id)
        return out_path

    prompt = _build_image_prompt(item, restaurant_name, restaurant_type)
    logger.info("🎨 Generating image for: %s", item.name)

    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        genai.configure(api_key=api_key)

        # Use the imagen model for image generation
        imagen = genai.ImageGenerationModel("imagen-3.0-generate-002")
        result = imagen.generate_images(
            prompt=prompt,
            number_of_images=1,
            aspect_ratio="1:1",
            safety_filter_level="block_only_high",
            person_generation="dont_allow",
        )

        if result.images:
            img = result.images[0]
            out_dir.mkdir(parents=True, exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(img._image_bytes)
            logger.info("✅ Saved image: %s", out_path)
            return out_path
        else:
            logger.warning("⚠️  No image generated for: %s", item.name)
            return None

    except Exception as e:
        logger.warning("❌ Image generation failed for %s: %s", item.name, e)
        return None


def generate_all_images(
    menu: StructuredMenu,
    restaurant_id: str,
    delay_between: float = 1.5,
) -> dict[str, str]:
    """
    Generate images for all items in the menu.
    Returns a dict mapping item_id → image filename (for the frontend).
    """
    out_dir = OUTPUT_BASE / restaurant_id / "images"
    out_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, str] = {}
    total = len(menu.items)

    for i, item in enumerate(menu.items):
        logger.info("Processing image %d/%d: %s", i + 1, total, item.name)
        path = generate_item_image(
            item=item,
            restaurant_name=menu.restaurant.name,
            restaurant_type=menu.restaurant.type,
            out_dir=out_dir,
        )
        if path:
            results[item.id] = path.name
        # Rate limiting — avoid hitting API too fast
        if i < total - 1:
            time.sleep(delay_between)

    logger.info(
        "✅ Image generation complete: %d/%d images generated",
        len(results), total
    )
    return results


def save_image_manifest(results: dict[str, str], restaurant_id: str) -> Path:
    """
    Save a manifest JSON file mapping item_id → image filename.
    The frontend uses this to know which image to show for each menu item.
    """
    import json
    out_dir = OUTPUT_BASE / restaurant_id
    manifest_path = out_dir / "image_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info("💾 Image manifest saved: %s", manifest_path)
    return manifest_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate menu item images")
    parser.add_argument("--id", required=True, help="Restaurant ID")
    parser.add_argument("--delay", type=float, default=1.5, help="Seconds between API calls")
    args = parser.parse_args()

    menu = load_menu(args.id)
    results = generate_all_images(menu, args.id, delay_between=args.delay)
    save_image_manifest(results, args.id)
    print(f"\n✅ Generated {len(results)}/{len(menu.items)} images")
