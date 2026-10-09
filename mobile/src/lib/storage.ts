// Settings and cached lists live in AsyncStorage; tokens only in the phone's
// secure store (Android Keystore / iOS Keychain). The web preview has no secure
// store, so there (and only there) tokens fall back to the browser's storage.
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

export type Settings = {
  username: string;
  orcid: string;
  keywords: string[];
  topics: string[];
  exploreShare: number;
  // what your computer learned about you (from "Connect your phone")
  interests: Record<string, number>;
  field: string[];
  desktopBadges: string[];
};

export const DEFAULT_SETTINGS: Settings = {
  username: '', orcid: '', keywords: [], topics: [], exploreShare: 0.2, interests: {}, field: [], desktopBadges: [],
};
const SETTINGS_KEY = 'mygeeky.settings';
const TOKEN_KEY = 'mygeeky_read_token';

export async function loadSettings(): Promise<Settings | null> {
  const raw = await AsyncStorage.getItem(SETTINGS_KEY);
  if (!raw) return null;
  try {
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return null;
  }
}

export async function saveSettings(s: Settings): Promise<void> {
  await AsyncStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
}

export async function getToken(): Promise<string | null> {
  if (Platform.OS === 'web') return globalThis.localStorage?.getItem(TOKEN_KEY) ?? null;
  try {
    return await SecureStore.getItemAsync(TOKEN_KEY);
  } catch {
    // after a reinstall or a phone-backup restore the stored token can't be decrypted:
    // forget it and treat the app as signed out, instead of failing on start
    await SecureStore.deleteItemAsync(TOKEN_KEY).catch(() => undefined);
    return null;
  }
}

export async function setToken(token: string | null): Promise<void> {
  if (Platform.OS === 'web') {
    if (token) globalThis.localStorage?.setItem(TOKEN_KEY, token);
    else globalThis.localStorage?.removeItem(TOKEN_KEY);
    return;
  }
  if (token) await SecureStore.setItemAsync(TOKEN_KEY, token);
  else await SecureStore.deleteItemAsync(TOKEN_KEY);
}

// ---- cached results: { at: ISO time, data }
export async function readCache<T>(key: string): Promise<{ at: string; data: T } | null> {
  const raw = await AsyncStorage.getItem(`mygeeky.cache.${key}`);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export async function writeCache<T>(key: string, data: T): Promise<void> {
  await AsyncStorage.setItem(`mygeeky.cache.${key}`, JSON.stringify({ at: new Date().toISOString(), data }));
}

export function isStale(at: string | undefined, hours: number): boolean {
  if (!at) return true;
  return Date.now() - new Date(at).getTime() > hours * 3600 * 1000;
}

export async function clearAll(): Promise<void> {
  const keys = (await AsyncStorage.getAllKeys()).filter((k) => k.startsWith('mygeeky.'));
  await AsyncStorage.multiRemove(keys);
  await setToken(null);
}
