// Settings, the read token and your profile, shared by every screen; plus a
// small hook that shows cached data at once and refreshes it when it's stale.
import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { logOpenToday } from './badges';
import { Profile } from './interests';
import { buildProfile } from './profile';
import { getToken, isStale, loadSettings, readCache, saveSettings, setToken, Settings, writeCache } from './storage';

type AppState = {
  ready: boolean;
  settings: Settings | null;
  token: string | null;
  profile: Profile | null;
  save: (s: Settings, token?: string | null) => Promise<void>;
  refreshProfile: () => Promise<Profile | null>;
};

const Ctx = createContext<AppState | null>(null);

/** Your keywords and topics alone: no network, so nothing ever waits on it. */
export function quickProfile(s: Settings): Profile {
  const weights: Record<string, number> = {};
  for (const t of [...s.keywords, ...s.topics]) weights[t.toLowerCase()] = 1;
  for (const [t, w] of Object.entries(s.interests ?? {})) weights[t] = Math.max(weights[t] ?? 0, w);
  return { weights, topicIds: [], field: [...(s.field ?? [])] };
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [token, setTok] = useState<string | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);

  useEffect(() => {
    (async () => {
      const [s, t] = await Promise.all([loadSettings(), getToken()]);
      setSettings(s);
      setTok(t);
      setReady(true);
      if (!s) return;
      logOpenToday();
      setProfile(quickProfile(s));             // lists start at once from your keywords...
      try {
        setProfile(await buildProfile(s, t));  // ...and sharpen when your full profile is ready
      } catch {
        /* offline: the quick profile stays */
      }
    })();
  }, []);

  const save = useCallback(async (s: Settings, t?: string | null) => {
    await saveSettings(s);
    if (t !== undefined) {
      await setToken(t);
      setTok(t);
    }
    setSettings(s);
    setProfile(quickProfile(s));
    try {
      setProfile(await buildProfile(s, t === undefined ? token : t, true));
    } catch {
      /* keep the quick profile */
    }
  }, [token]);

  const refreshProfile = useCallback(async () => {
    if (!settings) return null;
    try {
      const p = await buildProfile(settings, token, true);
      setProfile(p);
      return p;
    } catch {
      return null;
    }
  }, [settings, token]);

  return <Ctx.Provider value={{ ready, settings, token, profile, save, refreshProfile }}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useApp outside AppProvider');
  return v;
}

/** Cached data first, then a fresh load when it's older than `hours` (or on pull-to-refresh). */
export function useFeed<T>(key: string, hours: number, load: (p: Profile) => Promise<T>) {
  const { profile } = useApp();
  const [data, setData] = useState<T | null>(null);
  const [at, setAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loaderRef = useRef(load);
  useEffect(() => {
    loaderRef.current = load;
  });

  const refresh = useCallback(async () => {
    if (!profile) return;
    setLoading(true);
    setError(null);
    try {
      const fresh = await loaderRef.current(profile);
      setData(fresh);
      setAt(new Date().toISOString());
      await writeCache(key, fresh);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [key, profile]);

  useEffect(() => {
    let alive = true;
    (async () => {
      const cached = await readCache<T>(key);
      if (!alive) return;
      if (cached) {
        setData(cached.data);
        setAt(cached.at);
      }
      if (profile && (!cached || isStale(cached.at, hours))) refresh();
    })();
    return () => {
      alive = false;
    };
  }, [key, hours, profile, refresh]);

  return { data, at, loading, error, refresh };
}

export function timeAgo(iso?: string | null): string {
  if (!iso) return '';
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
