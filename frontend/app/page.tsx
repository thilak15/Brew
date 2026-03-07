'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { getTheme } from '@/lib/restaurantTheme';

const API_URL = (process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000').replace(/^ws/, 'http');

type Restaurant = {
  restaurant_id: string;
  restaurant_name: string;
  restaurant_type: string;
  category_count: number;
  item_count: number;
  is_builtin: boolean;
  description: string;
};

export default function HomePage() {
  const router = useRouter();
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_URL}/api/pipeline/restaurants`)
      .then(r => r.json())
      .then((data: Restaurant[]) => { setRestaurants(data); setLoading(false); })
      .catch(() => {
        // If API fails, default to just Brew
        setRestaurants([{
          restaurant_id: 'brew',
          restaurant_name: 'Brew',
          restaurant_type: 'coffee',
          category_count: 3,
          item_count: 22,
          is_builtin: true,
          description: 'Your favourite craft coffee drive-thru',
        }]);
        setLoading(false);
      });
  }, []);

  const deleteRestaurant = async (id: string, name: string) => {
    if (!window.confirm(`Are you sure you want to delete ${name}? This cannot be undone.`)) return;

    try {
      const res = await fetch(`${API_URL}/api/pipeline/restaurants/${id}`, { method: 'DELETE' });
      if (res.ok) {
        setRestaurants(prev => prev.filter(r => r.restaurant_id !== id));
      } else {
        const err = await res.json();
        alert(`Failed to delete: ${err.detail || 'Unknown error'}`);
      }
    } catch (e) {
      alert('Error deleting restaurant');
    }
  };

  return (
    <div style={{
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #0f0f1a 100%)',
      fontFamily: '"Inter", -apple-system, sans-serif',
      color: '#e2e8f0',
    }}>
      {/* Header */}
      <header style={{
        padding: '20px 40px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
        background: 'rgba(15,15,26,0.8)', backdropFilter: 'blur(16px)',
        position: 'sticky', top: 0, zIndex: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 40, height: 40, background: 'linear-gradient(135deg,#6366f1,#8b5cf6)',
            borderRadius: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20,
          }}>🚘</div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 18, letterSpacing: '-0.5px' }}>DriveAI</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>AI Drive-Through Platform</div>
          </div>
        </div>
        <button
          onClick={() => router.push('/setup')}
          style={{
            padding: '8px 20px', borderRadius: 10, fontSize: 13, fontWeight: 600,
            background: 'linear-gradient(135deg,#6366f1,#8b5cf6)', color: '#fff',
            border: 'none', cursor: 'pointer', letterSpacing: '-0.2px',
          }}
        >+ Add Restaurant</button>
      </header>

      {/* Hero */}
      <div style={{ textAlign: 'center', padding: '60px 24px 40px' }}>
        <h1 style={{
          fontSize: 52, fontWeight: 900, letterSpacing: '-2px', margin: '0 0 14px',
          background: 'linear-gradient(135deg, #e2e8f0 30%, #94a3b8 100%)',
          WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
        }}>
          Choose Your Drive-Through
        </h1>
        <p style={{ color: '#64748b', fontSize: 18, margin: 0 }}>
          Select a restaurant to start your AI-powered voice order
        </p>
      </div>

      {/* Restaurant grid */}
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 24px 80px' }}>
        {loading ? (
          <div style={{ textAlign: 'center', padding: 80, color: '#64748b' }}>
            <div style={{ fontSize: 48, marginBottom: 16 }}>🔄</div>
            <div style={{ fontSize: 16 }}>Loading restaurants…</div>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 24 }}>
            {restaurants.map(r => {
              const theme = getTheme(r.restaurant_type);
              return (
                <div
                  key={r.restaurant_id}
                  onClick={() => router.push(`/restaurant/${r.restaurant_id}`)}
                  style={{
                    background: `linear-gradient(135deg, ${theme.bg} 0%, ${theme.cardBg} 100%)`,
                    border: `1px solid ${theme.border}`,
                    borderRadius: 24, padding: 28, cursor: 'pointer',
                    transition: 'all 0.25s',
                    position: 'relative', overflow: 'hidden',
                  }}
                  onMouseEnter={e => {
                    (e.currentTarget as HTMLDivElement).style.transform = 'translateY(-6px)';
                    (e.currentTarget as HTMLDivElement).style.boxShadow = `0 20px 50px ${theme.primary}30`;
                    (e.currentTarget as HTMLDivElement).style.borderColor = theme.primary;
                  }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLDivElement).style.transform = '';
                    (e.currentTarget as HTMLDivElement).style.boxShadow = '';
                    (e.currentTarget as HTMLDivElement).style.borderColor = theme.border;
                  }}
                >
                  {/* Accent blob */}
                  <div style={{
                    position: 'absolute', top: -20, right: -20,
                    width: 100, height: 100, borderRadius: '50%',
                    background: `${theme.primary}18`,
                  }} />

                  {/* Logo and Delete Button Row */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
                    <div style={{
                      width: 56, height: 56, background: theme.primary, borderRadius: 16,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 28, boxShadow: `0 4px 14px ${theme.primary}55`,
                    }}>{theme.logoEmoji}</div>

                    {!r.is_builtin && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          deleteRestaurant(r.restaurant_id, r.restaurant_name);
                        }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(239, 68, 68, 0.2)'; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(239, 68, 68, 0.1)'; }}
                        style={{
                          background: 'rgba(239, 68, 68, 0.1)', color: '#ef4444',
                          border: 'none', borderRadius: 8, padding: '6px 10px',
                          fontSize: 12, fontWeight: 600, cursor: 'pointer', zIndex: 2,
                          transition: 'background 0.2s', position: 'relative'
                        }}
                      >
                        🗑️ Delete
                      </button>
                    )}
                  </div>

                  {/* Name + badge */}
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
                    <h2 style={{ fontSize: 22, fontWeight: 800, color: theme.text, margin: 0, letterSpacing: '-0.5px' }}>
                      {r.restaurant_name}
                    </h2>
                    {r.is_builtin && (
                      <span style={{
                        fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 999,
                        background: `${theme.primary}22`, color: theme.primary, letterSpacing: '0.05em',
                      }}>BUILT-IN</span>
                    )}
                  </div>

                  <p style={{ fontSize: 13, color: theme.subtext, margin: '0 0 20px' }}>{r.description}</p>

                  {/* Stats row */}
                  <div style={{ display: 'flex', gap: 16, marginBottom: 20 }}>
                    {[
                      { label: 'Categories', value: r.category_count },
                      { label: 'Items', value: r.item_count },
                    ].map(stat => (
                      <div key={stat.label} style={{
                        flex: 1, background: `${theme.primary}0F`, borderRadius: 10,
                        padding: '10px 14px', textAlign: 'center',
                        border: `1px solid ${theme.primary}22`,
                      }}>
                        <div style={{ fontSize: 22, fontWeight: 800, color: theme.primary }}>{stat.value}</div>
                        <div style={{ fontSize: 11, color: theme.subtext, fontWeight: 500 }}>{stat.label}</div>
                      </div>
                    ))}
                  </div>

                  {/* CTA */}
                  <div style={{
                    width: '100%', padding: '12px', borderRadius: 12, textAlign: 'center',
                    background: theme.primary, color: '#fff', fontWeight: 700, fontSize: 14,
                    letterSpacing: '-0.2px',
                  }}>
                    Start Ordering → 🚙
                  </div>
                </div>
              );
            })}

            {/* Add new card */}
            <div
              onClick={() => router.push('/setup')}
              style={{
                border: '2px dashed rgba(99,102,241,0.3)', borderRadius: 24,
                padding: 28, cursor: 'pointer', transition: 'all 0.25s',
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                gap: 12, minHeight: 280, textAlign: 'center',
              }}
              onMouseEnter={e => {
                (e.currentTarget as HTMLDivElement).style.borderColor = '#6366f1';
                (e.currentTarget as HTMLDivElement).style.background = 'rgba(99,102,241,0.05)';
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLDivElement).style.borderColor = 'rgba(99,102,241,0.3)';
                (e.currentTarget as HTMLDivElement).style.background = 'transparent';
              }}
            >
              <div style={{
                width: 56, height: 56, borderRadius: 16, border: '2px dashed rgba(99,102,241,0.4)',
                display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 28, color: '#6366f1',
              }}>+</div>
              <div style={{ fontWeight: 700, fontSize: 16, color: '#6366f1' }}>Add a Restaurant</div>
              <div style={{ fontSize: 13, color: '#64748b', maxWidth: 200 }}>
                Upload a menu photo or URL — Gemini configures everything automatically
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
