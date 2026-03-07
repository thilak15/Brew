/**
 * Restaurant theme system — maps restaurant type to a color palette.
 * Used by the dynamic /restaurant/[id] page.
 */

export type ThemeColors = {
    primary: string;      // main accent (buttons, active tabs)
    primaryHover: string; // darker hover variant
    accent: string;       // secondary accent
    bg: string;           // page background
    cardBg: string;       // white card background
    border: string;       // card border color
    text: string;         // body text
    subtext: string;      // muted/secondary text
    highlight: string;    // item highlight ring
    headerBg: string;     // sticky header bg
    selection: string;    // text selection bg
    logoEmoji: string;    // emoji shown in the logo
};

const THEMES: Record<string, ThemeColors> = {
    coffee: {
        primary: '#D4A373',
        primaryHover: '#C28E5C',
        accent: '#A3B899',
        bg: '#FAF4ED',
        cardBg: '#FFFFFF',
        border: '#E8DCCB',
        text: '#4A3219',
        subtext: '#8D7B68',
        highlight: '#A3B899',
        headerBg: '#FAF4ED',
        selection: '#D4A373',
        logoEmoji: '☕',
    },
    fast_food: {
        primary: '#E63946',
        primaryHover: '#C1121F',
        accent: '#F4A261',
        bg: '#FFF8F0',
        cardBg: '#FFFFFF',
        border: '#FFE5CC',
        text: '#1D1D1D',
        subtext: '#777',
        highlight: '#F4A261',
        headerBg: '#FFF8F0',
        selection: '#E63946',
        logoEmoji: '🍔',
    },
    mexican: {
        primary: '#2D6A4F',
        primaryHover: '#1B4332',
        accent: '#E9C46A',
        bg: '#F0FFF8',
        cardBg: '#FFFFFF',
        border: '#C3E6D3',
        text: '#1B2D22',
        subtext: '#52796F',
        highlight: '#E9C46A',
        headerBg: '#F0FFF8',
        selection: '#2D6A4F',
        logoEmoji: '🌮',
    },
    chicken: {
        primary: '#E76F51',
        primaryHover: '#CF5A38',
        accent: '#F4A261',
        bg: '#FFF5F0',
        cardBg: '#FFFFFF',
        border: '#FFD6C4',
        text: '#3D1A0A',
        subtext: '#8B5A44',
        highlight: '#F4A261',
        headerBg: '#FFF5F0',
        selection: '#E76F51',
        logoEmoji: '🍗',
    },
    pizza: {
        primary: '#C1121F',
        primaryHover: '#9D0208',
        accent: '#FFB703',
        bg: '#FFF9F0',
        cardBg: '#FFFFFF',
        border: '#FFE5CC',
        text: '#2D0007',
        subtext: '#8B2020',
        highlight: '#FFB703',
        headerBg: '#FFF9F0',
        selection: '#C1121F',
        logoEmoji: '🍕',
    },
    burger: {
        primary: '#E63946',
        primaryHover: '#C1121F',
        accent: '#FFB703',
        bg: '#FFFBF0',
        cardBg: '#FFFFFF',
        border: '#FFE8AA',
        text: '#1D0A00',
        subtext: '#7A5020',
        highlight: '#FFB703',
        headerBg: '#FFFBF0',
        selection: '#E63946',
        logoEmoji: '🍔',
    },
    sandwich: {
        primary: '#588157',
        primaryHover: '#3A5A40',
        accent: '#A7C957',
        bg: '#F8FFF0',
        cardBg: '#FFFFFF',
        border: '#D4EDB0',
        text: '#1B2D1A',
        subtext: '#52796F',
        highlight: '#A7C957',
        headerBg: '#F8FFF0',
        selection: '#588157',
        logoEmoji: '🥪',
    },
    seafood: {
        primary: '#0077B6',
        primaryHover: '#023E8A',
        accent: '#00B4D8',
        bg: '#F0F8FF',
        cardBg: '#FFFFFF',
        border: '#B0D9F0',
        text: '#03071E',
        subtext: '#3A6186',
        highlight: '#00B4D8',
        headerBg: '#F0F8FF',
        selection: '#0077B6',
        logoEmoji: '🦞',
    },
    default: {
        primary: '#6366F1',
        primaryHover: '#4F46E5',
        accent: '#8B5CF6',
        bg: '#F8F9FF',
        cardBg: '#FFFFFF',
        border: '#E0E0FF',
        text: '#1E1B4B',
        subtext: '#6B7280',
        highlight: '#8B5CF6',
        headerBg: '#F8F9FF',
        selection: '#6366F1',
        logoEmoji: '🍽️',
    },
};

export function getTheme(restaurantType: string | undefined): ThemeColors {
    const type = (restaurantType || 'default').toLowerCase().replace(/[^a-z_]/g, '_');
    return THEMES[type] ?? THEMES.default;
}

/** Category emoji map — used in SmartMenu */
export const CATEGORY_EMOJI: Record<string, string> = {
    drinks: '🥤', beverages: '🥤', coffee: '☕', tea: '🍵',
    breakfast: '🍳', brunch: '🥞',
    desserts: '🍪', sweets: '🍰', bakery: '🥐',
    tacos: '🌮', burritos: '🌯', nachos: '🧀',
    burgers: '🍔', sandwiches: '🥪',
    chicken: '🍗', wings: '🍗',
    pizza: '🍕',
    sides: '🍟', fries: '🍟',
    salads: '🥗',
    seafood: '🦞', fish: '🐟',
    combos: '🤝', 'popular combos': '⭐', value: '💰',
    default: '🍽️',
};

export function getCategoryEmoji(category: string): string {
    const key = category.toLowerCase();
    for (const [k, v] of Object.entries(CATEGORY_EMOJI)) {
        if (key.includes(k)) return v;
    }
    return CATEGORY_EMOJI.default;
}
