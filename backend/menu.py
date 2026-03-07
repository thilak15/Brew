"""
Load restaurant menu and build system prompt for the drive-through voice agent.

When RESTAURANT_ID is set, loads from:
  pipeline/output/{RESTAURANT_ID}/menu.json
  pipeline/output/{RESTAURANT_ID}/system_prompt.md

Falls back to Brew's own menu.json and system_prompt.md when not set.
"""
from __future__ import annotations

import json
import logging
import os
import contextvars
from pathlib import Path

logger = logging.getLogger(__name__)

# Per-session restaurant override — set by main.py WebSocket handler.
# Takes priority over active_restaurant.json and RESTAURANT_ID env var.
_current_restaurant: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_restaurant", default=None
)

# The RESTAURANT_ID env var controls which restaurant's files to load
# Also checked: pipeline/output/active_restaurant.json (set by the setup UI)
_RESTAURANT_ID_ENV = os.getenv("RESTAURANT_ID", "")

_BACKEND_DIR = Path(__file__).resolve().parent

# In Docker: pipeline is mounted at /pipeline
# Locally: pipeline is a sibling of backend/
_DOCKER_PIPELINE_OUTPUT = Path("/pipeline/output")
_LOCAL_PIPELINE_OUTPUT = _BACKEND_DIR.parent / "pipeline" / "output"
_PIPELINE_OUTPUT = _DOCKER_PIPELINE_OUTPUT if _DOCKER_PIPELINE_OUTPUT.exists() else _LOCAL_PIPELINE_OUTPUT
_ACTIVE_FILE = _PIPELINE_OUTPUT / "active_restaurant.json"


def _get_active_restaurant_id() -> str:
    """Return the active restaurant ID — contextvar (per-session) → file (UI) → env var."""
    # 1. Per-session contextvar set by WebSocket handler (supports simultaneous restaurants)
    ctx_id = _current_restaurant.get()
    if ctx_id:
        return ctx_id
    # 2. File written by setup UI (no restart needed)
    if _ACTIVE_FILE.exists():
        try:
            data = json.loads(_ACTIVE_FILE.read_text())
            rid = data.get("restaurant_id", "")
            if rid:
                return rid
        except Exception:
            pass
    # 3. Env var (CLI-set)
    return os.getenv("RESTAURANT_ID", _RESTAURANT_ID_ENV)


# Module-level alias — re-evaluated on each menu load via _get_active_restaurant_id()
RESTAURANT_ID = _get_active_restaurant_id()


def _get_menu_path() -> Path:
    """Return the path to the active restaurant's menu.json."""
    restaurant_id = _get_active_restaurant_id()
    if restaurant_id:
        pipeline_menu = _PIPELINE_OUTPUT / restaurant_id / "menu.json"
        if pipeline_menu.exists():
            logger.info("Loading menu from pipeline output: %s", pipeline_menu)
            return pipeline_menu
        else:
            logger.warning(
                "RESTAURANT_ID=%s but no menu.json found at %s — falling back to Brew menu",
                restaurant_id, pipeline_menu
            )
    return _BACKEND_DIR / "menu.json"


def _get_prompt_path() -> Path:
    """Return the path to the active restaurant's system_prompt.md."""
    restaurant_id = _get_active_restaurant_id()
    if restaurant_id:
        pipeline_prompt = _PIPELINE_OUTPUT / restaurant_id / "system_prompt.md"
        if pipeline_prompt.exists():
            logger.info("Loading system prompt from pipeline output: %s", pipeline_prompt)
            return pipeline_prompt
        else:
            logger.warning(
                "RESTAURANT_ID=%s but no system_prompt.md found — falling back to Brew prompt",
                restaurant_id
            )
    return _BACKEND_DIR / "system_prompt.md"


def _load_raw_menu() -> dict:
    """Load raw menu JSON from the active source."""
    path = _get_menu_path()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_system_prompt(*args, **kwargs) -> str:
    """
    Load and return the active system prompt with menu text injected.

    For pipeline-generated menus (StructuredMenu schema), builds menu_text
    from the categories/items/modifiers structure.
    For the original Brew menu.json, uses the legacy format.
    """
    raw = _load_raw_menu()
    prompt_path = _get_prompt_path()
    with open(prompt_path, encoding="utf-8") as f:
        prompt_template = f.read().strip()

    # Detect which format we have
    if "items" in raw and "categories" in raw:
        # Pipeline-generated StructuredMenu format
        menu_text = _build_menu_text_from_structured(raw)
    else:
        # Legacy Brew format
        menu_text = _build_menu_text_from_legacy(raw)

    return prompt_template.format(menu_text=menu_text)


