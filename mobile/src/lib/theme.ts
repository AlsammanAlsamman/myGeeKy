// myGeeKy's colours, the same as the desktop panel and the website.
export const C = {
  bg: '#12121c',
  card: 'rgba(255,255,255,0.05)',
  cardHi: 'rgba(255,255,255,0.09)',
  line: 'rgba(255,255,255,0.10)',
  text: '#f0f0f5',
  muted: 'rgba(240,240,245,0.62)',
  pink: '#ff6fd8',
  violet: '#7a5cff',
  cyan: '#7fd8ff',
  green: '#34d399',
  amber: '#ffc457',
  red: '#f87171',
};

// one letter, one meaning (as on the desktop): P paper, N news, D discussion, A announcement
export const BADGES: Record<string, { label: string; color: string; text: string }> = {
  P: { label: 'paper', color: '#22c55e', text: '#ffffff' },
  N: { label: 'news', color: '#eab308', text: '#1a1a1a' },
  D: { label: 'discussion', color: '#38bdf8', text: '#ffffff' },
  A: { label: 'announcement', color: '#a78bfa', text: '#ffffff' },
};

export const CATEGORY_COLORS: Record<string, string> = { ai: C.pink, science: C.green, tech: C.cyan };
