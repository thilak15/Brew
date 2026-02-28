export type Modifier = {
  type: string;
  name: string;
  price_impact?: number;
  quantity?: number;
};

export type OrderItem = {
  id: string;
  name: string;
  base_name?: string;
  size?: string;
  base_price: number;
  modifiers: Modifier[];
};

export type ConnectionStatus = "idle" | "connecting" | "open" | "error";
export type AudioMode = "listening" | "thinking" | "speaking" | "idle";

export type BrewState = {
  order: OrderItem[];
  connection: ConnectionStatus;
  mode: AudioMode;
  menuContext?: string;
  transcript?: string;
  error?: string;
};

export type BrewAction =
  | { type: "ORDER_STATE"; payload: OrderItem[] }
  | { type: "CONNECTION"; status: ConnectionStatus; error?: string }
  | { type: "MODE"; mode: AudioMode }
  | { type: "MENU_CONTEXT"; context: string | undefined }
  | { type: "TRANSCRIPT"; text: string | undefined }
  | { type: "ERROR"; message: string };

const initialState: BrewState = {
  order: [],
  connection: "idle",
  mode: "idle",
};

export function brewReducer(state: BrewState, action: BrewAction): BrewState {
  switch (action.type) {
    case "ORDER_STATE":
      return { ...state, order: action.payload };
    case "CONNECTION":
      return {
        ...state,
        connection: action.status,
        error: action.error,
      };
    case "MODE":
      return { ...state, mode: action.mode };
    case "MENU_CONTEXT":
      return { ...state, menuContext: action.context };
    case "TRANSCRIPT":
      return { ...state, transcript: action.text };
    case "ERROR":
      return { ...state, error: action.message };
    default:
      return state;
  }
}

export function getInitialState(): BrewState {
  return { ...initialState };
}

export function orderTotal(items: OrderItem[]): number {
  return items.reduce((sum, item) => {
    const modTotal = (item.modifiers ?? []).reduce(
      (m, mod) => m + (mod.price_impact ?? 0) * (mod.quantity ?? 1),
      0
    );
    return sum + (item.base_price ?? 0) + modTotal;
  }, 0);
}
