"""
Brew ADK agent: single streaming agent with order tools.
Tools get per-session order state via contextvar set by the WebSocket handler
(no InvocationContext in signatures so ADK automatic function calling works).
"""
from __future__ import annotations

import os
import contextvars
from google.adk.agents import Agent

from menu import get_system_prompt, get_drink_base_price, get_modifier_price_impact
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


def add_item(name: str, size: str) -> str:
    """Add a beverage to the order. Use exact drink names from the menu (e.g. 'Shaken Espresso', 'Iced Latte'). Size is required (Tall, Grande, or Venti)."""
    state = _state()
    if not state:
        return "No active order session."
    base_price = get_drink_base_price(name)
    item_id = state.add_item(name, size=size, base_price=base_price)
    return f"{{'status': 'success', 'action': 'added_item', 'name': '{name}', 'size': '{size}', 'item_id': '{item_id}'}}"


def remove_item(item_id: str) -> str:
    """Remove an item from the order by its item id."""
    state = _state()
    if not state:
        return "No active order session."
    if state.remove_item(item_id):
        return f"{{'status': 'success', 'action': 'removed_item', 'item_id': '{item_id}'}}"
    return f"{{'status': 'error', 'message': 'Item {item_id} not found.'}}"


def add_modifier(
    item_id: str,
    modifier_type: str,
    value: str,
    quantity: int = 1,
) -> str:
    """Add a modifier to an item. modifier_type: one of syrup, milk_swap, topping, ice_level. value: exact name from menu (e.g. 'Oat Milk', 'SF Vanilla', 'Matcha Cold Foam'). quantity: number of pumps/scoops (default 1)."""
    state = _state()
    if not state:
        return "No active order session."
    price_impact = get_modifier_price_impact(modifier_type)
    if state.add_modifier(item_id, modifier_type, value, price_impact=price_impact, quantity=quantity):
        return f"{{'status': 'success', 'action': 'added_modifier', 'item_id': '{item_id}', 'modifier': '{value}', 'qty': {quantity}}}"
    return f"{{'status': 'error', 'message': 'Item {item_id} not found.'}}"


def remove_modifier(item_id: str, modifier_type: str, value: str) -> str:
    """Remove a modifier from an item. E.g. remove_modifier(item_id, 'milk_swap', 'Oat Milk')."""
    state = _state()
    if not state:
        return "No active order session."
    if state.remove_modifier(item_id, modifier_type, value):
        return f"{{'status': 'success', 'action': 'removed_modifier', 'item_id': '{item_id}', 'modifier': '{value}'}}"
    return f"{{'status': 'error', 'message': 'Modifier or item not found.'}}"


def set_modifier(
    item_id: str,
    modifier_type: str,
    value: str,
    quantity: int = 1,
) -> str:
    """Replace all modifiers of this type with one value. Use for 'instead of X I want Y' (e.g. set milk_swap to 'Whole Milk')."""
    state = _state()
    if not state:
        return "No active order session."
    price_impact = get_modifier_price_impact(modifier_type)
    if state.set_modifier(item_id, modifier_type, value, price_impact=price_impact, quantity=quantity):
        return f"{{'status': 'success', 'action': 'set_modifier', 'item_id': '{item_id}', 'modifier': '{value}', 'qty': {quantity}}}"
    return f"{{'status': 'error', 'message': 'Item {item_id} not found.'}}"


def set_ice_level(item_id: str, level: str) -> str:
    """Set ice level for an item. level: one of Light, Normal, Extra, No Ice."""
    state = _state()
    if not state:
        return "No active order session."
    if state.set_ice_level(item_id, level):
        return f"{{'status': 'success', 'action': 'set_ice_level', 'item_id': '{item_id}', 'level': '{level}'}}"
    return f"{{'status': 'error', 'message': 'Item {item_id} not found.'}}"


def undo_last_change() -> str:
    """Revert the last order change (e.g. undo last add or modifier change). Call when customer says 'wait, go back' or 'undo'."""
    state = _state()
    if not state:
        return "No active order session."
    if state.undo():
        return "{'status': 'success', 'action': 'undo'}"
    return "{'status': 'error', 'message': 'Nothing to undo.'}"


def get_order_summary() -> str:
    """Get the current order summary and total price to read back to the customer before completing the order."""
    state = _state()
    if not state:
        return "No active order session."
    items = state.snapshot()
    if not items:
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
    
    return "Current Order:\n" + "\n".join(summary) + f"\n\nTotal Price: ${total:.2f}"


root_agent = Agent(
    name="brew_agent",
    model=os.getenv("BREW_AGENT_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025"),
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
        get_order_summary,
    ],
)
