"""
Load coffee shop menu and build system prompt for the Brew agent.
"""
from __future__ import annotations

import json
from pathlib import Path


def _load_menu() -> dict:
    path = Path(__file__).resolve().parent / "menu.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_system_prompt() -> str:
    """Build strict system instruction with full menu so the model only uses valid items."""
    menu = _load_menu()
    
    prompt_path = Path(__file__).resolve().parent / "system_prompt.md"
    with open(prompt_path, encoding="utf-8") as f:
        prompt_template = f.read().strip()
        
    menu_lines = ["DRINKS:"]
    for d in menu["drinks"]:
        menu_lines.append(f"  - {d['name']} (base ${d['base_price']:.2f}, sizes: {', '.join(d['sizes'])})")
    menu_lines.append("")
    menu_lines.append("MODIFIERS:")
    for mod_type, data in menu["modifiers"].items():
        menu_lines.append(f"  {mod_type}: {', '.join(data['options'])}")
        
    menu_text = "\n".join(menu_lines)
    return prompt_template.format(menu_text=menu_text)


def get_menu_dict() -> dict:
    """Return raw menu for lookup (e.g. base prices)."""
    return _load_menu()


def get_drink_base_price(name: str) -> float:
    """Return base price for a drink by name, or 0.0 if not found."""
    menu = _load_menu()
    for d in menu["drinks"]:
        if d["name"].lower() == name.lower():
            return float(d["base_price"])
    return 0.0


def get_modifier_price_impact(modifier_type: str) -> float:
    """Return default price impact for a modifier type from menu."""
    menu = _load_menu()
    mods = menu.get("modifiers", {})
    if modifier_type in mods:
        return float(mods[modifier_type].get("default_price_impact", 0))
    return 0.0
