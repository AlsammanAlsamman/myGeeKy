// The orbit's planets: what each one is, and its list of things, built from the feeds.
import type Ionicons from '@expo/vector-icons/Ionicons';
import { timeAgo } from './app-state';
import { Repo } from './github';
import { Headline, kindOf } from './headlines';
import { Event } from './live';
import { Launch } from './market';
import { Model } from './models';
import { Person } from './people';
import { Paper } from './research';
import { BADGES } from './theme';

export type IconName = keyof typeof Ionicons.glyphMap;
export type SectionId = 'live' | 'people' | 'activity' | 'signals' | 'news' | 'papers' | 'repos' | 'models' | 'launches' | 'you';

export type Section = { id: SectionId; label: string; color: string; icon: IconName; about: string };

export const SECTIONS: Record<SectionId, Section> = {
  live: { id: 'live', label: 'Live', color: '#ff6fd8', icon: 'flash-outline', about: 'New faces and the latest moves around you.' },
  people: { id: 'people', label: 'People', color: '#7fd8ff', icon: 'people-outline', about: 'People building the tools of your field, and who follows you.' },
  activity: { id: 'activity', label: 'Activity', color: '#34d399', icon: 'pulse-outline', about: 'What the people you follow are doing on GitHub.' },
  signals: { id: 'signals', label: 'Signals', color: '#a78bfa', icon: 'radio-outline', about: 'Private thank-yous and collab invites between myGeeKy users.' },
  news: { id: 'news', label: 'News', color: '#eab308', icon: 'newspaper-outline', about: 'AI labs, journals and the tech press, ranked by your interests.' },
  papers: { id: 'papers', label: 'Papers', color: '#22c55e', icon: 'document-text-outline', about: 'Rising in your field: papers gaining citations fastest.' },
  repos: { id: 'repos', label: 'Repos', color: '#7fd8ff', icon: 'git-branch-outline', about: 'The popular, active projects your field runs on.' },
  models: { id: 'models', label: 'AI models', color: '#ffc457', icon: 'hardware-chip-outline', about: 'Trending on Hugging Face: your field first, then everywhere.' },
  launches: { id: 'launches', label: 'Launches', color: '#ff6fd8', icon: 'rocket-outline', about: 'Today on Product Hunt, the ones in your field first.' },
  you: { id: 'you', label: 'You', color: '#ffd24a', icon: 'person-outline', about: 'Your model, your badges and your settings.' },
};

export const INNER: SectionId[] = ['live', 'people', 'activity', 'signals'];
export const OUTER: SectionId[] = ['news', 'papers', 'repos', 'models', 'launches'];
export const RING_NAME = { inner: 'YOUR CIRCLE', outer: 'THE WORLD', you: 'THE CENTRE' };

export type Row = {
  id: string; title: string; sub: string; right?: string; url: string; action: string;
  avatar?: string; letter?: string; letterBg?: string; letterFg?: string; login?: string;
  kind: string; cat?: string; explore?: boolean;      // what opening it counts as, for badges
};

const fmt = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n));
const profile = (login: string) => `https://github.com/${login}`;

function eventRow(e: Event): Row {
  return {
    id: `e${e.id}`, title: e.actor, sub: `${e.icon} ${e.verb}${e.repo ? ` · ${e.repo.split('/')[1] ?? e.repo}` : ''}`,
    right: timeAgo(e.at), url: e.repo ? `https://github.com/${e.repo}` : profile(e.actor),
    action: e.repo ? `Open ${e.repo.split('/')[1] ?? e.repo} on GitHub` : 'Open profile on GitHub', avatar: e.avatar, kind: 'repo', login: e.actor,
  };
}

function personRow(p: Person, why = p.why): Row {
  return { id: `p${p.login}`, title: p.login, sub: why, url: profile(p.login), action: 'View profile', avatar: p.avatar, kind: 'person', login: p.login };
}

export type Feeds = {
  live?: { events: Event[]; following: number } | null;
  people?: { followBack: Person[]; field: Person[] } | null;
  headlines?: { items: Headline[] } | null;
  research?: { rising: Paper[]; tools: Paper[] } | null;
  repos?: Repo[] | null;
  models?: { field: Model[]; trending: Model[] } | null;
  launches?: Launch[] | null;
};

export function rowsFor(id: SectionId, f: Feeds): Row[] {
  switch (id) {
    case 'live': {
      const faces = (f.people?.followBack ?? []).slice(0, 4).map((p) => personRow(p, "follows you · you don't follow back yet"));
      return [...faces, ...(f.live?.events ?? []).slice(0, 6).map(eventRow)];
    }
    case 'activity':
      return (f.live?.events ?? []).map(eventRow);
    case 'people':
      return [...(f.people?.field ?? []).map((p) => personRow(p)), ...(f.people?.followBack ?? []).map((p) => personRow(p, 'follows you'))];
    case 'news':
      return (f.headlines?.items ?? []).map((h) => {
        const l = kindOf(h);
        return {
          id: `h${h.id}`, title: h.title, sub: `${h.explore ? '🌍 ' : ''}${h.source}${h.match.length && !h.explore ? ` · ${h.match.slice(0, 2).join(', ')}` : ''}`,
          right: timeAgo(h.published), url: h.link, action: `Read on ${h.source}`,
          letter: l, letterBg: BADGES[l].color, letterFg: BADGES[l].text,
          kind: l === 'P' ? 'paper' : 'headline', cat: h.category, explore: h.explore,
        };
      });
    case 'papers':
      return [...(f.research?.rising ?? []), ...(f.research?.tools ?? [])].map((p, i) => ({
        id: `r${i}${p.id}`, title: p.title, sub: `🔥 ${p.velocity}/month · ${p.venue || 'preprint'} · cited ${p.cited}`,
        right: p.date ? p.date.slice(0, 4) : '', url: p.url, action: 'Read the paper',
        letter: 'P', letterBg: BADGES.P.color, letterFg: BADGES.P.text, kind: 'paper', cat: 'science',
      }));
    case 'repos':
      return (f.repos ?? []).map((r, i) => ({
        id: `g${r.full_name}`, title: r.full_name.split('/')[1], sub: [r.full_name.split('/')[0], r.language, `pushed ${timeAgo(r.pushed_at)}`].filter(Boolean).join(' · '),
        right: `★ ${fmt(r.stargazers_count)}`, url: r.html_url, action: 'Open on GitHub',
        letter: String(i + 1), letterBg: 'rgba(255,255,255,0.10)', letterFg: '#f0f0f5', kind: 'repo',
      }));
    case 'models': {
      const seen = new Set<string>();
      return [...(f.models?.field ?? []), ...(f.models?.trending ?? [])].filter((m) => !seen.has(m.id) && seen.add(m.id)).map((m) => ({
        id: `m${m.id}`, title: m.id.split('/')[1] ?? m.id, sub: [m.id.split('/')[0], m.pipeline.replace(/-/g, ' ')].filter(Boolean).join(' · '),
        right: `♥ ${fmt(m.likes)}`, url: m.url, action: 'Open on Hugging Face',
        letter: 'M', letterBg: '#ffc457', letterFg: '#1a1a1a', kind: 'model', cat: 'ai',
      }));
    }
    case 'launches':
      return (f.launches ?? []).map((l) => ({
        id: `l${l.id}`, title: l.name, sub: l.match.length ? `${l.tagline} · your field: ${l.match.slice(0, 2).join(', ')}` : l.tagline,
        url: l.url, action: 'Open on Product Hunt', letter: 'L', letterBg: '#ff6fd8', letterFg: '#1a1a1a', kind: 'launch',
      }));
    default:
      return [];
  }
}
