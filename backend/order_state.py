"""
Order state manager for Brew. Maintains current order as JSON-serializable items
with modifier support and a short history for undo.
"""
from __future__ import annotations

import copy
import uuid
from typing import Any


def _new_id() -> str:
    return f"item_{uuid.uuid4().hex[:12]}"


class OrderState:
    """In-memory order state with undo history."""

    MAX_HISTORY = 10

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []
        self._history: list[list[dict[str, Any]]] = []

    def _push_history(self) -> None:
        snapshot = copy.deepcopy(self._items)
        self._history.append(snapshot)
        if len(self._history) > self.MAX_HISTORY:
            self._history.pop(0)

    def add_item(self, name: str, size: str | None = None, base_price: float = 0.0) -> str:
        """Add a beverage. Returns the new item id."""
        self._push_history()
        item_id = _new_id()
        display_name = f"{name}" + (f" ({size})" if size else "")
        self._items.append({
            "id": item_id,
            "name": display_name,
            "base_name": name,
            "size": size or "medium",
            "base_price": base_price,
            "modifiers": [],
        })
        return item_id

    def remove_item(self, item_id: str) -> bool:
        """Remove item by id. Returns True if found and removed."""
        self._push_history()
        for i, item in enumerate(self._items):
            if item["id"] == item_id:
                self._items.pop(i)
                return True
        return False

    def _find_item(self, item_id: str) -> dict[str, Any] | None:
        for item in self._items:
            if item["id"] == item_id:
                return item
        return None

    def add_modifier(
        self,
        item_id: str,
        modifier_type: str,
        name: str,
        price_impact: float = 0.0,
        quantity: int | None = None,
    ) -> bool:
        """Add a modifier (e.g. syrup, milk_swap, topping)."""
        item = self._find_item(item_id)
        if not item:
            return False
        self._push_history()
        mod = {
            "type": modifier_type,
            "name": name,
            "price_impact": price_impact,
        }
        if quantity is not None:
            mod["quantity"] = quantity
        item["modifiers"].append(mod)
        return True

    def remove_modifier(self, item_id: str, modifier_type: str, value: str) -> bool:
        """Remove first matching modifier by type and name."""
        item = self._find_item(item_id)
        if not item:
            return False
        self._push_history()
        mods = item["modifiers"]
        for i, m in enumerate(mods):
            if m.get("type") == modifier_type and m.get("name", "").lower() == value.lower():
                mods.pop(i)
                return True
        return False

    def set_modifier(
        self,
        item_id: str,
        modifier_type: str,
        value: str,
        price_impact: float = 0.0,
        quantity: int | None = None,
    ) -> bool:
        """Replace all modifiers of this type with a single one (e.g. milk swap)."""
        item = self._find_item(item_id)
        if not item:
            return False
        self._push_history()
        item["modifiers"] = [m for m in item["modifiers"] if m.get("type") != modifier_type]
        mod = {
            "type": modifier_type,
            "name": value,
            "price_impact": price_impact,
        }
        if quantity is not None:
            mod["quantity"] = quantity
        item["modifiers"].append(mod)
        return True

    def set_ice_level(self, item_id: str, level: str) -> bool:
        """Set ice level (light, normal, extra, no_ice). Replaces existing ice_level modifier."""
        return self.set_modifier(item_id, "ice_level", level, 0.0)

    def undo(self) -> bool:
        """Revert to previous state. Returns True if there was history."""
        if not self._history:
            return False
        self._items = self._history.pop()
        return True

    def snapshot(self) -> list[dict[str, Any]]:
        """Return full order as list of items for frontend (no history)."""
        return copy.deepcopy(self._items)


# Per-session order state registry for use by ADK tools (key: (user_id, session_id))
_session_states: dict[tuple[str, str], OrderState] = {}


def get_order_state(user_id: str, session_id: str) -> OrderState | None:
    return _session_states.get((user_id, session_id))


def register_order_state(user_id: str, session_id: str) -> OrderState:
    state = OrderState()
    _session_states[(user_id, session_id)] = state
    return state


def unregister_order_state(user_id: str, session_id: str) -> None:
    _session_states.pop((user_id, session_id), None)
