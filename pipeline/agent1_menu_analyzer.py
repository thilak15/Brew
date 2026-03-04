"""
Agent 1: Menu Analyzer
======================
Accepts a menu in one of several formats (image file, URL, or raw JSON from a POS API)
and uses Gemini multimodal to extract a fully structured StructuredMenu object.

Inputs:
  - image_paths: list of paths to menu photo(s) or screenshots
  - url: a restaurant's online menu page URL
  - raw_json: already-structured JSON from a POS API (Toast, Square, Clover)
  - restaurant_name: display name of the restaurant
  - restaurant_id: snake_case ID used for output folder naming

Output:
  - pipeline/output/{restaurant_id}/menu.json
  - Returns a StructuredMenu object
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types as genai_types
from dotenv import load_dotenv
from PIL import Image

# Load env vars (GOOGLE_API_KEY)
load_dotenv(Path(__file__).resolve().parents[1] / "backend" / ".env")

from schemas import StructuredMenu, RestaurantInfo, MenuItem, ComboMeal, MenuModifiers, SwapOptions, UpsellRule

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

OUTPUT_BASE = Path(__file__).resolve().parent / "output"

# ---------------------------------------------------------------------------
# Extraction prompt — tells Gemini exactly what schema to output
# ---------------------------------------------------------------------------
EXTRACTION_PROMPT = """You are a restaurant menu data extraction expert.
Carefully analyze the provided menu image(s) or text and extract ALL information.

You MUST output a single valid JSON object matching this exact schema.
Do NOT include markdown fences, only raw JSON.

Schema:
{{
  "restaurant": {{
    "restaurant_id": "{restaurant_id}",
    "name": "{restaurant_name}",
    "type": "<burger|coffee|mexican|pizza|chicken|sandwich|asian|other>",
    "currency": "USD",
    "drive_through": true,
    "notes": "<any special ordering notes>"
  }},
  "categories": ["<list of all category names in order>"],
  "items": [
    {{
      "id": "<snake_case_item_id>",
      "name": "<exact menu name>",
      "category": "<category this item belongs to>",
      "description": "<brief description if visible>",
      "base_price": <price as float>,
      "sizes": ["<size options if available>"],
      "add_ons": ["<things that can be added>"],
      "swappables": {{
        "protein": [],
        "bread": [],
        "sauce": [],
        "milk": [],
        "other": {{}}
      }},
      "availability": "<all_day|breakfast_only|lunch_only|limited_time>",
      "is_combo_eligible": <true|false>
    }}
  ],
  "combos": [
    {{
      "id": "<snake_case_combo_id>",
      "name": "<combo name>",
      "description": "<what it includes>",
      "base_price": <price as float>,
      "includes": ["<item names>"],
      "upgrade_options": {{}},
      "availability": "all_day"
    }}
  ],
  "modifiers": {{
    "milk_swap": ["<alternative milk options if any>"],
    "sauces": ["<available sauces>"],
    "toppings": ["<available toppings>"],
    "ice_level": ["<ice options if any>"],
    "protein_swap": ["<protein alternatives if any>"],
    "bread_swap": ["<bread alternatives if any>"],
    "extra": {{}}
  }},
  "upsell_rules": [
    {{
      "trigger": "<when to trigger>",
      "suggestion": "<what to suggest>"
    }}
  ],
  "time_based_rules": ["<any time-of-day availability rules>"]
}}

