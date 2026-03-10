"""
Brew ADK agent: single streaming agent with order tools.
Tools get per-session order state via contextvar set by the WebSocket handler
(no InvocationContext in signatures so ADK automatic function calling works).
"""
from __future__ import annotations

import os
import contextvars
from google.adk.agents import Agent

from menu import get_system_prompt, get_item_base_price, get_modifier_price_impact, get_item_category
from order_state import get_order_state

# Session identity for the current run_live() task; set in main.py before run_live().
_current_session: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar(
    "brew_session", default=None
)


def set_current_session(user_id: str, session_id: str) -> None:
    """Set session identity for the current async context (call from WebSocket handler before run_live)."""
    _current_session.set((user_id, session_id))


def clear_current_session() -> None:
    """Clear session identity (optional, e.g. after run_live exits)."""
    try:
        _current_session.set(None)
    except LookupError:
        pass


def _state():
    sess = _current_session.get()
    if not sess:
        return None
    return get_order_state(sess[0], sess[1])


import logging
logger = logging.getLogger(__name__)

def add_item(name: str, size: str) -> str:
    """Add an item to the order. Use exact names from the menu (e.g. 'Iced Latte', 'Cake Pop'). For drinks, Size is required (Tall, Grande, or Venti). For food items, ALWAYS pass size='Regular'."""
    logger.info(f"👉 TOOL CALL: add_item(name='{name}', size='{size}')")
    state = _state()
    if not state:
        logger.error("❌ TOOL CALL FAILED: No active order session.")
        return "No active order session."
    base_price = get_item_base_price(name)
    item_id = state.add_item(name, size=size, base_price=base_price)
    # Auto-switch menu view to the category of the added item
    category = get_item_category(name)
    if category and getattr(state, 'menu_context', None) != category:
        state.menu_context = category
        logger.info(f"🔄 AUTO-SWITCH: Menu view → {category} (triggered by adding {name})")
    logger.info(f"✅ TOOL SUCCESS: Added item {item_id} | {size} {name}")
    return f"{{'status': 'success', 'action': 'added_item', 'name': '{name}', 'size': '{size}', 'item_id': '{item_id}'}}"


def remove_item(item_id: str) -> str:
    """Remove an item from the order by its item id."""
    logger.info(f"👉 TOOL CALL: remove_item(item_id='{item_id}')")
    state = _state()
    if not state:
        return "No active order session."
    if state.remove_item(item_id):
        logger.info(f"✅ TOOL SUCCESS: Removed item {item_id}")
        return f"{{'status': 'success', 'action': 'removed_item', 'item_id': '{item_id}'}}"
    logger.error(f"❌ TOOL CALL FAILED: Item {item_id} not found.")
    return f"{{'status': 'error', 'message': 'Item {item_id} not found.'}}"


def add_modifier(
    item_id: str,
    modifier_type: str,
    value: str,
    quantity: str = "1",
) -> str:
    """Add a modifier to an item. modifier_type: one of syrup, milk_swap, topping, ice_level, warming. value: exact name from menu (e.g. 'Oat Milk', 'SF Vanilla', 'Matcha Cold Foam'). quantity: number of pumps/scoops (pass as a string, e.g. '1', '2')."""
    
    try:
        qty_int = int(quantity)
    except ValueError:
        qty_int = 1
        
    logger.info(f"👉 TOOL CALL: add_modifier(item_id='{item_id}', modifier_type='{modifier_type}', value='{value}', quantity={qty_int})")
    state = _state()
    if not state:
        return "No active order session."
    price_impact = get_modifier_price_impact(modifier_type)
    if state.add_modifier(item_id, modifier_type, value, price_impact=price_impact, quantity=qty_int):
        logger.info(f"✅ TOOL SUCCESS: Added modifier {qty_int}x {value} to {item_id}")
        return f"{{'status': 'success', 'action': 'added_modifier', 'item_id': '{item_id}', 'modifier': '{value}', 'qty': {qty_int}}}"
    logger.error(f"❌ TOOL CALL FAILED: Item {item_id} not found.")
    return f"{{'status': 'error', 'message': 'Item {item_id} not found.'}}"


def remove_modifier(item_id: str, modifier_type: str, value: str) -> str:
    """Remove a modifier from an item. modifier_type: one of syrup, milk_swap, topping, ice_level, warming. E.g. remove_modifier(item_id, 'milk_swap', 'Oat Milk')."""
    logger.info(f"👉 TOOL CALL: remove_modifier(item_id='{item_id}', modifier_type='{modifier_type}', value='{value}')")
    state = _state()
    if not state:
        return "No active order session."
    if state.remove_modifier(item_id, modifier_type, value):
        logger.info(f"✅ TOOL SUCCESS: Removed modifier {value} from {item_id}")
        return f"{{'status': 'success', 'action': 'removed_modifier', 'item_id': '{item_id}', 'modifier': '{value}'}}"
    logger.error(f"❌ TOOL CALL FAILED: Modifier {value} or item {item_id} not found.")
    return f"{{'status': 'error', 'message': 'Modifier or item not found.'}}"


