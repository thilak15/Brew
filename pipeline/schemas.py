"""
Pydantic schemas for structuring and validating the output of Agent 1 (Menu Analyzer).
These ensure that the menu.json output always has a consistent, reliable format
that Agents 2 and 3 can depend on.
"""
from __future__ import annotations

from typing import Any, Union
from pydantic import BaseModel, Field, field_validator, model_validator


class MenuModifiers(BaseModel):
    """Key-value map of modifier types to their available options."""
    # Common modifiers — each is optional since not every restaurant has them
    milk_swap: list[str] = Field(default_factory=list, description="Alternative milk options")
    sauces: list[str] = Field(default_factory=list, description="Available sauces/dressings")
    toppings: list[str] = Field(default_factory=list, description="Extra add-on toppings")
    ice_level: list[str] = Field(default_factory=list, description="Ice level options")
    protein_swap: list[str] = Field(default_factory=list, description="Protein alternatives")
    bread_swap: list[str] = Field(default_factory=list, description="Bread/bun alternatives")
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Any store-specific modifier types not covered above"
    )

    @field_validator("milk_swap", "sauces", "toppings", "ice_level", "protein_swap", "bread_swap", mode="before")
    @classmethod
    def normalize_lists(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return [str(x) for x in v]
        if isinstance(v, bool):
            return ["available"] if v else []
        if v in (None, {}, "", []):
            return []
        return [str(v)]

    @field_validator("extra", mode="before")
    @classmethod
    def normalize_extra(cls, v: Any) -> dict[str, list[str]]:
        """Convert non-list values (e.g. prices as floats) to string lists."""
        if not isinstance(v, dict):
            return {}
        result = {}
        for key, val in v.items():
            if isinstance(val, list):
                result[key] = [str(x) for x in val]
            else:
                # e.g. {"extra_meat": 1.0} → {"extra_meat": ["+$1.00"]}
                try:
                    result[key] = [f"+${float(val):.2f}"]
                except (TypeError, ValueError):
                    result[key] = [str(val)]
        return result


class SwapOptions(BaseModel):
    """What can be swapped on a specific item."""
    protein: list[str] = Field(default_factory=list)
    bread: list[str] = Field(default_factory=list)
    sauce: list[str] = Field(default_factory=list)
    milk: list[str] = Field(default_factory=list)
    other: dict[str, Any] = Field(default_factory=dict)

    @field_validator("protein", "bread", "sauce", "milk", mode="before")
    @classmethod
    def normalize_lists(cls, v: Any) -> list[str]:
        if isinstance(v, list):
            return [str(x) for x in v]
        if isinstance(v, bool):
            return ["available"] if v else []
        if v in (None, {}, "", []):
            return []
        return [str(v)]

    @field_validator("other", mode="before")
    @classmethod
    def normalize_other(cls, v: Any) -> dict[str, list[str]]:
        if not isinstance(v, dict):
            return {}
        result = {}
        for key, val in v.items():
            if isinstance(val, list):
                result[key] = [str(x) for x in val]
            elif isinstance(val, bool):
                result[key] = ["available"] if val else []
            elif val in (None, {}, ""):
                result[key] = []
            else:
                try:
                    result[key] = [f"+${float(val):.2f}"]
                except (TypeError, ValueError):
                    result[key] = [str(val)]
        return result


class MenuItem(BaseModel):
    """A single menu item — drink, food, side, or dessert."""
    id: str = Field(description="Snake_case unique identifier, e.g. 'big_mac'")
    name: str = Field(description="Display name as it appears on the menu")
    category: str = Field(description="Category name: Drinks, Burgers, Sides, etc.")
    description: str = Field(default="", description="Brief item description")
    base_price: float = Field(description="Starting price in USD")
    sizes: list[str] = Field(
        default_factory=list,
        description="Available sizes e.g. ['Small', 'Medium', 'Large'] or ['Tall', 'Grande', 'Venti']"
    )
    add_ons: list[str] = Field(
        default_factory=list,
        description="Things that can be added extra e.g. ['Extra Cheese', 'Add Avocado']"
    )
    swappables: SwapOptions = Field(
        default_factory=SwapOptions,
        description="What can be substituted on this item"
    )
    availability: str = Field(
        default="all_day",
        description="When this is available: 'all_day', 'breakfast_only', 'limited_time', etc."
    )
    is_combo_eligible: bool = Field(
        default=False,
        description="Can this item be ordered as part of a combo meal?"
    )

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v)


