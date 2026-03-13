"use client";

import { useState, useEffect } from "react";
import Image from "next/image";
import { getApiBaseUrl } from "@/lib/backendUrl";

type MenuTab = "Drinks" | "Breakfast" | "Desserts";

type BackendMenuItem = {
  name: string;
};

type BackendMenuResponse = {
  drinks?: BackendMenuItem[];
  breakfast?: BackendMenuItem[];
  desserts?: BackendMenuItem[];
};

const FALLBACK_MENU: Record<MenuTab, string[]> = {
  Drinks: [
    "Iced Latte",
    "Hot Latte",
    "Shaken Espresso",
    "Brown Sugar Shaken Espresso",
    "Americano",
    "Cappuccino",
    "Cold Brew",
    "Matcha Latte",
    "Chai Latte",
    "Mocha",
    "Caramel Macchiato",
    "Frappuccino",
  ],
  Breakfast: [
    "Bacon & Gouda Sandwich",
    "Spinach Feta Wrap",
    "Ham & Swiss Croissant",
    "Egg Bites",
    "Butter Croissant",
  ],
  Desserts: [
    "Chocolate Chip Cookie",
    "Fudge Brownie",
    "Blueberry Muffin",
    "Lemon Loaf",
    "Cake Pop",
  ],
};

function normalizeMenu(menu: BackendMenuResponse | null): Record<MenuTab, string[]> {
  if (!menu) return FALLBACK_MENU;
  const drinks = (menu.drinks ?? []).map((item) => item.name).filter(Boolean);
  const breakfast = (menu.breakfast ?? [])
    .map((item) => item.name)
    .filter(Boolean);
  const desserts = (menu.desserts ?? []).map((item) => item.name).filter(Boolean);
  if (!drinks.length || !breakfast.length || !desserts.length) {
    return FALLBACK_MENU;
  }
  return {
    Drinks: drinks,
    Breakfast: breakfast,
    Desserts: desserts,
  };
}

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

type SmartMenuProps = {
  menuContext?: string;
};

export function SmartMenu({ menuContext }: SmartMenuProps) {
  const [activeTab, setActiveTab] = useState<MenuTab>("Drinks");
  const [menuCategories, setMenuCategories] =
    useState<Record<MenuTab, string[]>>(FALLBACK_MENU);

  const contextLower = String(menuContext ?? "").toLowerCase();

  useEffect(() => {
    const baseUrl = getApiBaseUrl();
    if (!baseUrl) return;
    const controller = new AbortController();
    const loadMenu = async () => {
      try {
        const res = await fetch(`${baseUrl}/menu`, {
          method: "GET",
          signal: controller.signal,
        });
        if (!res.ok) return;
        const data = (await res.json()) as BackendMenuResponse;
        setMenuCategories(normalizeMenu(data));
      } catch {
        // Keep fallback menu if backend menu can't be loaded.
      }
    };
    void loadMenu();
    return () => controller.abort();
  }, []);

  // Update local active tab if the AI sends down a category context switch
  useEffect(() => {
    if (contextLower.includes("breakfast")) {
      setActiveTab("Breakfast");
    } else if (contextLower.includes("desserts")) {
      setActiveTab("Desserts");
    } else if (contextLower.includes("drinks")) {
      setActiveTab("Drinks");
    }
  }, [contextLower]);

  const highlightVegan =
    contextLower.includes("vegan") ||
    contextLower.includes("oat") ||
    contextLower.includes("almond") ||
    contextLower.includes("soy");
  const grayDairy =
    contextLower.includes("oat milk") ||
    contextLower.includes("no dairy");

  return (
    <div className="flex flex-col gap-4 p-6 bg-white h-full relative">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b-2 border-[#FAF4ED] pb-3">
        <h2 className="text-2xl font-bold text-[#4A3219] shrink-0">Menu</h2>

        {/* Category Tabs */}
        <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide">
          {(Object.keys(menuCategories) as Array<MenuTab>).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-1.5 text-sm font-semibold rounded-full transition-colors whitespace-nowrap ${activeTab === tab
                ? "bg-[#D4A373] text-white shadow-sm"
                : "bg-[#FAF4ED] text-[#8D7B68] hover:bg-[#E8DCCB]"
                }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      <ul className="grid grid-cols-1 sm:grid-cols-2 gap-4 overflow-auto pb-4 pr-2 custom-scrollbar">
        {menuCategories[activeTab].map((name) => {
          const isVeganDrink = activeTab === "Drinks" && ["Matcha Latte", "Chai Latte", "Americano", "Cold Brew"].includes(name);

          let className = "flex items-center gap-4 p-3 rounded-2xl border transition-all duration-200 shadow-sm ";
          if (highlightVegan && isVeganDrink) {
            className += " bg-[#E8F3E8] border-[#A3B899] ring-2 ring-[#A3B899]/50 transform -translate-y-1 shadow-md";
          } else if (grayDairy && !isVeganDrink && activeTab === "Drinks") {
            className += " bg-gray-50 border-gray-100 opacity-60 grayscale-[0.5]";
          } else {
            className += " bg-white border-[#E8DCCB] hover:border-[#D4A373] hover:shadow-md hover:-translate-y-1 cursor-default";
          }

          const imgSrc = `/images/menu/${slug(name)}.webp`;
          return (
            <li key={name} className={className}>
              <div className="relative w-14 h-14 shrink-0 bg-[#FAF4ED] rounded-xl p-1 overflow-hidden shadow-inner flex items-center justify-center">
                <Image
                  src={imgSrc}
                  alt={name}
                  width={128}
                  height={128}
                  className="object-cover w-full h-full rounded-lg"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = "none";
                    (e.target as HTMLElement).parentElement!.innerHTML = activeTab === "Drinks" ? "☕️" : activeTab === "Breakfast" ? "🍳" : "🍪";
                  }}
                />
              </div>
              <span className="font-semibold text-[#4A3219] leading-tight flex-1">{name}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
