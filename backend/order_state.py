"""
Order state manager for Brew. Maintains current order as JSON-serializable items
with modifier support and a short history for undo.

Firestore persistence: every cart mutation is synced to Firestore so that the
cart survives Cloud Run instance restarts and horizontal scaling.
When a new connection arrives for a known session_id, the cart is restored
from Firestore even if this Cloud Run instance has never seen it before.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import os
import uuid
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_GCP_PROJECT = os.getenv("GCP_PROJECT_ID", "brew-488719")
_CART_COLLECTION = "brew_carts"


def _new_id() -> str:
    # Deprecated: UUIDs cause audio models to hallucinate IDs.
    # Now handled internally by OrderState._generate_id()
    pass


def _get_firestore():
    """Lazy-initialise Firestore async client. Returns None if unavailable."""
    try:
        from google.cloud import firestore
        return firestore.AsyncClient(project=_GCP_PROJECT)
    except Exception as e:
        logger.warning("Firestore unavailable, cart will be in-memory only: %s", e)
        return None


# Module-level lazy Firestore client (shared across all sessions in this process)
_firestore_client = None


def _db():
    global _firestore_client
    if _firestore_client is None:
        _firestore_client = _get_firestore()
    return _firestore_client

class OrderState:
    """Order state with undo history, backed by Firestore for persistence."""

    MAX_HISTORY = 10

    def __init__(self, session_key: str = "") -> None:
        self._items: list[dict[str, Any]] = []
        self._history: list[list[dict[str, Any]]] = []
        self.menu_context: str = "Drinks"
        self._session_key = session_key  # used as Firestore doc ID

    def _fire_and_forget_sync(self) -> None:
        """Schedule a Firestore write without blocking the calling coroutine."""
        if not self._session_key:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._sync_to_firestore())
        except RuntimeError:
            pass  # No running loop — skip sync (only happens in unit tests)

    async def _sync_to_firestore(self) -> None:
        """Write current cart snapshot to Firestore."""
        db = _db()
        if not db or not self._session_key:
            return
        try:
            doc_ref = db.collection(_CART_COLLECTION).document(self._session_key)
            await doc_ref.set({
                "items": self._items,
                "history": self._history[-3:],  # keep last 3 undo steps only
                "menu_context": self.menu_context,
            })
        except Exception as e:
            logger.warning("Firestore sync failed: %s", e)

    def _push_history(self) -> None:
        snapshot = copy.deepcopy(self._items)
        self._history.append(snapshot)
        if len(self._history) > self.MAX_HISTORY:
            self._history.pop(0)

    def _generate_id(self) -> str:
        if not hasattr(self, '_next_id'):
            self._next_id = 1
            if self._items:
                max_id = 0
                for item in self._items:
                    if str(item.get("id", "")).startswith("item_"):
                        try:
                            num = int(item["id"].split("_")[-1])
                            if num > max_id:
                                max_id = num
                        except ValueError:
                            pass
                self._next_id = max_id + 1
        item_id = f"item_{self._next_id}"
        self._next_id += 1
        return item_id

    def add_item(self, name: str, size: str | None = None, base_price: float = 0.0, warmed: bool = False) -> str:
        """Add a beverage or food item. Returns the new item id."""
        self._push_history()
        item_id = self._generate_id()
        display_name = f"{name}" + (f" ({size})" if size else "")
        self._items.append({
            "id": item_id,
            "name": display_name,
            "base_name": name,
            "size": size or "medium",
            "base_price": base_price,
            "modifiers": [],
        })
        logger.info(f"🛒 ORDER_STATE: Added item {name} (Size: {size}) [ID: {item_id}]")
        logger.info(f"🛒 ORDER_STATE CURRENT ITEMS: {[i['name'] for i in self._items]}")
        
        if warmed:
            from menu import get_modifier_price_impact
            price_impact = get_modifier_price_impact("warming")
            self.add_modifier(item_id, "warming", "Warmed", price_impact=price_impact, quantity=1)
            
        self._fire_and_forget_sync()
        return item_id

    def remove_item(self, item_id: str) -> bool:
        """Remove item by id. Returns True if found and removed."""
        self._push_history()
        for i, item in enumerate(self._items):
            if item["id"] == item_id:
                removed = self._items.pop(i)
                logger.info(f"🛒 ORDER_STATE: Removed item {removed['name']} [ID: {item_id}]")
                logger.info(f"🛒 ORDER_STATE CURRENT ITEMS: {[i['name'] for i in self._items]}")
                self._fire_and_forget_sync()
                return True
        logger.warning(f"🛒 ORDER_STATE: Attempted to remove non-existent item [ID: {item_id}]")
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
            logger.warning(f"🛒 ORDER_STATE: Attempted to add modifier {name} to non-existent item [ID: {item_id}]")
            return False
        # Prevent duplicate modifiers of the same type+name
        for existing in item["modifiers"]:
            if existing["type"] == modifier_type and existing["name"] == name:
                logger.info(f"🛒 ORDER_STATE: Modifier {name} already exists on {item['name']} [ID: {item_id}], skipping duplicate")
                return True
        self._push_history()
        mod = {
            "type": modifier_type,
            "name": name,
            "price_impact": price_impact,
        }
        if quantity is not None:
            mod["quantity"] = quantity
        item["modifiers"].append(mod)
        logger.info(f"🛒 ORDER_STATE: Attached modifier {name} to {item['name']} [ID: {item_id}]")
        self._fire_and_forget_sync()
        return True

    def remove_modifier(self, item_id: str, modifier_type: str, value: str) -> bool:
        """Remove first matching modifier by type and name."""
        item = self._find_item(item_id)
        if not item:
            logger.warning(f"🛒 ORDER_STATE: Attempted to remove modifier {value} from non-existent item [ID: {item_id}]")
            return False
        self._push_history()
        mods = item["modifiers"]
        for i, m in enumerate(mods):
            if m.get("type") == modifier_type and m.get("name", "").lower() == value.lower():
                removed_mod = mods.pop(i)
                logger.info(f"🛒 ORDER_STATE: Removed modifier {removed_mod['name']} from {item['name']} [ID: {item_id}]")
                self._fire_and_forget_sync()
                return True
        logger.warning(f"🛒 ORDER_STATE: Attempted to remove non-existent modifier {value} from {item['name']} [ID: {item_id}]")
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
            logger.warning(f"🛒 ORDER_STATE: Attempted to set modifier {value} on non-existent item [ID: {item_id}]")
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
        logger.info(f"🛒 ORDER_STATE: Overwrote modifier type {modifier_type} with {value} on {item['name']} [ID: {item_id}]")
        self._fire_and_forget_sync()
        return True

    def set_ice_level(self, item_id: str, level: str) -> bool:
        """Set ice level (light, normal, extra, no_ice). Replaces existing ice_level modifier."""
        return self.set_modifier(item_id, "ice_level", level, 0.0)

    def undo(self) -> bool:
        """Revert to previous state. Returns True if there was history."""
        if not self._history:
            logger.warning(f"🛒 ORDER_STATE: Attempted to undo with no history remaining.")
            return False
        self._items = self._history.pop()
        logger.info(f"🛒 ORDER_STATE: Undid previous action. Restored {len(self._items)} items to cart.")
        self._fire_and_forget_sync()
        return True

    def clear(self) -> bool:
        """Clear all items from the order."""
        if not self._items:
            return False # Nothing to clear
        self._push_history()
        self._items = []
        logger.info(f"🛒 ORDER_STATE: Cleared the order.")
        self._fire_and_forget_sync()
        return True

    def snapshot(self) -> list[dict[str, Any]]:
        """Return full order as list of items for frontend (no history)."""
        return copy.deepcopy(self._items)


# Per-session order state registry for use by ADK tools (key: (user_id, session_id))
_session_states: dict[tuple[str, str], OrderState] = {}


def _session_key(user_id: str, session_id: str) -> str:
    return f"{user_id}__{session_id}"


def get_order_state(user_id: str, session_id: str) -> OrderState | None:
    return _session_states.get((user_id, session_id))


def register_order_state(user_id: str, session_id: str) -> OrderState:
    """Create a new OrderState for this session, keyed so Firestore can persist it."""
    key = _session_key(user_id, session_id)
    state = OrderState(session_key=key)
    _session_states[(user_id, session_id)] = state
    return state


async def restore_order_state(user_id: str, session_id: str) -> OrderState | None:
    """
    Attempt to restore an OrderState from Firestore for a reconnected session.
    This is called when get_order_state returns None (different Cloud Run instance).
    """
    db = _db()
    if not db:
        return None
    key = _session_key(user_id, session_id)
    try:
        doc = await db.collection(_CART_COLLECTION).document(key).get()
        if doc.exists:
            data = doc.to_dict()
            state = OrderState(session_key=key)
            state._items = data.get("items", [])
            state._history = data.get("history", [])
            state.menu_context = data.get("menu_context", "Drinks")
            _session_states[(user_id, session_id)] = state
            logger.info(
                "Restored cart from Firestore for session %s (%d items)",
                session_id, len(state._items)
            )
            return state
    except Exception as e:
        logger.warning("Firestore restore failed: %s", e)
    return None


def unregister_order_state(user_id: str, session_id: str) -> None:
    _session_states.pop((user_id, session_id), None)