class ComboMeal(BaseModel):
    """A combo/meal deal that bundles multiple items."""
    id: str
    name: str
    description: str = ""
    base_price: float
    includes: list[str] = Field(description="Item names included in the base combo")
    upgrade_options: dict[str, Any] = Field(
        default_factory=dict,
        description="What can be upgraded e.g. {'size': ['Medium→Large (+$0.50)'], 'drink': ['any fountain drink']}"
    )
    availability: str = Field(default="all_day")

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v)

    @field_validator("upgrade_options", mode="before")
    @classmethod
    def normalize_upgrade_options(cls, v: Any) -> dict[str, list[str]]:
        """Normalize any non-list values in upgrade_options to string lists."""
        if not isinstance(v, dict):
            return {}
        result = {}
        for key, val in v.items():
            if isinstance(val, list):
                result[key] = [str(x) for x in val]
            elif isinstance(val, bool):
                result[key] = ["available"] if val else []
            else:
                try:
                    result[key] = [f"+${float(val):.2f}"]
                except (TypeError, ValueError):
                    result[key] = [str(val)]
        return result


class UpsellRule(BaseModel):
    """An upsell suggestion rule for the AI to follow."""
    trigger: str = Field(description="When to trigger this, e.g. 'When customer orders a burger'")
    suggestion: str = Field(description="What to suggest, e.g. 'Ask if they want to make it a meal'")


class RestaurantInfo(BaseModel):
    """Metadata about the restaurant."""
    restaurant_id: str
    name: str
    type: str = Field(description="e.g. 'burger', 'coffee', 'mexican', 'pizza', 'chicken'")
    currency: str = Field(default="USD")
    drive_through: bool = Field(default=True)
    notes: str = Field(default="", description="Any special notes about this restaurant's ordering system")


class StructuredMenu(BaseModel):
    """
    The complete output of Agent 1 (Menu Analyzer).
    This is the universal schema for any restaurant's menu.
    """
    restaurant: RestaurantInfo
    categories: list[str] = Field(description="Ordered list of all menu categories")
    items: list[MenuItem]
    combos: list[ComboMeal] = Field(default_factory=list)
    modifiers: MenuModifiers = Field(default_factory=MenuModifiers)
    upsell_rules: list[UpsellRule] = Field(default_factory=list)
    time_based_rules: list[str] = Field(
        default_factory=list,
        description="Time-of-day rules e.g. 'Breakfast items only available before 11am'"
    )

    def to_agent_menu_text(self) -> str:
        """Render the menu in a compact text format for injection into the system prompt."""
        lines = []
        for category in self.categories:
            cat_items = [i for i in self.items if i.category == category]
            if not cat_items:
                continue
            lines.append(f"\n{category.upper()}:")
            for item in cat_items:
                size_str = f", sizes: {', '.join(item.sizes)}" if item.sizes else ""
                avail = f" [{item.availability}]" if item.availability != "all_day" else ""
                lines.append(f"  - {item.name} (${item.base_price:.2f}{size_str}){avail}")
                if item.add_ons:
                    lines.append(f"    Add-ons: {', '.join(item.add_ons)}")

        if self.combos:
            lines.append("\nCOMBO MEALS:")
            for combo in self.combos:
                lines.append(f"  - {combo.name} (${combo.base_price:.2f}): {', '.join(combo.includes)}")

        # Modifiers
        mod_lines = []
        if self.modifiers.milk_swap:
            mod_lines.append(f"  milk_swap: {', '.join(self.modifiers.milk_swap)}")
        if self.modifiers.sauces:
            mod_lines.append(f"  sauces: {', '.join(self.modifiers.sauces)}")
        if self.modifiers.ice_level:
            mod_lines.append(f"  ice_level: {', '.join(self.modifiers.ice_level)}")
        if self.modifiers.toppings:
            mod_lines.append(f"  toppings: {', '.join(self.modifiers.toppings)}")
        for k, v in self.modifiers.extra.items():
            mod_lines.append(f"  {k}: {', '.join(v)}")
        if mod_lines:
            lines.append("\nMODIFIERS:")
            lines.extend(mod_lines)

        return "\n".join(lines)
