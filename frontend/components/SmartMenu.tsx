"use client";

import Image from "next/image";
import { useState, useEffect } from "react";
import type { ThemeColors } from "@/lib/restaurantTheme";
import { getCategoryEmoji } from "@/lib/restaurantTheme";

// ── Legacy Brew hardcoded data (used when no menu prop is passed) ──────────────
const BREW_MENU: Record<string, string[]> = {
  Drinks: [
    "Iced Latte", "Hot Latte", "Shaken Espresso", "Brown Sugar Shaken Espresso",
    "Americano", "Cappuccino", "Cold Brew", "Matcha Latte",
    "Chai Latte", "Mocha", "Caramel Macchiato", "Frappuccino",
  ],
  Breakfast: [
    "Bacon & Gouda Sandwich", "Spinach Feta Wrap",
    "Ham & Swiss Croissant", "Egg Bites", "Butter Croissant",
  ],
  Desserts: [
    "Chocolate Chip Cookie", "Fudge Brownie",
    "Blueberry Muffin", "Lemon Loaf", "Cake Pop",
  ],
};

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

const API_URL = (process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000').replace(/^ws/, 'http');

export type DynamicMenuItem = {
  id: string;
  name: string;
  category: string;
  base_price?: number;
  sizes?: string[];
  availability?: string;
};

type SmartMenuProps = {
  menuContext?: string;
  // Dynamic mode (pipeline restaurants)
  restaurantId?: string;
  categories?: string[];
  items?: DynamicMenuItem[];
  theme?: ThemeColors;
};

const DEFAULT_THEME: ThemeColors = {
  primary: "#D4A373", primaryHover: "#C28E5C", accent: "#A3B899",
  bg: "#FAF4ED", cardBg: "#FFFFFF", border: "#E8DCCB",
  text: "#4A3219", subtext: "#8D7B68", highlight: "#A3B899",
  headerBg: "#FAF4ED", selection: "#D4A373", logoEmoji: "☕",
};

export function SmartMenu({ menuContext, restaurantId, categories, items, theme = DEFAULT_THEME }: SmartMenuProps) {
  const isDynamic = !!(categories && items);

  // ── Tab state ──────────────────────────────────────────────────────────────
  const tabList = isDynamic ? categories! : Object.keys(BREW_MENU);
  const [activeTab, setActiveTab] = useState(tabList[0] ?? "");

  // Reset tab when restaurant changes
  useEffect(() => {
    setActiveTab(tabList[0] ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categories?.join(",")]);

  const contextLower = String(menuContext ?? "").toLowerCase();

  // AI-driven tab switch
  useEffect(() => {
    if (!contextLower) return;
    const match = tabList.find(t => contextLower.includes(t.toLowerCase()));
    if (match) setActiveTab(match);
  }, [contextLower, tabList]);

  // Brew-specific dietary highlights (legacy only)
  const highlightVegan =
    !isDynamic && (contextLower.includes("vegan") || contextLower.includes("oat") ||
      contextLower.includes("almond") || contextLower.includes("soy"));
  const grayDairy = !isDynamic && (contextLower.includes("oat milk") || contextLower.includes("no dairy"));

  // ── Render items for active tab ────────────────────────────────────────────
  const activeItems: string[] = isDynamic
    ? items!.filter(i => i.category.toLowerCase() === activeTab.toLowerCase()).map(i => i.name)
    : BREW_MENU[activeTab as keyof typeof BREW_MENU] ?? [];

  const activeItemData = isDynamic
    ? items!.filter(i => i.category.toLowerCase() === activeTab.toLowerCase())
    : null;

  const p = theme.primary;
  const pt = theme.text;
  const ps = theme.subtext;
  const pb = theme.border;
  const pbg = theme.bg;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: 24, background: theme.cardBg, height: "100%", position: "relative" }}>
      {/* Header row */}
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 12, borderBottom: `2px solid ${pbg}`, paddingBottom: 12 }}>
        <h2 style={{ fontSize: 22, fontWeight: 800, color: pt, margin: 0 }}>Menu</h2>
        {/* Category tabs */}
        <div style={{ display: "flex", gap: 8, overflowX: "auto", paddingBottom: 2 }}>
          {tabList.map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                padding: "5px 14px", fontSize: 13, fontWeight: 600, borderRadius: 999,
                border: "none", cursor: "pointer", whiteSpace: "nowrap", transition: "all 0.15s",
                background: activeTab === tab ? p : pbg,
                color: activeTab === tab ? "#fff" : ps,
              }}
            >
              {getCategoryEmoji(tab)} {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Items grid */}
      <ul style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, overflowY: "auto", paddingBottom: 8, margin: 0, listStyle: "none", padding: 0 }}>
        {activeItems.map((name, idx) => {
          const itemData = activeItemData?.[idx];
          const isVeganDrink = !isDynamic && activeTab === "Drinks" &&
            ["Matcha Latte", "Chai Latte", "Americano", "Cold Brew"].includes(name);

          let borderColor = pb;
          let bgColor = theme.cardBg;
          let transform = "";
          let opacity = 1;
          const shadow = "0 1px 4px rgba(0,0,0,0.06)";

          if (highlightVegan && isVeganDrink) {
            borderColor = theme.highlight;
            bgColor = `${theme.highlight}18`;
            transform = "translateY(-2px)";
          } else if (grayDairy && !isVeganDrink && activeTab === "Drinks") {
            opacity = 0.5;
          }

          const imgSrc = isDynamic && restaurantId
            ? `/api/pipeline/images/${restaurantId}/${slug(name)}.png`
            : `/images/menu/${slug(name)}.png`;

          return (
            <li key={name} style={{
              display: "flex", alignItems: "center", gap: 12, padding: "10px 12px",
              borderRadius: 16, border: `1px solid ${borderColor}`, background: bgColor,
              boxShadow: shadow, transition: "all 0.2s", opacity, transform, cursor: "default",
            }}>
              <div style={{
                position: "relative", width: 52, height: 52, flexShrink: 0, background: pbg,
                borderRadius: 12, overflow: "hidden", display: "flex",
                alignItems: "center", justifyContent: "center", fontSize: 26,
              }}>
                <Image
                  src={imgSrc}
                  alt={name}
                  fill
                  sizes="52px"
                  style={{ objectFit: "cover" }}
                  onError={(e) => {
                    const el = e.target as HTMLImageElement;
                    el.style.display = "none";
                  }}
                />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, color: pt, fontSize: 13, lineHeight: 1.3 }}>{name}</div>
                {itemData?.base_price !== undefined && (
                  <div style={{ fontSize: 12, color: p, fontWeight: 700, marginTop: 2 }}>
                    ${itemData.base_price.toFixed(2)}
                    {itemData.sizes && itemData.sizes.length > 0 && (
                      <span style={{ color: ps, fontWeight: 400, marginLeft: 4 }}>· {itemData.sizes.join(" / ")}</span>
                    )}
                  </div>
                )}
                {itemData?.availability && itemData.availability !== "all_day" && (
                  <div style={{ fontSize: 10, color: "#f59e0b", fontWeight: 700, marginTop: 1 }}>⏰ {itemData.availability}</div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
