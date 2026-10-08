import { fetchT } from './net';

// Read-only GitHub API calls. With the sign-in token the limit is 5,000 calls an
// hour; without one it's 60, so screens that need many calls say so.
export const NAME_RE = /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/;

export class GitHubError extends Error {}

export async function gh<T = any>(path: string, token: string | null): Promise<T> {
  const r = await fetchT(`https://api.github.com${path}`, {
    headers: {
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (r.status === 403 || r.status === 429) {
    throw new GitHubError(token ? 'GitHub asks us to slow down. Try again in a few minutes.'
                                : 'GitHub limits reading without signing in. Sign in with GitHub on the You tab.');
  }
  if (!r.ok) throw new GitHubError(`GitHub said ${r.status}.`);
  return r.json();
}

/** Everyone a user follows (up to 500). */
export async function following(user: string, token: string | null): Promise<string[]> {
  const out: string[] = [];
  for (let page = 1; page <= 5; page++) {
    const batch = await gh<{ login: string }[]>(`/users/${user}/following?per_page=100&page=${page}`, token);
    out.push(...batch.map((u) => u.login));
    if (batch.length < 100) break;
  }
  return out;
}

export async function followers(user: string, token: string | null): Promise<{ login: string; avatar: string }[]> {
  const out: { login: string; avatar: string }[] = [];
  for (let page = 1; page <= 3; page++) {
    const batch = await gh<{ login: string; avatar_url: string }[]>(`/users/${user}/followers?per_page=100&page=${page}`, token);
    out.push(...batch.map((u) => ({ login: u.login, avatar: u.avatar_url })));
    if (batch.length < 100) break;
  }
  return out;
}

export type Repo = {
  full_name: string; description: string | null; stargazers_count: number; language: string | null;
  topics?: string[]; pushed_at: string; html_url: string; fork: boolean; archived: boolean;
  owner: { login: string; avatar_url: string; type: string };
};

export async function searchRepos(q: string, token: string | null, perPage = 20): Promise<Repo[]> {
  const d = await gh<{ items: Repo[] }>(`/search/repositories?q=${encodeURIComponent(q)}&sort=stars&order=desc&per_page=${perPage}`, token);
  return d.items ?? [];
}
