// Your profile on the phone: your keywords and topics (with their meanings from
// the keyword dictionary), your research topics from OpenAlex (via ORCID) and
// the topics on your GitHub repos -- cached for a day.
import { fetchT } from './net';
import { Dict, expand, Profile, Weights } from './interests';
import { isStale, readCache, Settings, writeCache } from './storage';

const DICT_URL = 'https://raw.githubusercontent.com/mygeeky/myGeeKy/main/src/mygeeky/data/keywords.json';
const STOP = new Set(['and', 'the', 'for', 'with', 'studies', 'study', 'research', 'analysis', 'methods']);

export async function loadDictionary(): Promise<Dict | null> {
  const cached = await readCache<Dict>('keywords');
  if (cached && !isStale(cached.at, 24 * 7)) return cached.data;
  try {
    const r = await fetchT(DICT_URL);
    if (!r.ok) throw new Error(String(r.status));
    const d = (await r.json()) as Dict;
    await writeCache('keywords', d);
    return d;
  } catch {
    return cached?.data ?? null;
  }
}

export async function profileFromSources(s: Settings, token: string | null, dict: Dict | null): Promise<Profile> {
  const weights: Weights = { ...expand(dict, [...s.keywords, ...s.topics]) };
  for (const [t, w] of Object.entries(s.interests ?? {})) weights[t] = Math.max(weights[t] ?? 0, w);   // learned on your computer
  for (const t of [...s.keywords, ...s.topics]) weights[t.toLowerCase()] = 1;
  const field: string[] = [];
  const topicIds: { id: string; name: string }[] = [];
  if (/^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/.test(s.orcid)) {          // your research topics, from OpenAlex
    try {
      const r = await fetchT(`https://api.openalex.org/authors/orcid:${s.orcid}?select=id,topics`);
      if (r.ok) {
        for (const t of ((await r.json()).topics ?? []).slice(0, 6)) {
          const id = String(t.id ?? '').split('/').pop() ?? '';
          const name = String(t.display_name ?? '');
          if (/^T\d+$/.test(id)) topicIds.push({ id, name: name.slice(0, 80) });
          if (name) field.push(name);
          for (const w of name.toLowerCase().split(/[\s,]+/)) {
            if (w.length > 4 && !STOP.has(w)) weights[w] = Math.max(weights[w] ?? 0, 0.7);
          }
        }
      }
    } catch {
      /* offline: keep what we have */
    }
  }
  if (s.username) {                                          // the topics on your own repos (2+ repos)
    try {
      const r = await fetchT(`https://api.github.com/users/${encodeURIComponent(s.username)}/repos?per_page=100&sort=pushed`, {
        headers: { Accept: 'application/vnd.github+json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      });
      if (r.ok) {
        const counts: Record<string, number> = {};
        for (const repo of await r.json()) for (const t of repo.topics ?? []) counts[t] = (counts[t] ?? 0) + 1;
        for (const [t, n] of Object.entries(counts)) {
          const p = t.replace(/-/g, ' ');
          if (n >= 2) weights[p] = Math.max(weights[p] ?? 0, 0.7);
        }
      }
    } catch {
      /* fine */
    }
  }
  if (!field.length) field.push(...(s.field ?? []));
  return { weights, topicIds, field };
}

export async function buildProfile(s: Settings, token: string | null, force = false): Promise<Profile> {
  const key = JSON.stringify([s.username, s.orcid, s.keywords, s.topics, s.interests ?? {}]);
  const cached = await readCache<Profile & { key: string }>('profile');
  if (!force && cached && !isStale(cached.at, 24) && cached.data.key === key) return cached.data;
  const profile = await profileFromSources(s, token, await loadDictionary());
  await writeCache('profile', { ...profile, key });
  return profile;
}
