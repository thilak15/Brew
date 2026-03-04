"""
Agent 2: Prompt Architect
=========================
Reads a StructuredMenu from Agent 1 and generates a complete, restaurant-specific
system_prompt.md that the drive-through voice agent can use directly.

The generated prompt:
  - Names the AI after the restaurant ("You are Wendy's AI drive-through assistant")
  - Includes all ORDERING RULES adapted to that restaurant's structure
  - Adds combo upsell logic if combos exist
  - Adds time-of-day rules if breakfast/limited items exist
  - Adds protein/bread swap rules if swappables exist
  - Injects the full menu item list
  - Outputs as a .md file compatible with the existing Brew agent loader

Input:  pipeline/output/{restaurant_id}/menu.json
Output: pipeline/output/{restaurant_id}/system_prompt.md
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from google import genai
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / "backend" / ".env")

from schemas import StructuredMenu
from agent1_menu_analyzer import load_menu

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

OUTPUT_BASE = Path(__file__).resolve().parent / "output"

# ---------------------------------------------------------------------------
# Base template — this is the universal structure every restaurant's prompt
# will follow. The Prompt Architect fills in restaurant-specific sections.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = """\
{persona_block}

CRITICAL — LANGUAGE MIRRORING: You MUST always respond in the same language the customer is speaking. This is automatic and requires no instruction from the customer. If they speak Spanish, you reply in Spanish. If they speak Hindi, you reply in Hindi. If they switch back to English, you switch back too. Never respond in a different language than what was just spoken. The ONLY exception are the internal tool names (add_item, add_modifier, etc.) — those always stay in English.

CRITICAL: You MUST actually execute tool calls. Thinking about calling a tool is NOT the same as calling it. Every order action REQUIRES a real tool call — do NOT just say "Got it" without calling the tool.

GREETING: {greeting}

ORDERING RULES:
{ordering_rules}

MENU SWITCHING: Call `set_menu_view` to change the visual menu tab ONLY when the customer explicitly orders from or asks about a different category ({categories}). Never switch unprompted.

STYLE: Keep confirmations brief. Don't repeat the entire cart after every item. Don't repeat yourself.

=== MENU (use these exact names) ===

{{menu_text}}
"""

ARCHITECT_PROMPT = """You are an expert at writing AI voice agent system prompts for drive-through restaurants.

Given the structured menu data below, generate the specific sections for a drive-through AI prompt.
You must output a JSON object with these exact keys — no other text, no markdown fences:

{{
  "persona_block": "<2-3 sentences defining the AI's name, personality, and role for THIS restaurant>",
  "greeting": "<The exact greeting the AI says when a customer pulls up — specific to this restaurant>",
  "ordering_rules": "<A bullet list (each line starts with '- ') of ALL ordering rules specific to this restaurant. MUST include: size rules, modifier rules, combo upsell rules, swappable rules, breakfast/time rules if applicable, undo/clear/end rules>",
  "categories": "<Comma-separated list of the restaurant's menu category names>"
}}

STRICT RULES FOR ordering_rules:
1. If the restaurant has combos: add a rule — "COMBOS: When customer orders a main item, ask if they want to make it a meal/combo. A combo includes [list what's included]. Combo items can be upgraded in size for an extra charge."
2. If there are breakfast items: add — "BREAKFAST ITEMS: Items marked breakfast_only are only available before [time]. If customer asks after hours, apologize and suggest alternatives."
3. If there are protein swaps: add — "PROTEIN SWAPS: Call set_modifier(item_id, 'protein_swap', '[choice]') when customer wants to change the protein."
4. If there are milk alternatives: add — "MILK SWAPS: If customer wants alternative milk, call set_modifier(item_id, 'milk_swap', '[milk name]') for the relevant item."
5. If items have size options: add — "SIZES: Ask for size if not specified. Size names for this restaurant: [list sizes]."
6. Always include: "MODIFIERS ON EXISTING ITEMS: Use add_modifier or set_modifier with the EXISTING item_id. NEVER call add_item again — that creates a duplicate."
7. Always include: "UNDO: Call undo_last_change when customer says undo or go back."
8. Always include: "CLEAR: Call clear_order to cancel entire order."
9. Always include: "END OF ORDER: When done, call get_order_summary, read back total, say the equivalent of 'please pull up to the window' in the customer's language."
10. Adapt ALL rules to this specific restaurant's menu — don't use generic coffee shop language for a burger joint.

Restaurant menu data:
{menu_json}
"""


def generate_prompt(menu: StructuredMenu, model_name: str = "gemini-2.5-flash") -> str:
    """
    Run Agent 2 to generate a restaurant-specific system prompt from a StructuredMenu.
    Returns the prompt as a string ready to be saved as system_prompt.md.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set in environment")

    client = genai.Client(api_key=api_key)

    # Compact menu summary for the prompt (avoid token overload)
    menu_summary = {
        "restaurant": menu.restaurant.model_dump(),
        "categories": menu.categories,
        "sample_items": [i.model_dump() for i in menu.items[:30]],  # first 30 items
        "combos": [c.model_dump() for c in menu.combos],
        "modifiers": menu.modifiers.model_dump(),
        "upsell_rules": [u.model_dump() for u in menu.upsell_rules],
        "time_based_rules": menu.time_based_rules,
    }

    prompt_txt = ARCHITECT_PROMPT.format(menu_json=json.dumps(menu_summary, indent=2))
    response = client.models.generate_content(
        model=model_name,
        contents=[prompt_txt],
    )

    raw_text = response.text.strip()
    # Strip any markdown fences
    import re
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)

    try:
        sections = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error("Gemini returned invalid JSON for prompt sections:\n%s", raw_text[:1000])
        raise RuntimeError(f"Prompt Architect returned invalid JSON: {e}") from e

    # Build the full system prompt from the template
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        persona_block=sections.get("persona_block", f"You are the AI voice assistant for {menu.restaurant.name}'s drive-through."),
        greeting=sections.get("greeting", f"Hi, welcome to {menu.restaurant.name}! What can I get started for you today?"),
        ordering_rules=sections.get("ordering_rules", ""),
        categories=sections.get("categories", ", ".join(menu.categories)),
    )

    logger.info("✅ System prompt generated (%d chars)", len(system_prompt))
    return system_prompt


def save_prompt(prompt: str, restaurant_id: str) -> Path:
    """Save the generated system prompt to pipeline/output/{restaurant_id}/system_prompt.md"""
    out_dir = OUTPUT_BASE / restaurant_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "system_prompt.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(prompt)
    logger.info("💾 Saved system_prompt.md → %s", out_path)
    return out_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test Agent 2: Prompt Architect")
    parser.add_argument("--id", required=True, help="Restaurant ID (must have menu.json already)")
    args = parser.parse_args()

    menu = load_menu(args.id)
    prompt = generate_prompt(menu)
    path = save_prompt(prompt, args.id)
    print(f"\n✅ System prompt saved to: {path}")
    print("\n--- Preview (first 1000 chars) ---")
    print(prompt[:1000])