IMPORTANT EXTRACTION RULES:
1. Extract EVERY SINGLE item visible on the menu — do not skip any.
2. If an item has multiple sizes, list all sizes in the "sizes" array.
3. For combos/meals, list every item included in the base combo.
4. Identify ALL customization options: what can be added, removed, or swapped.
5. If an item is "breakfast only" or "limited time", note it in availability.
6. Set is_combo_eligible=true for main entree items (burgers, sandwiches, etc.).
7. If prices are not visible, use 0.0 as a placeholder.
8. Generate reasonable upsell_rules based on the menu structure.
9. Output ONLY the JSON. No explanations, no markdown fences.
"""


def _encode_image(image_path: str | Path) -> tuple[str, str]:
    """Encode image file to base64 for Gemini API."""
    path = Path(image_path)
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("utf-8")
    mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return data, mime


def _clean_json_response(text: str) -> str:
    """Strip markdown fences if Gemini wraps the JSON in them."""
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ```
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def analyze_menu(
    restaurant_name: str,
    restaurant_id: str,
    image_paths: list[str | Path] | None = None,
    url: str | None = None,
    raw_json: dict[str, Any] | None = None,
    model_name: str = "gemini-2.5-flash",
) -> StructuredMenu:
    """
    Core function: Run Agent 1 to extract structured menu data.

    Priority: raw_json > image_paths > url
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set in environment")

    client = genai.Client(api_key=api_key)

    prompt_text = EXTRACTION_PROMPT.format(
        restaurant_name=restaurant_name,
        restaurant_id=restaurant_id,
    )

    if raw_json is not None:
        logger.info("Analyzing menu from raw JSON (POS API data)")
        contents = [prompt_text, f"\nHere is the raw menu data from the POS system:\n{json.dumps(raw_json, indent=2)}"]
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
        )

    elif image_paths:
        logger.info("Analyzing menu from %d image(s): %s", len(image_paths), image_paths)
        contents: list = [prompt_text]
        for img_path in image_paths:
            img = Image.open(img_path)
            contents.append(img)
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
        )

    elif url:
        logger.info("Analyzing menu from URL: %s", url)
        contents = [
            prompt_text,
            f"\nPlease analyze the menu from this restaurant's website: {url}\n"
            f"Extract all menu items, prices, and options you would find on a typical menu for this type of restaurant. "
            f"If you cannot access the URL directly, generate a realistic representative menu based on what you know about this restaurant chain."
        ]
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
        )

    else:
        raise ValueError("Must provide at least one of: image_paths, url, or raw_json")

    raw_text = response.text
    logger.debug("Raw Gemini response: %s", raw_text[:500])

    cleaned = _clean_json_response(raw_text)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON from Gemini response. Raw:\n%s", cleaned[:1000])
        raise RuntimeError(f"Gemini returned invalid JSON: {e}") from e

    # Validate with Pydantic
    try:
        menu = StructuredMenu(**data)
    except Exception as e:
        logger.error("Pydantic validation failed: %s\nData: %s", e, json.dumps(data, indent=2)[:2000])
        raise RuntimeError(f"Menu schema validation failed: {e}") from e

    logger.info(
        "✅ Menu extracted: %d items across %d categories, %d combos",
        len(menu.items), len(menu.categories), len(menu.combos)
    )
    return menu


def save_menu(menu: StructuredMenu, restaurant_id: str) -> Path:
    """Save the structured menu to pipeline/output/{restaurant_id}/menu.json"""
    out_dir = OUTPUT_BASE / restaurant_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "menu.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(menu.model_dump(), f, indent=2, ensure_ascii=False)
    logger.info("💾 Saved menu.json → %s", out_path)
    return out_path


def load_menu(restaurant_id: str) -> StructuredMenu:
    """Load a previously saved menu from pipeline/output/{restaurant_id}/menu.json"""
    path = OUTPUT_BASE / restaurant_id / "menu.json"
    if not path.exists():
        raise FileNotFoundError(f"No menu.json found for restaurant_id: {restaurant_id}")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return StructuredMenu(**data)


if __name__ == "__main__":
    # Quick standalone test:
    # python pipeline/agent1_menu_analyzer.py --name "Taco Bell" --id taco_bell_demo --url https://www.tacobell.com/food
    import argparse
    parser = argparse.ArgumentParser(description="Test Agent 1: Menu Analyzer")
    parser.add_argument("--name", required=True, help="Restaurant name")
    parser.add_argument("--id", required=True, help="Restaurant ID (snake_case)")
    parser.add_argument("--url", help="Restaurant menu URL")
    parser.add_argument("--image", nargs="+", help="Path(s) to menu image(s)")
    args = parser.parse_args()

    menu = analyze_menu(
        restaurant_name=args.name,
        restaurant_id=args.id,
        image_paths=args.image,
        url=args.url,
    )
    path = save_menu(menu, args.id)
    print(f"\n✅ Menu saved to: {path}")
    print(f"   Categories: {menu.categories}")
    print(f"   Total items: {len(menu.items)}")
    print(f"   Combos: {len(menu.combos)}")
