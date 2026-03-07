'use client';

import { useReducer, useState, useCallback, useRef, useEffect } from 'react';
import { brewReducer, getInitialState } from '@/lib/orderReducer';
import { useBrewWebSocket } from '@/lib/useBrewWebSocket';
import { startMicCapture, playAudioChunk, prepareAudioPlayback } from '@/lib/audioPipeline';
import { SmartMenu, type DynamicMenuItem } from '@/components/SmartMenu';
import { LiveReceipt } from '@/components/LiveReceipt';
import { AudioVisualizer } from '@/components/AudioVisualizer';
import { getTheme } from '@/lib/restaurantTheme';
import { useRouter, useParams } from 'next/navigation';

const API_URL = (process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000').replace(/^ws/, 'http');
const WELCOME_TRIGGER = "System: A car has just pulled up to the drive-thru speaker. Please greet the customer immediately out loud and ask for their order.";

type MenuData = {
    restaurant: { name: string; type: string; cuisine?: string };
    categories: string[];
    items: DynamicMenuItem[];
};

export default function RestaurantPage() {
    // Next.js 14 pattern: useParams() hook, not use(params)
    const params = useParams() as { restaurant_id: string };
    const restaurant_id = params.restaurant_id as string;
    const router = useRouter();

    const isBrew = restaurant_id === 'brew';
    const [menuData, setMenuData] = useState<MenuData | null>(null);
    const [loading, setLoading] = useState(!isBrew);

    useEffect(() => {
        if (isBrew) return;
        if (!restaurant_id) return;
        fetch(`${API_URL}/api/pipeline/menu/${restaurant_id}`)
            .then(r => { if (!r.ok) throw new Error('Not found'); return r.json(); })
            .then((data: MenuData) => { setMenuData(data); setLoading(false); })
            .catch(() => { setLoading(false); });
    }, [restaurant_id, isBrew]);

    const theme = getTheme(menuData?.restaurant?.type ?? (isBrew ? 'coffee' : undefined));
    const restaurantName = menuData?.restaurant?.name ?? (isBrew ? 'Brew' : restaurant_id);

    const [state, dispatch] = useReducer(brewReducer, getInitialState());
    const [connect, setConnect] = useState(false);
    const [sessionId] = useState(() => {
        if (typeof window === 'undefined') return 'session_new';
        const key = `driveai_session_${restaurant_id}`;
        const stored = localStorage.getItem(key);
        if (stored) return stored;
        const newId = `session_${Math.random().toString(36).substring(2, 9)}`;
        localStorage.setItem(key, newId);
        return newId;
    });
    const [micActive, setMicActive] = useState(false);
    const [autoStarted, setAutoStarted] = useState(false);
    const stopMicRef = useRef<(() => void) | null>(null);

    const { sendAudio, sendText } = useBrewWebSocket({
        restaurant_id,
        session_id: sessionId,
        dispatch,
        connect,
        onAudioChunk: playAudioChunk,
    });

    useEffect(() => {
        if (state.connection === 'idle') {
            stopMicRef.current?.();
            stopMicRef.current = null;
            setMicActive(false);
        }
    }, [state.connection]);

    const startOrder = useCallback(() => {
        prepareAudioPlayback();
        setTimeout(() => sendText(WELCOME_TRIGGER), 500);
        startMicCapture((chunk) => sendAudio(chunk)).then((stop) => {
            stopMicRef.current = stop;
            setMicActive(true);
        });
    }, [sendAudio, sendText]);

    useEffect(() => {
        if (state.connection === 'open' && !micActive && !autoStarted) {
            setAutoStarted(true);
            startOrder();
        }
    }, [state.connection, micActive, autoStarted, startOrder]);

    const endOrder = useCallback(() => {
        stopMicRef.current?.();
        stopMicRef.current = null;
        setMicActive(false);
        setConnect(false);
    }, []);

    const p = theme.primary;

    if (!restaurant_id) {
        return null;
    }

    if (loading) {
        return (
            <div style={{ minHeight: '100vh', background: theme.bg, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'sans-serif' }}>
                <div style={{ textAlign: 'center', color: theme.subtext }}>
                    <div style={{ fontSize: 48, marginBottom: 16 }}>🔄</div>
                    <div style={{ fontSize: 18, fontWeight: 600 }}>Loading menu…</div>
                </div>
            </div>
        );
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh', background: theme.bg, color: theme.text, fontFamily: '"Inter", -apple-system, sans-serif' }}>
            {/* Header */}
            <header style={{
                padding: '12px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                flexWrap: 'wrap', gap: 12, position: 'sticky', top: 0, zIndex: 10,
                background: `${theme.headerBg}CC`, backdropFilter: 'blur(12px)',
                borderBottom: `1px solid ${theme.border}`,
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <button onClick={() => router.push('/')} style={{
                        width: 36, height: 36, borderRadius: 10, border: `1px solid ${theme.border}`,
                        background: theme.cardBg, cursor: 'pointer', fontSize: 18, display: 'flex',
                        alignItems: 'center', justifyContent: 'center',
                    }}>←</button>
                    <div style={{
                        width: 40, height: 40, background: p, borderRadius: 14,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 20, transform: 'rotate(-6deg)',
                    }}>{theme.logoEmoji}</div>
                    <h1 style={{ fontSize: 26, fontWeight: 800, letterSpacing: '-0.5px', color: theme.text, margin: 0 }}>
                        {restaurantName}<span style={{ color: p }}>.</span>
                    </h1>
                </div>

                {/* Drive-Up controls */}
                <div style={{
                    display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
                    background: theme.cardBg, padding: '8px 16px', borderRadius: 999,
                    boxShadow: '0 1px 6px rgba(0,0,0,0.07)', border: `1px solid ${theme.border}`,
                }}>
                    {state.connection === 'idle' ? (
                        <button onClick={() => {
                            dispatch({ type: 'ORDER_STATE', payload: [] });
                            setConnect(true);
                            setAutoStarted(false);
                        }} style={{
                            padding: '8px 22px', borderRadius: 999, background: p, color: '#fff',
                            border: 'none', fontWeight: 700, fontSize: 14, cursor: 'pointer',
                        }}>Drive Up 🚙</button>
                    ) : state.connection === 'open' ? (
                        !micActive ? (
                            <button onClick={startOrder} style={{
                                padding: '8px 22px', borderRadius: 999, background: theme.accent, color: '#fff',
                                border: 'none', fontWeight: 700, fontSize: 14, cursor: 'pointer',
                            }}>Tap to Order 🗣️</button>
                        ) : (
                            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                <AudioVisualizer mode={state.mode} connection={state.connection} />
                                <button onClick={endOrder} style={{
                                    padding: '6px 16px', borderRadius: 999, background: '#FEE2E2', color: '#DC2626',
                                    border: 'none', fontWeight: 600, fontSize: 13, cursor: 'pointer',
                                }}>Pull Forward ➡️</button>
                            </div>
                        )
                    ) : (
                        <span style={{ fontSize: 13, color: theme.subtext }}>
                            <span>⏳</span> Warming up…
                        </span>
                    )}
                    {state.error && (
                        <span style={{ fontSize: 13, fontWeight: 600, color: '#DC2626', background: '#FEE2E2', padding: '4px 12px', borderRadius: 999 }}>
                            ⚠️ {state.error}
                        </span>
                    )}
                </div>
            </header>

            {/* Main 2-column layout */}
            <main style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, padding: 20, maxWidth: 1200, margin: '0 auto', width: '100%', boxSizing: 'border-box' }}>
                <section style={{ background: theme.cardBg, borderRadius: 24, boxShadow: '0 2px 12px rgba(0,0,0,0.06)', border: `1px solid ${theme.border}`, overflow: 'hidden', minHeight: 400, display: 'flex', flexDirection: 'column' }}>
                    <SmartMenu
                        restaurantId={isBrew ? undefined : restaurant_id}
                        menuContext={state.menuContext}
                        categories={isBrew ? undefined : (menuData?.categories ?? [])}
                        items={isBrew ? undefined : (menuData?.items ?? [])}
                        theme={theme}
                    />
                </section>
                <section style={{ background: theme.cardBg, borderRadius: 24, boxShadow: '0 2px 12px rgba(0,0,0,0.06)', border: `1px solid ${theme.border}`, overflow: 'hidden', minHeight: 400, display: 'flex', flexDirection: 'column', position: 'relative' }}>
                    <div style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: 3, background: p, opacity: 0.6 }} />
                    <LiveReceipt items={state.order} />
                </section>
            </main>

            {state.transcript && (
                <footer style={{
                    position: 'fixed', bottom: 20, left: '50%', transform: 'translateX(-50%)',
                    background: `${theme.cardBg}E8`, backdropFilter: 'blur(12px)',
                    boxShadow: '0 4px 24px rgba(0,0,0,0.12)', border: `1px solid ${theme.border}`,
                    padding: '10px 24px', borderRadius: 999, fontSize: 13, fontWeight: 500, color: theme.subtext,
                    maxWidth: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    pointerEvents: 'none',
                }}>
                    &ldquo;{state.transcript}&rdquo;
                </footer>
            )}
        </div>
    );
}
