'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { useRouter } from 'next/navigation';

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';
const API_URL = WS_URL.replace(/^ws/, 'http');

type ProgressStatus = 'idle' | 'running' | 'done' | 'error';

interface MenuItem {
    id: string;
    name: string;
    category: string;
    base_price: number;
    sizes: string[];
    add_ons: string[];
    availability: string;
}

interface ComboItem {
    name: string;
    base_price: number;
    includes: string[];
}

interface MenuData {
    restaurant: { name: string; type: string };
    categories: string[];
    items: MenuItem[];
    combos: ComboItem[];
    modifiers: Record<string, unknown>;
}

export default function SetupPage() {
    const router = useRouter();
    const [restaurantName, setRestaurantName] = useState('');
    const [restaurantId, setRestaurantId] = useState('');
    const [url, setUrl] = useState('');
    const [images, setImages] = useState<File[]>([]);
    const [isDragging, setIsDragging] = useState(false);
    const [inputMode, setInputMode] = useState<'url' | 'image'>('url');
    const [status, setStatus] = useState<ProgressStatus>('idle');
    const [progressMessages, setProgressMessages] = useState<string[]>([]);
    const [jobId, setJobId] = useState('');
    const [menuData, setMenuData] = useState<MenuData | null>(null);
    const [confirming, setConfirming] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const progressEndRef = useRef<HTMLDivElement>(null);

    // Auto-scroll progress
    useEffect(() => {
        progressEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [progressMessages]);

    // Auto-generate restaurant ID from name
    const handleNameChange = (name: string) => {
        setRestaurantName(name);
        setRestaurantId(
            name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') + '_demo'
        );
    };

    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
        const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
        setImages(prev => [...prev, ...files]);
        setInputMode('image');
    }, []);

    const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = Array.from(e.target.files || []);
        setImages(prev => [...prev, ...files]);
        setInputMode('image');
    };

    const removeImage = (index: number) => {
        setImages(prev => prev.filter((_, i) => i !== index));
    };

    const handleSubmit = async () => {
        if (!restaurantName.trim() || !restaurantId.trim()) return;
        if (inputMode === 'url' && !url.trim()) return;
        if (inputMode === 'image' && images.length === 0) return;

        setStatus('running');
        setProgressMessages([]);
        setMenuData(null);

        const formData = new FormData();
        formData.append('restaurant_name', restaurantName);
        formData.append('restaurant_id', restaurantId);
        formData.append('url', inputMode === 'url' ? url : '');
        if (inputMode === 'image') {
            images.forEach(img => formData.append('images', img));
        }

        try {
            const res = await fetch(`${API_URL}/api/pipeline/run`, { method: 'POST', body: formData });
            const { job_id } = await res.json();
            setJobId(job_id);

            // Start SSE stream
            const evtSource = new EventSource(`${API_URL}/api/pipeline/progress/${job_id}`);
            evtSource.onmessage = async (e) => {
                const data = JSON.parse(e.data);
                if (data.type === 'progress') {
                    setProgressMessages(prev => [...prev, data.message]);
                } else if (data.type === 'done') {
                    evtSource.close();
                    // Fetch the extracted menu for confirmation
                    const menuRes = await fetch(`${API_URL}/api/pipeline/menu/${data.restaurant_id}`);
                    const menu = await menuRes.json();
                    setMenuData(menu);
                    setStatus('done');
                } else if (data.type === 'error') {
                    evtSource.close();
                    setStatus('error');
                    setProgressMessages(prev => [...prev, `❌ ${data.message}`]);
                }
            };
            evtSource.onerror = () => {
                evtSource.close();
                if (status !== 'done') setStatus('error');
            };
        } catch (err) {
            setStatus('error');
            setProgressMessages(prev => [...prev, `❌ Failed to start pipeline: ${err}`]);
        }
    };

    const handleConfirm = async () => {
        setConfirming(true);
        try {
            const res = await fetch(`${API_URL}/api/pipeline/confirm/${jobId}`, { method: 'POST' });
            if (res.ok) {
                router.push('/');
            }
        } catch {
            setConfirming(false);
        }
    };

    const categoryColors: Record<string, string> = {};
    const colorPalette = [
        '#6366f1', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#3b82f6', '#ef4444', '#14b8a6', '#f97316',
    ];
    menuData?.categories.forEach((cat, i) => {
        categoryColors[cat] = colorPalette[i % colorPalette.length];
    });

    return (
        <main style={{
            minHeight: '100vh',
            background: 'linear-gradient(135deg, #0a0a0f 0%, #13131f 50%, #0a0a0f 100%)',
            fontFamily: '"Inter", -apple-system, sans-serif',
            color: '#e2e8f0',
            padding: '0',
        }}>
            {/* Header */}
            <div style={{
                borderBottom: '1px solid rgba(99,102,241,0.2)',
                background: 'rgba(15,15,25,0.8)',
                backdropFilter: 'blur(20px)',
                padding: '16px 32px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                position: 'sticky',
                top: 0,
                zIndex: 50,
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <div style={{
                        width: 36, height: 36, borderRadius: 10,
                        background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 18,
                    }}>☕</div>
                    <div>
                        <div style={{ fontWeight: 700, fontSize: 16, letterSpacing: '-0.3px' }}>DriveAI Setup</div>
                        <div style={{ fontSize: 11, color: '#64748b' }}>Restaurant Onboarding</div>
                    </div>
                </div>
            </div>

            <div style={{ maxWidth: 860, margin: '0 auto', padding: '40px 24px' }}>
                {/* Title */}
                <div style={{ textAlign: 'center', marginBottom: 48 }}>
                    <h1 style={{
                        fontSize: 40, fontWeight: 800, letterSpacing: '-1.5px',
                        background: 'linear-gradient(135deg, #e2e8f0 0%, #94a3b8 100%)',
                        WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
                        margin: '0 0 12px',
                    }}>
                        Add a New Restaurant
                    </h1>
                    <p style={{ color: '#64748b', fontSize: 16, margin: 0 }}>
                        Upload a menu photo or paste a URL — Gemini reads and configures everything automatically.
                    </p>
                </div>

                {/* Setup form */}
                {status === 'idle' && (
                    <div style={{
                        background: 'rgba(255,255,255,0.03)',
                        border: '1px solid rgba(255,255,255,0.08)',
                        borderRadius: 20,
                        padding: 36,
                    }}>
                        {/* Name + ID row */}
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
                            <div>
                                <label style={{ display: 'block', fontSize: 13, fontWeight: 500, color: '#94a3b8', marginBottom: 8 }}>
                                    Restaurant Name *
                                </label>
                                <input
                                    value={restaurantName}
                                    onChange={e => handleNameChange(e.target.value)}
                                    placeholder="e.g. Taco Bell, McDonald's"
                                    style={{
                                        width: '100%', padding: '12px 14px', borderRadius: 10,
                                        background: 'rgba(255,255,255,0.05)',
                                        border: '1px solid rgba(255,255,255,0.1)',
                                        color: '#e2e8f0', fontSize: 14, outline: 'none',
                                        boxSizing: 'border-box',
                                    }}
                                />
                            </div>
                            <div>
                                <label style={{ display: 'block', fontSize: 13, fontWeight: 500, color: '#94a3b8', marginBottom: 8 }}>
                                    Restaurant ID (auto-generated)
                                </label>
                                <input
                                    value={restaurantId}
                                    onChange={e => setRestaurantId(e.target.value)}
                                    placeholder="e.g. taco_bell_demo"
                                    style={{
                                        width: '100%', padding: '12px 14px', borderRadius: 10,
                                        background: 'rgba(255,255,255,0.03)',
                                        border: '1px solid rgba(255,255,255,0.06)',
                                        color: '#64748b', fontSize: 14, outline: 'none',
                                        boxSizing: 'border-box',
                                    }}
                                />
                            </div>
                        </div>

                        {/* Mode toggle */}
                        <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
                            {(['url', 'image'] as const).map(mode => (
                                <button key={mode} onClick={() => setInputMode(mode)} style={{
                                    padding: '8px 18px', borderRadius: 8, fontSize: 13, fontWeight: 600,
                                    cursor: 'pointer', transition: 'all 0.2s',
                                    background: inputMode === mode ? 'linear-gradient(135deg,#6366f1,#8b5cf6)' : 'rgba(255,255,255,0.05)',
                                    border: inputMode === mode ? 'none' : '1px solid rgba(255,255,255,0.1)',
                                    color: inputMode === mode ? '#fff' : '#94a3b8',
                                }}>
                                    {mode === 'url' ? '🔗 Menu URL' : '📷 Upload Photo'}
                                </button>
                            ))}
                        </div>

                        {/* URL input */}
                        {inputMode === 'url' && (
                            <input
                                value={url}
                                onChange={e => setUrl(e.target.value)}
                                placeholder="https://www.tacobell.com/food"
                                style={{
                                    width: '100%', padding: '14px 16px', borderRadius: 10,
                                    background: 'rgba(255,255,255,0.05)',
                                    border: '1px solid rgba(255,255,255,0.1)',
                                    color: '#e2e8f0', fontSize: 15, outline: 'none',
                                    boxSizing: 'border-box', marginBottom: 24,
                                }}
                            />
                        )}

                        {/* Drag & drop zone */}
                        {inputMode === 'image' && (
                            <div style={{ marginBottom: 24 }}>
                                <div
                                    onDragOver={e => { e.preventDefault(); setIsDragging(true); }}
                                    onDragLeave={() => setIsDragging(false)}
                                    onDrop={handleDrop}
                                    onClick={() => fileInputRef.current?.click()}
                                    style={{
                                        border: `2px dashed ${isDragging ? '#6366f1' : 'rgba(255,255,255,0.15)'}`,
                                        borderRadius: 16, padding: '48px 24px', textAlign: 'center',
                                        cursor: 'pointer', transition: 'all 0.2s',
                                        background: isDragging ? 'rgba(99,102,241,0.08)' : 'transparent',
                                    }}
                                >
                                    <div style={{ fontSize: 48, marginBottom: 12 }}>📂</div>
                                    <div style={{ color: '#94a3b8', fontSize: 15, fontWeight: 500 }}>
                                        Drop menu photos here or <span style={{ color: '#6366f1' }}>browse</span>
                                    </div>
                                    <div style={{ color: '#475569', fontSize: 12, marginTop: 6 }}>
                                        Supports JPG, PNG — multiple photos OK
                                    </div>
                                    <input ref={fileInputRef} type="file" accept="image/*" multiple onChange={handleFileSelect} style={{ display: 'none' }} />
                                </div>
                                {images.length > 0 && (
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 14 }}>
                                        {images.map((img, i) => (
                                            <div key={i} style={{
                                                display: 'flex', alignItems: 'center', gap: 8,
                                                background: 'rgba(99,102,241,0.1)', borderRadius: 8,
                                                padding: '6px 12px', border: '1px solid rgba(99,102,241,0.3)',
                                            }}>
                                                <span style={{ fontSize: 20 }}>🖼️</span>
                                                <span style={{ fontSize: 13, color: '#c4b5fd', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                    {img.name}
                                                </span>
                                                <button onClick={() => removeImage(i)} style={{
                                                    background: 'none', border: 'none', color: '#ef4444',
                                                    cursor: 'pointer', fontSize: 16, padding: 0, lineHeight: 1,
                                                }}>×</button>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Submit button */}
                        <button
                            onClick={handleSubmit}
                            disabled={!restaurantName || !restaurantId || (inputMode === 'url' ? !url : images.length === 0)}
                            style={{
                                width: '100%', padding: '16px', borderRadius: 12,
                                background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
                                border: 'none', color: '#fff', fontSize: 16, fontWeight: 700,
                                cursor: 'pointer', transition: 'all 0.2s', letterSpacing: '-0.3px',
                                opacity: (!restaurantName || !restaurantId || (inputMode === 'url' ? !url : images.length === 0)) ? 0.4 : 1,
                            }}
                        >
                            🚀 Analyze Menu & Generate Agent
                        </button>
                    </div>
                )}

                {/* Progress view */}
                {(status === 'running' || (status === 'done' && progressMessages.length > 0) || status === 'error') && !menuData && (
                    <div style={{
                        background: 'rgba(0,0,0,0.4)',
                        border: '1px solid rgba(255,255,255,0.08)',
                        borderRadius: 20, padding: 32,
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
                            {status === 'running' && (
                                <div style={{
                                    width: 20, height: 20, border: '2px solid #6366f1',
                                    borderTop: '2px solid transparent', borderRadius: '50%',
                                    animation: 'spin 0.8s linear infinite',
                                }} />
                            )}
                            {status === 'done' && <span style={{ fontSize: 22 }}>✅</span>}
                            {status === 'error' && <span style={{ fontSize: 22 }}>❌</span>}
                            <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>
                                {status === 'running' ? 'Analyzing Menu...' : status === 'done' ? 'Analysis Complete!' : 'Pipeline Failed'}
                            </h2>
                        </div>

                        <div style={{
                            background: '#0a0a0f', borderRadius: 12, padding: 20,
                            fontFamily: 'monospace', fontSize: 13, lineHeight: 1.8,
                            maxHeight: 300, overflowY: 'auto',
                            border: '1px solid rgba(255,255,255,0.05)',
                        }}>
                            {progressMessages.map((msg, i) => (
                                <div key={i} style={{
                                    color: msg.startsWith('❌') ? '#ef4444' : msg.startsWith('✅') ? '#10b981' : msg.startsWith('🎉') ? '#f59e0b' : '#94a3b8',
                                    marginBottom: 4,
                                }}>
                                    {msg}
                                </div>
                            ))}
                            {status === 'running' && (
                                <div style={{ color: '#6366f1', animation: 'pulse 1s infinite' }}>▌</div>
                            )}
                            <div ref={progressEndRef} />
                        </div>
                    </div>
                )}

                {/* Menu confirmation */}
                {status === 'done' && menuData && (
                    <div>
                        <div style={{
                            background: 'rgba(16,185,129,0.06)',
                            border: '1px solid rgba(16,185,129,0.2)',
                            borderRadius: 20, padding: 28, marginBottom: 28,
                        }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                                <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>
                                    ✅ Menu Extracted Successfully
                                </h2>
                                <div style={{ fontSize: 13, color: '#64748b' }}>
                                    Review and confirm to activate
                                </div>
                            </div>
                            <p style={{ color: '#64748b', margin: '8px 0 0', fontSize: 14 }}>
                                {progressMessages[progressMessages.length - 1]}
                            </p>
                        </div>

                        {/* Stats strip */}
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 28 }}>
                            {[
                                { label: 'Menu Items', value: menuData.items.length, icon: '🍔' },
                                { label: 'Categories', value: menuData.categories.length, icon: '📂' },
                                { label: 'Combo Meals', value: menuData.combos.length, icon: '🤝' },
                            ].map(stat => (
                                <div key={stat.label} style={{
                                    background: 'rgba(255,255,255,0.03)',
                                    border: '1px solid rgba(255,255,255,0.07)',
                                    borderRadius: 14, padding: '20px 24px', textAlign: 'center',
                                }}>
                                    <div style={{ fontSize: 32, marginBottom: 6 }}>{stat.icon}</div>
                                    <div style={{ fontSize: 32, fontWeight: 800, letterSpacing: '-1px' }}>{stat.value}</div>
                                    <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{stat.label}</div>
                                </div>
                            ))}
                        </div>

                        {/* Category chips */}
                        <div style={{ marginBottom: 28 }}>
                            <div style={{ fontSize: 13, fontWeight: 600, color: '#64748b', marginBottom: 12, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                Categories
                            </div>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                                {menuData.categories.map(cat => (
                                    <span key={cat} style={{
                                        padding: '6px 14px', borderRadius: 20, fontSize: 13, fontWeight: 600,
                                        background: `${categoryColors[cat]}22`,
                                        border: `1px solid ${categoryColors[cat]}44`,
                                        color: categoryColors[cat],
                                    }}>{cat}</span>
                                ))}
                            </div>
                        </div>

                        {/* Menu items table */}
                        <div style={{
                            background: 'rgba(255,255,255,0.02)',
                            border: '1px solid rgba(255,255,255,0.07)',
                            borderRadius: 16, overflow: 'hidden', marginBottom: 28,
                        }}>
                            <div style={{ padding: '14px 20px', borderBottom: '1px solid rgba(255,255,255,0.05)', fontSize: 13, fontWeight: 600, color: '#64748b', display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr', gap: 16 }}>
                                <span>ITEM NAME</span><span>CATEGORY</span><span>PRICE</span><span>SIZES</span>
                            </div>
                            <div style={{ maxHeight: 380, overflowY: 'auto' }}>
                                {menuData.items.map((item, i) => (
                                    <div key={item.id} style={{
                                        display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr', gap: 16,
                                        padding: '12px 20px', alignItems: 'center',
                                        background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)',
                                        borderBottom: '1px solid rgba(255,255,255,0.03)',
                                        fontSize: 13,
                                    }}>
                                        <span style={{ fontWeight: 500, color: '#e2e8f0' }}>
                                            {item.availability !== 'all_day' && <span style={{ fontSize: 10, color: '#f59e0b', marginRight: 6, fontWeight: 700 }}>◐</span>}
                                            {item.name}
                                        </span>
                                        <span style={{
                                            color: categoryColors[item.category] || '#94a3b8',
                                            fontSize: 11, fontWeight: 600,
                                        }}>{item.category}</span>
                                        <span style={{ color: '#10b981', fontWeight: 600 }}>
                                            ${item.base_price.toFixed(2)}
                                        </span>
                                        <span style={{ color: '#64748b', fontSize: 11 }}>
                                            {item.sizes.length > 0 ? item.sizes.join(', ') : 'Fixed'}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Combos */}
                        {menuData.combos.length > 0 && (
                            <div style={{
                                background: 'rgba(245,158,11,0.05)',
                                border: '1px solid rgba(245,158,11,0.15)',
                                borderRadius: 16, padding: 20, marginBottom: 28,
                            }}>
                                <div style={{ fontSize: 13, fontWeight: 700, color: '#f59e0b', marginBottom: 14, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                    🤝 Combo Meals
                                </div>
                                {menuData.combos.map(combo => (
                                    <div key={combo.name} style={{
                                        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
                                        padding: '10px 0', borderBottom: '1px solid rgba(245,158,11,0.08)',
                                        fontSize: 13,
                                    }}>
                                        <div>
                                            <div style={{ fontWeight: 600, marginBottom: 3 }}>{combo.name}</div>
                                            <div style={{ color: '#64748b', fontSize: 12 }}>{combo.includes.join(' + ')}</div>
                                        </div>
                                        <span style={{ color: '#f59e0b', fontWeight: 700 }}>${combo.base_price.toFixed(2)}</span>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* Confirm button */}
                        <button
                            onClick={handleConfirm}
                            disabled={confirming}
                            style={{
                                width: '100%', padding: '18px', borderRadius: 14,
                                background: confirming ? '#374151' : 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
                                border: 'none', color: '#fff', fontSize: 17, fontWeight: 700,
                                cursor: confirming ? 'default' : 'pointer',
                                letterSpacing: '-0.3px', transition: 'all 0.2s',
                            }}
                        >
                            {confirming ? '⏳ Activating...' : '✅ Confirm & Activate This Restaurant →'}
                        </button>
                        <p style={{ textAlign: 'center', color: '#475569', fontSize: 12, marginTop: 12 }}>
                            You'll be redirected to the ordering page immediately. Previous restaurant configs are preserved.
                        </p>
                    </div>
                )}
            </div>

            <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
        input:focus { border-color: rgba(99,102,241,0.5) !important; box-shadow: 0 0 0 3px rgba(99,102,241,0.1); }
        ::-webkit-scrollbar { width: 6px; } ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
      `}</style>
        </main>
    );
}
