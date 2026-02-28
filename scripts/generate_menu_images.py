#!/usr/bin/env python3
"""
Optional hackathon asset pipeline: pre-generate menu item images with Imagen 3
via Gemini API. Saves PNGs to frontend/public/images/menu/ for the Smart Menu.

Requires: GOOGLE_API_KEY, and google-genai with image generation support.
Usage: python scripts/generate_menu_images.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Add backend to path if needed
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

try:
    from menu import get_menu_dict
except ImportError:
    get_menu_dict = None

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "frontend" / "public" / "images" / "menu"
PROMPT_TEMPLATE = (
    "Highly realistic commercial food photography of {name}, "
    "isolated on solid white background, studio lighting, professional product shot."
)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def main() -> int:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("Install: pip install google-genai")
        return 1

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Set GOOGLE_API_KEY")
        return 1

    if get_menu_dict:
        menu = get_menu_dict()
        names = [d["name"] for d in menu["drinks"]]
    else:
        names = [
            "Iced Latte",
            "Hot Latte",
            "Shaken Espresso",
            "Americano",
            "Cappuccino",
            "Cold Brew",
            "Matcha Latte",
            "Chai Latte",
            "Mocha",
        ]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = genai.Client(api_key=api_key)

    for name in names:
        path = OUTPUT_DIR / f"{slug(name)}.png"
        if path.exists():
            print(f"Skip (exists): {name}")
            continue
        prompt = PROMPT_TEMPLATE.format(name=name)
        try:
            # Use Gemini native image generation (works with AI Studio API keys)
            response = client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )
            # Extract image part from response
            saved = False
            if response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                        path.write_bytes(part.inline_data.data)
                        print(f"Saved: {name} -> {path}")
                        saved = True
                        break
            if not saved:
                print(f"No image for: {name}")
        except Exception as e:
            print(f"Error {name}: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
