// Someone at a glance -- a port of the desktop's profile_card.py: their two most
// active repos, their most-starred one, 30 days of activity, their interests,
// and their links elsewhere (only the ones they've put on GitHub).
import { gh, NAME_RE } from './github';

export type LinkKind = 'linkedin' | 'orcid' | 'scholar' | 'researchgate' | 'facebook' | 'x' | 'web';
export type CardRepo = { name: string; url: string; description: string; stars: number; language: string; pushedAt: string };
export type Card = {
  login: string; name: string; avatar: string; bio: string; company: string; location: string;
  followers: number; publicRepos: number; since: string; url: string;
  active: CardRepo[]; top: CardRepo | null; daily: number[]; interests: string[]; links: { kind: LinkKind; url: string }[];
};

const KINDS: [LinkKind, RegExp][] = [
  ['orcid', /(^|\/\/|\.)orcid\.org\//i], ['scholar', /scholar\.google\./i], ['linkedin', /(^|\/\/|\.)linkedin\.com\//i],
  ['facebook', /(^|\/\/|\.)(facebook|fb)\.com\//i], ['x', /(^|\/\/|\.)(twitter|x)\.com\//i], ['researchgate', /researchgate\.net\//i],
];
const ORDER: LinkKind[] = ['linkedin', 'orcid', 'scholar', 'researchgate', 'facebook', 'x', 'web'];

export function kindOf(url: string): LinkKind {
  return KINDS.find(([, re]) => re.test(url))?.[0] ?? 'web';
}

export function links(user: any, socials: any[]): { kind: LinkKind; url: string }[] {
  const found: Partial<Record<LinkKind, string>> = {};
  const add = (raw: string) => {
    let url = (raw || '').trim();
    if (!url) return;
    if (!/^https?:\/\//.test(url)) url = `https://${url}`;
    url = url.replace(/^http:\/\//, 'https://');
    const k = kindOf(url);
    if (!found[k]) found[k] = url;
  };
  for (const s of socials ?? []) add(s?.url ?? '');
  if (user?.twitter_username && !found.x) found.x = `https://x.com/${user.twitter_username}`;
  add(user?.blog ?? '');
  const m = /\b(\d{4}-\d{4}-\d{4}-\d{3}[\dX])\b/.exec(user?.bio ?? '');
  if (m && !found.orcid) found.orcid = `https://orcid.org/${m[1]}`;
  return ORDER.filter((k) => found[k]).map((k) => ({ kind: k, url: found[k]! }));
}

export function daily(events: any[], days = 30, now = new Date()): number[] {
  const counts = new Array(days).fill(0);
  const start = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()) - (days - 1) * 86400000;
  for (const e of events ?? []) {
    const t = Date.parse(e?.created_at ?? '');
    if (Number.isNaN(t)) continue;
    const i = Math.floor((t - start) / 86400000);
    if (i >= 0 && i < days) counts[i] += 1;
  }
  return counts;
}

function interests(repos: any[], n = 8): string[] {
  const topics = new Map<string, number>();
  const langs = new Map<string, number>();
  for (const r of repos) {
    if (r.fork) continue;
    for (const t of r.topics ?? []) topics.set(t.replace(/-/g, ' '), (topics.get(t.replace(/-/g, ' ')) ?? 0) + 1);
    if (r.language) langs.set(r.language, (langs.get(r.language) ?? 0) + 1);
  }
  const by = (m: Map<string, number>) => [...m].sort((a, b) => b[1] - a[1]).map(([k]) => k);
  const out = by(topics).slice(0, n);
  for (const l of by(langs).slice(0, 4)) if (!out.includes(l)) out.push(l);
  return out.slice(0, n);
}

const repo = (r: any): CardRepo => ({
  name: r.name, url: r.html_url, description: (r.description ?? '').slice(0, 160), stars: r.stargazers_count ?? 0,
  language: r.language ?? '', pushedAt: r.pushed_at ?? '',
});

const cache = new Map<string, { at: number; card: Card }>();

export async function fetchCard(login: string, token: string | null): Promise<Card> {
  if (!NAME_RE.test(login)) throw new Error("That isn't a GitHub username.");
  const hit = cache.get(login.toLowerCase());
  if (hit && Date.now() - hit.at < 3600_000) return hit.card;
  const [user, repos] = await Promise.all([
    gh(`/users/${login}`, token), gh<any[]>(`/users/${login}/repos?per_page=100&sort=pushed&type=owner`, token),
  ]);
  const [events, socials] = await Promise.all([
    gh<any[]>(`/users/${login}/events/public?per_page=100`, token).catch(() => []),
    gh<any[]>(`/users/${login}/social_accounts`, token).catch(() => []),
  ]);
  const own = (repos ?? []).filter((r) => !r.fork);
  const active = [...own].sort((a, b) => String(b.pushed_at).localeCompare(String(a.pushed_at))).slice(0, 2);
  const top = own.reduce((best: any, r: any) => (!best || r.stargazers_count > best.stargazers_count ? r : best), null);
  const card: Card = {
    login: user.login, name: user.name ?? '', avatar: user.avatar_url ?? '', bio: (user.bio ?? '').trim().slice(0, 300),
    company: (user.company ?? '').trim(), location: (user.location ?? '').trim(), followers: user.followers ?? 0,
    publicRepos: user.public_repos ?? 0, since: String(user.created_at ?? '').slice(0, 4), url: user.html_url,
    active: active.map(repo), top: top && top.stargazers_count > 0 ? repo(top) : null,
    daily: daily(Array.isArray(events) ? events : []), interests: interests(own), links: links(user, Array.isArray(socials) ? socials : []),
  };
  cache.set(login.toLowerCase(), { at: Date.now(), card });
  return card;
}
