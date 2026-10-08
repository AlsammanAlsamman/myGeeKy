// Live: what the people you follow are doing on GitHub -- a port of the
// desktop's activity.py. One call to received_events covers everyone you follow.
import { following, gh } from './github';

export type Event = {
  id: string; actor: string; avatar: string; verb: string; repo: string; at: string; icon: string;
};

type Raw = { id: string; type: string; actor?: { login: string; avatar_url: string }; repo?: { name: string };
             payload?: any; created_at: string };

const VERBS: Record<string, [string, (p: any) => string]> = {
  PushEvent: ['⬆️', (p) => {
    const n = p?.size ?? p?.commits?.length;
    if (n) return `pushed ${n} commit${n === 1 ? '' : 's'}`;
    const branch = String(p?.ref ?? '').replace(/^refs\/heads\//, '');
    return branch ? `pushed to '${branch}'` : 'pushed commits';
  }],
  PullRequestEvent: ['🔀', (p) => (p?.action === 'closed' && p?.pull_request?.merged ? 'merged a pull request' : `${p?.action ?? 'updated'} a pull request`)],
  IssuesEvent: ['🐞', (p) => `${p?.action ?? 'updated'} an issue`],
  CreateEvent: ['✨', (p) => (p?.ref_type === 'repository' ? 'created a new repository'
    : p?.ref_type === 'branch' ? `created branch '${p?.ref ?? ''}'` : `created a ${p?.ref_type ?? 'thing'}`)],
  ReleaseEvent: ['🚀', () => 'published a release'],
  WatchEvent: ['⭐', () => 'starred'],
  ForkEvent: ['🍴', () => 'forked'],
  PublicEvent: ['🌍', () => 'open-sourced'],
  IssueCommentEvent: ['💬', () => 'commented on an issue'],
  PullRequestReviewEvent: ['👀', () => 'reviewed a pull request'],
  PullRequestReviewCommentEvent: ['💬', () => 'commented on a pull request'],
};

export function formatEvent(e: Raw): Event | null {
  const v = VERBS[e.type];
  if (!v || !e.actor?.login) return null;
  let verb: string;
  try {
    verb = v[1](e.payload);
  } catch {
    return null;
  }
  return { id: e.id, actor: e.actor.login, avatar: e.actor.avatar_url, verb, repo: e.repo?.name ?? '', at: e.created_at, icon: v[0] };
}

/** The people you follow, newest first; strangers' events on followed orgs are left out. */
export async function fetchLive(user: string, token: string | null, limit = 50): Promise<{ events: Event[]; following: number }> {
  const follows = new Set((await following(user, token)).map((u) => u.toLowerCase()));
  const events: Event[] = [];
  for (let page = 1; page <= 3 && events.length < limit; page++) {
    const raw = await gh<Raw[]>(`/users/${user}/received_events?per_page=100&page=${page}`, token);
    for (const e of raw) {
      if (!follows.has((e.actor?.login ?? '').toLowerCase())) continue;
      const f = formatEvent(e);
      if (f) events.push(f);
    }
    if (raw.length < 100) break;
  }
  return { events: events.slice(0, limit), following: follows.size };
}