def set_modifier(
    item_id: str,
    modifier_type: str,
    value: str,
    quantity: str = "1",
) -> str:
    """Replace all modifiers of this type with one value. modifier_type: one of syrup, milk_swap, topping, ice_level, warming. Use for 'instead of X I want Y' (e.g. set milk_swap to 'Whole Milk'). quantity: pass as string numeral (e.g. '1')."""
    
    try:
        qty_int = int(quantity)
    except ValueError:
        qty_int = 1
        
    logger.info(f"👉 TOOL CALL: set_modifier(item_id='{item_id}', modifier_type='{modifier_type}', value='{value}', quantity={qty_int})")
    state = _state()
    if not state:
        return "No active order session."
    price_impact = get_modifier_price_impact(modifier_type)
    if state.set_modifier(item_id, modifier_type, value, price_impact=price_impact, quantity=qty_int):
        logger.info(f"✅ TOOL SUCCESS: Set modifier {modifier_type} to {value} for {item_id}")
        return f"{{'status': 'success', 'action': 'set_modifier', 'item_id': '{item_id}', 'modifier': '{value}', 'qty': {qty_int}}}"
    logger.error(f"❌ TOOL CALL FAILED: Item {item_id} not found.")
    return f"{{'status': 'error', 'message': 'Item {item_id} not found.'}}"


def set_ice_level(item_id: str, level: str) -> str:
    """Set ice level for an item. level: one of Light, Normal, Extra, No Ice."""
    logger.info(f"👉 TOOL CALL: set_ice_level(item_id='{item_id}', level='{level}')")
    state = _state()
    if not state:
        return "No active order session."
    if state.set_ice_level(item_id, level):
        logger.info(f"✅ TOOL SUCCESS: Set ice level to {level} for {item_id}")
        return f"{{'status': 'success', 'action': 'set_ice_level', 'item_id': '{item_id}', 'level': '{level}'}}"
    logger.error(f"❌ TOOL CALL FAILED: Item {item_id} not found.")
    return f"{{'status': 'error', 'message': 'Item {item_id} not found.'}}"


def undo_last_change() -> str:
    """Revert the last order change (e.g. undo last add or modifier change). Call when customer says 'wait, go back' or 'undo'."""
    logger.info(f"👉 TOOL CALL: undo_last_change()")
    state = _state()
    if not state:
        return "No active order session."
    if state.undo():
        logger.info(f"✅ TOOL SUCCESS: Undid last change.")
        return "{'status': 'success', 'action': 'undo'}"
    logger.error(f"❌ TOOL CALL FAILED: Nothing to undo.")
    return "{'status': 'error', 'message': 'Nothing to undo.'}"


def clear_order() -> str:
    """Clear all items from the current order. Use this when the customer wants to cancel their entire order."""
    logger.info(f"👉 TOOL CALL: clear_order()")
    state = _state()
    if not state:
        return "No active order session."
    if state.clear():
        logger.info(f"✅ TOOL SUCCESS: Order cleared.")
        return "{'status': 'success', 'message': 'Order cleared.'}"
    logger.warning(f"⚠️ TOOL WARNING: Order already empty.")
    return "{'status': 'error', 'message': 'The order is already empty.'}"


def set_menu_view(category: str) -> str:
    """
    Switch the visual menu tab shown on the customer's screen.
    Args:
        category: Must be one of 'Drinks', 'Breakfast', or 'Desserts'.
    """
    valid_categories = ["Drinks", "Breakfast", "Desserts"]
    normalized = category.strip().title()
    if normalized not in valid_categories:
        return f"Error: Category must be one of {valid_categories}"
        
    logger.info(f"👉 TOOL CALL: set_menu_view(category='{normalized}')")
    state = _state()
    if state:
        state.menu_context = normalized
        logger.info(f"✅ TOOL SUCCESS: Switched menu view to {normalized}.")
    else:
        logger.warning(f"⚠️ TOOL WARNING: No active order to attach UI context to.")
        
    return f"Successfully switched menu view to {normalized}."


def get_order_summary() -> str:
    """Get the current order summary and total price to read back to the customer before completing the order."""
    logger.info(f"👉 TOOL CALL: get_order_summary()")
    state = _state()
    if not state:
        return "No active order session."
    items = state.snapshot()
    if not items:
        logger.info(f"✅ TOOL SUCCESS: Order is empty.")
        return "The order is currently empty."
    
    total = 0.0
    summary = []
    for item in items:
        item_total = item.get("base_price", 0.0)
        mods = []
        for m in item.get("modifiers", []):
            qty = m.get("quantity", 1)
            impact = m.get("price_impact", 0.0)
            item_total += impact * qty
            qty_str = f"{qty}x " if qty != 1 else ""
            mods.append(f"{qty_str}{m.get('name')}")
        
        total += item_total
        mod_text = f" (with {', '.join(mods)})" if mods else ""
        summary.append(f"[{item.get('id')}] {item.get('name')}{mod_text}: ${item_total:.2f}")
    
    summary_str = "Current Order:\n" + "\n".join(summary) + f"\n\nTotal Price: ${total:.2f}"
    logger.info(f"✅ TOOL SUCCESS: Successfully generated order summary:\n{summary_str}")
    return summary_str


root_agent = Agent(
    name="brew_agent",
    model=os.environ["BREW_AGENT_MODEL"],  # Set in backend/.env — single source of truth
    description="Drive-thru barista that takes beverage orders with modifiers.",
    instruction=get_system_prompt(),
    tools=[
        add_item,
        remove_item,
        add_modifier,
        remove_modifier,
        set_modifier,
        set_ice_level,
        undo_last_change,
        clear_order,
        set_menu_view,
        get_order_summary,
    ],
)

TOOL_MAP = {t.__name__: t for t in root_agent.tools}
