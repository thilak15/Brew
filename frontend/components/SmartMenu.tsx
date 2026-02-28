"use client";

import Image from "next/image";

const MENU_ITEMS = [
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
];

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

type SmartMenuProps = {
  menuContext?: string;
};

export function SmartMenu({ menuContext }: SmartMenuProps) {
  const contextLower = String(menuContext ?? "").toLowerCase();
  const highlightVegan =
    contextLower.includes("vegan") ||
    contextLower.includes("oat") ||
    contextLower.includes("almond") ||
    contextLower.includes("soy");
  const grayDairy =
    contextLower.includes("oat milk") ||
    contextLower.includes("no dairy");

  return (
    <div className="flex flex-col gap-4 p-6 bg-white h-full">
      <div className="flex items-center gap-3 border-b-2 border-[#FAF4ED] pb-3">
        <h2 className="text-2xl font-bold text-[#4A3219]">Menu</h2>
      </div>
      <ul className="grid grid-cols-1 sm:grid-cols-2 gap-4 overflow-auto pb-4 pr-2 custom-scrollbar">
        {MENU_ITEMS.map((name) => {
          const isVegan = ["Matcha Latte", "Chai Latte", "Americano", "Cold Brew"].includes(name);
          let className = "flex items-center gap-4 p-3 rounded-2xl border transition-all duration-200 shadow-sm ";
          if (highlightVegan && isVegan) {
            className += " bg-[#E8F3E8] border-[#A3B899] ring-2 ring-[#A3B899]/50 transform -translate-y-1 shadow-md";
          } else if (grayDairy && !isVegan) {
            className += " bg-gray-50 border-gray-100 opacity-60 grayscale-[0.5]";
          } else {
            className += " bg-white border-[#E8DCCB] hover:border-[#D4A373] hover:shadow-md hover:-translate-y-1 cursor-default";
          }
          const imgSrc = `/images/menu/${slug(name)}.png`;
          return (
            <li key={name} className={className}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <div className="relative w-14 h-14 shrink-0 bg-[#FAF4ED] rounded-xl p-1 overflow-hidden shadow-inner flex items-center justify-center">
                <img
                  src={imgSrc}
                  alt={name}
                  className="object-cover w-full h-full rounded-lg"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = "none";
                    (e.target as HTMLElement).parentElement!.innerHTML = "☕️";
                  }}
                />
              </div>
              <span className="font-semibold text-[#4A3219] leading-tight">{name}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
