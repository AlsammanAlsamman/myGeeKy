// People: who follows you that you don't follow yet, and people building the
// tools of your field (the owners of the most-starred, active repos matching
// your interests). Suggestions only -- the app never follows anyone.
import { followers, following, searchRepos } from './github';
import { Weights } from './interests';
import { topTerms, fieldRepos } from './market';

export type Person = { login: string; avatar: string; why: string; repo?: string };

export async function fetchPeople(user: string, token: string | null, weights: Weights):
    Promise<{ followBack: Person[]; field: Person[] }> {
  const [mine, theirs] = await Promise.all([following(user, token), followers(user, token)]);
  const known = new Set([...mine, user].map((u) => u.toLowerCase()));
  const followBack = theirs.filter((f) => !known.has(f.login.toLowerCase()))
    .map((f) => ({ login: f.login, avatar: f.avatar, why: 'follows you' }));

  const field: Person[] = [];
  const seen = new Set(known);
  for (const repo of await fieldRepos(topTerms(weights, 3), token, 40, (q) => searchRepos(q, token, 20))) {
    const o = repo.owner;
    if (o.type !== 'User' || seen.has(o.login.toLowerCase())) continue;
    seen.add(o.login.toLowerCase());
    field.push({ login: o.login, avatar: o.avatar_url, repo: repo.full_name,
                 why: `builds ${repo.full_name.split('/')[1]} · ★ ${repo.stargazers_count.toLocaleString()}` });
    if (field.length >= 20) break;
  }
  return { followBack: followBack.slice(0, 30), field };
}