def _build_menu_text_from_structured(raw: dict) -> str:
    """Build menu text string from pipeline StructuredMenu schema."""
    lines = []
    items_by_category: dict[str, list] = {}
    for item in raw.get("items", []):
        cat = item.get("category", "Other")
        items_by_category.setdefault(cat, []).append(item)

    for category in raw.get("categories", list(items_by_category.keys())):
        cat_items = items_by_category.get(category, [])
        if not cat_items:
            continue
        lines.append(f"\n{category.upper()}:")
        for item in cat_items:
            size_str = f", sizes: {', '.join(item['sizes'])}" if item.get("sizes") else ""
            avail = item.get("availability", "all_day")
            avail_str = f" [{avail}]" if avail != "all_day" else ""
            lines.append(f"  - {item['name']} (${item.get('base_price', 0):.2f}{size_str}){avail_str}")
            if item.get("add_ons"):
                lines.append(f"    Add-ons: {', '.join(item['add_ons'])}")

    combos = raw.get("combos", [])
    if combos:
        lines.append("\nCOMBO MEALS:")
        for combo in combos:
            lines.append(f"  - {combo['name']} (${combo.get('base_price', 0):.2f}): {', '.join(combo.get('includes', []))}")

    modifiers = raw.get("modifiers", {})
    mod_lines = []
    for key, val in modifiers.items():
        if key == "extra":
            for k, v in val.items():
                if v:
                    mod_lines.append(f"  {k}: {', '.join(v)}")
        elif isinstance(val, list) and val:
            mod_lines.append(f"  {key}: {', '.join(val)}")
    if mod_lines:
        lines.append("\nMODIFIERS:")
        lines.extend(mod_lines)

    return "\n".join(lines)


def _build_menu_text_from_legacy(menu: dict) -> str:
    """Build menu text string from original Brew menu.json format."""
    menu_lines = ["DRINKS:"]
    for d in menu.get("drinks", []):
        menu_lines.append(f"  - {d['name']} (base ${d['base_price']:.2f}, sizes: {', '.join(d['sizes'])})")

    menu_lines.append("\nBREAKFAST:")
    for b in menu.get("breakfast", []):
        menu_lines.append(f"  - {b['name']} (base ${b['base_price']:.2f}, sizes: {', '.join(b['sizes'])})")

    menu_lines.append("\nDESSERTS:")
    for s in menu.get("desserts", []):
        menu_lines.append(f"  - {s['name']} (base ${s['base_price']:.2f}, sizes: {', '.join(s['sizes'])})")

    menu_lines.append("\nMODIFIERS:")
    for mod_type, data in menu.get("modifiers", {}).items():
        menu_lines.append(f"  {mod_type}: {', '.join(data['options'])}")

    return "\n".join(menu_lines)


def get_menu_dict() -> dict:
    """Return raw menu for lookup (e.g. base prices)."""
    return _load_raw_menu()


def get_item_base_price(name: str) -> float:
    """Return base price for an item by name, or 0.0 if not found."""
    raw = _load_raw_menu()
    # Structured pipeline format
    if "items" in raw:
        for item in raw["items"]:
            if item["name"].lower() == name.lower():
                return float(item.get("base_price", 0.0))
    # Legacy Brew format
    for category in ["drinks", "breakfast", "desserts"]:
        for item in raw.get(category, []):
            if item["name"].lower() == name.lower():
                return float(item["base_price"])
    return 0.0


def get_item_category(name: str) -> str | None:
    """Return the display category for an item name, or None."""
    raw = _load_raw_menu()
    # Structured pipeline format
    if "items" in raw:
        for item in raw["items"]:
            if item["name"].lower() == name.lower():
                return item.get("category")
    # Legacy Brew format
    _CATEGORY_MAP = {"drinks": "Drinks", "breakfast": "Breakfast", "desserts": "Desserts"}
    for key, display in _CATEGORY_MAP.items():
        for item in raw.get(key, []):
            if item["name"].lower() == name.lower():
                return display
    return None


def get_modifier_price_impact(modifier_type: str) -> float:
    """Return default price impact for a modifier type from menu."""
    raw = _load_raw_menu()
    # Legacy format only (structured menus handle prices differently)
    mods = raw.get("modifiers", {})
    if modifier_type in mods and isinstance(mods[modifier_type], dict):
        return float(mods[modifier_type].get("default_price_impact", 0))
    return 0.0
