"""
Pipeline Orchestrator CLI
=========================
Runs the full 3-agent pipeline in sequence for a given restaurant:
  Step 1 → Agent 1: Menu Analyzer → menu.json
  Step 2 → Agent 2: Prompt Architect → system_prompt.md
  Step 3 → Image Generator → images/ + image_manifest.json

Usage:
  # From a menu photo:
  python pipeline/run_pipeline.py --name "Taco Bell" --id taco_bell_demo --image menu.jpg

  # From a URL:
  python pipeline/run_pipeline.py --name "McDonald's" --id mcdonalds_demo --url https://www.mcdonalds.com/us/en-us/full-menu.html

  # Skip image generation (faster for testing):
  python pipeline/run_pipeline.py --name "Wendy's" --id wendys_demo --url https://www.wendys.com/menu --skip-images

  # Use existing menu.json, only regenerate prompt:
  python pipeline/run_pipeline.py --id taco_bell_demo --prompt-only
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure pipeline/ is in path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent1_menu_analyzer import analyze_menu, save_menu, load_menu
from agent2_prompt_architect import generate_prompt, save_prompt
from image_generator import generate_all_images, save_image_manifest

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)

OUTPUT_BASE = Path(__file__).resolve().parent / "output"


def print_separator(title: str) -> None:
    width = 60
    print(f"\n{'━' * width}")
    print(f"  {title}")
    print(f"{'━' * width}")


def run_pipeline(
    restaurant_name: str,
    restaurant_id: str,
    image_paths: list[str] | None = None,
    url: str | None = None,
    raw_json: dict | None = None,
    skip_images: bool = False,
    prompt_only: bool = False,
    image_delay: float = 1.5,
) -> dict:
    """
    Run the full pipeline. Returns a summary dict of what was generated.
    """
    results = {
        "restaurant_id": restaurant_id,
        "restaurant_name": restaurant_name,
        "menu_path": None,
        "prompt_path": None,
        "images_generated": 0,
        "manifest_path": None,
    }

    # ─── Step 1: Menu Analysis ───────────────────────────────────────────────
    if not prompt_only:
        print_separator("STEP 1 / 3 — Menu Analyzer (Agent 1)")
        print(f"  Restaurant: {restaurant_name}")
        if image_paths:
            print(f"  Input:      {len(image_paths)} image(s)")
        elif url:
            print(f"  Input:      {url}")
        elif raw_json:
            print("  Input:      POS API JSON")

        menu = analyze_menu(
            restaurant_name=restaurant_name,
            restaurant_id=restaurant_id,
            image_paths=image_paths,
            url=url,
            raw_json=raw_json,
        )
        menu_path = save_menu(menu, restaurant_id)
        results["menu_path"] = str(menu_path)
        print(f"\n  ✅ menu.json saved → {menu_path}")
        print(f"     Categories: {menu.categories}")
        print(f"     Items:      {len(menu.items)}")
        print(f"     Combos:     {len(menu.combos)}")
    else:
        print_separator("STEP 1 / 3 — Skipping (--prompt-only mode)")
        print("  Loading existing menu.json...")
        try:
            menu = load_menu(restaurant_id)
            print(f"  ✅ Loaded: {len(menu.items)} items")
        except FileNotFoundError:
            print(f"  ❌ No menu.json found for '{restaurant_id}'. Run without --prompt-only first.")
            sys.exit(1)

    # ─── Step 2: Prompt Generation ───────────────────────────────────────────
    print_separator("STEP 2 / 3 — Prompt Architect (Agent 2)")
    system_prompt = generate_prompt(menu)
    prompt_path = save_prompt(system_prompt, restaurant_id)
    results["prompt_path"] = str(prompt_path)
    print(f"\n  ✅ system_prompt.md saved → {prompt_path}")
    print(f"     Length: {len(system_prompt)} characters")

    # ─── Step 3: Image Generation ─────────────────────────────────────────────
    if skip_images:
        print_separator("STEP 3 / 3 — Skipping Images (--skip-images)")
    else:
        print_separator(f"STEP 3 / 3 — Image Generator ({len(menu.items)} items)")
        image_results = generate_all_images(menu, restaurant_id, delay_between=image_delay)
        manifest_path = save_image_manifest(image_results, restaurant_id)
        results["images_generated"] = len(image_results)
        results["manifest_path"] = str(manifest_path)
        print(f"\n  ✅ {len(image_results)}/{len(menu.items)} images generated")
        print(f"     Manifest → {manifest_path}")

    # ─── Summary ─────────────────────────────────────────────────────────────
    print_separator("✅ PIPELINE COMPLETE")
    print(f"\n  Restaurant:    {restaurant_name}")
    print(f"  Restaurant ID: {restaurant_id}")
    print(f"\n  Output files:")
    if results["menu_path"]:
        print(f"    menu.json       → {results['menu_path']}")
    if results["prompt_path"]:
        print(f"    system_prompt   → {results['prompt_path']}")
    if results["manifest_path"]:
        print(f"    image_manifest  → {results['manifest_path']}")

    print(f"\n  ⚙️  To use this restaurant with the Brew voice agent:")
    print(f"     Set environment variable:  RESTAURANT_ID={restaurant_id}")
    print(f"     Then restart the backend:  docker compose up --build backend")
    print()

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the full AI drive-through menu pipeline for any restaurant.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # From a menu photo:
  python pipeline/run_pipeline.py --name "Taco Bell" --id taco_bell_demo --image /path/to/menu.jpg

  # From a URL (Gemini will reason about the restaurant from its training knowledge):
  python pipeline/run_pipeline.py --name "McDonald's" --id mcdonalds_demo --url https://mcdonalds.com

  # Multiple images:
  python pipeline/run_pipeline.py --name "Wendy's" --id wendys_demo --image img1.jpg img2.jpg

  # Fast test (skip images):
  python pipeline/run_pipeline.py --name "Burger King" --id bk_demo --url https://bk.com --skip-images

  # Regenerate prompt only (menu.json must already exist):
  python pipeline/run_pipeline.py --id bk_demo --name "Burger King" --prompt-only
        """
    )
    parser.add_argument("--name", required=False, help="Restaurant display name")
    parser.add_argument("--id", required=True, help="Restaurant ID (snake_case, e.g. taco_bell_demo)")
    parser.add_argument("--image", nargs="+", help="Path(s) to menu image file(s)")
    parser.add_argument("--url", help="Restaurant menu URL")
    parser.add_argument("--skip-images", action="store_true", help="Skip image generation (faster)")
    parser.add_argument("--prompt-only", action="store_true", help="Only run Agent 2 (menu.json must exist)")
    parser.add_argument("--image-delay", type=float, default=1.5, help="Seconds between image API calls (default: 1.5)")

    args = parser.parse_args()

    if args.prompt_only and not args.name:
        # Try to load from existing menu.json
        menu_path = OUTPUT_BASE / args.id / "menu.json"
        if menu_path.exists():
            with open(menu_path) as f:
                data = json.load(f)
            args.name = data.get("restaurant", {}).get("name", args.id)
        else:
            parser.error("--name is required when menu.json doesn't exist")
    elif not args.prompt_only and not args.name:
        parser.error("--name is required")

    if not args.prompt_only and not args.image and not args.url:
        parser.error("Must provide --image or --url (or use --prompt-only if menu.json exists)")

    run_pipeline(
        restaurant_name=args.name,
        restaurant_id=args.id,
        image_paths=args.image,
        url=args.url,
        skip_images=args.skip_images,
        prompt_only=args.prompt_only,
        image_delay=args.image_delay,
    )


if __name__ == "__main__":
    main()
