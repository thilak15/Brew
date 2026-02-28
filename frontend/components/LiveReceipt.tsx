"use client";

import type { OrderItem } from "@/lib/orderReducer";
import { orderTotal } from "@/lib/orderReducer";

type LiveReceiptProps = {
  items: OrderItem[];
};

export function LiveReceipt({ items }: LiveReceiptProps) {
  const total = orderTotal(items);

  return (
    <div className="flex flex-col h-full p-6 bg-white relative">
      <div className="flex items-center gap-3 border-b-2 border-dashed border-[#E8DCCB] pb-4 mb-2">
        <h2 className="text-2xl font-bold text-[#4A3219]">Your Order</h2>
      </div>

      <ul className="flex-1 overflow-auto space-y-4 py-2 pr-2 custom-scrollbar">
        {items.length === 0 ? (
          <li className="flex flex-col items-center justify-center h-full text-[#8D7B68] space-y-3 opacity-60">
            <span className="text-4xl">🪴</span>
            <p className="font-medium text-lg">Your cart is empty</p>
          </li>
        ) : (
          items.map((item) => (
            <li key={item.id} className="text-base bg-[#FAF4ED] p-4 rounded-2xl shadow-sm border border-[#E8DCCB]">
              <div className="flex justify-between items-start font-bold text-[#4A3219] mb-1">
                <span>{item.name}</span>
                <span className="text-[#D4A373]">
                  ${(item.base_price + (item.modifiers ?? []).reduce((s, m) => s + (m.price_impact ?? 0) * (m.quantity || 1), 0)).toFixed(2)}
                </span>
              </div>

              {item.modifiers?.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {item.modifiers.map((m, i) => (
                    <li key={i} className="flex justify-between items-center text-sm text-[#8D7B68] bg-white/50 px-2 py-1 rounded-lg">
                      <span className="flex items-center gap-2">
                        <span className="text-xs">↳</span>
                        {m.type}: <strong>{m.quantity && m.quantity > 1 ? `${m.quantity}x ` : ""}{m.name}</strong>
                      </span>
                      {m.price_impact ? <span className="text-xs font-semibold">+${(m.price_impact * (m.quantity || 1)).toFixed(2)}</span> : null}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))
        )}
      </ul>

      {items.length > 0 && (
        <div className="border-t-2 border-dashed border-[#E8DCCB] pt-4 mt-2 flex justify-between items-center bg-[#FAF4ED] p-4 rounded-2xl shadow-inner">
          <span className="text-lg font-bold text-[#8D7B68]">Total</span>
          <span className="text-2xl font-black text-[#A3B899]">${total.toFixed(2)}</span>
        </div>
      )}
    </div>
  );
}
