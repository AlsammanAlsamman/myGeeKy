// Market: the popular, active repos of your field (a light port of the
// desktop's market.py watchlist), and today's Product Hunt launches.
import { XMLParser } from 'fast-xml-parser';
import { Repo, searchRepos } from './github';
import { match, Weights } from './interests';
import { plain } from './headlines';

/** Your strongest interests, for searching. */
export function topTerms(weights: Weights, n: number): string[] {
  return Object.entries(weights)
    .filter(([t]) => t.length >= 2 && t.length <= 40)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
    .map(([t]) => t);
}

// collections and learning material rank high on stars but aren't software the field runs on
const NOT_SOFTWARE = /\bawesome\b|curated|\blist of\b|\bcourses?\b|tutorials?\b|lecture|portfolio|cheat ?sheet|interview|roadmap|introduction to/i;

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const termRe = (t: string) => new RegExp(`\\b${t.toLowerCase().replace(/-/g, ' ').split(/\s+/).map(escape).join('[\\s_-]?')}\\b`, 'i');

/** How clearly a repo belongs to your field: your terms in its own name or
 *  description, or a fair share of its topics; 0 = not in your field. */
export function relevance(repo: Repo, terms: string[]): number {
  const own = `${repo.full_name.replace('/', ' ')} ${repo.description ?? ''}`;
  if (NOT_SOFTWARE.test(own)) return 0;
  const topics = (repo.topics ?? []).map((t) => t.replace(/-/g, ' '));
  if (topics.includes('awesome') || topics.includes('awesome list')) return 0;
  const pats = terms.map(termRe);
  const ownHits = pats.filter((p) => p.test(own)).length;
  const topicShare = topics.length ? topics.filter((t) => pats.some((p) => p.test(t))).length / topics.length : 0;
  if (!ownHits && topicShare < 0.25) return 0;
  return ownHits + 2 * topicShare;
}

/** Most-starred repos pushed in the last 90 days, per term, taking turns so
 *  one broad term can't fill the list. */
export async function fieldRepos(terms: string[], token: string | null, size: number,
                                 search: (q: string) => Promise<Repo[]> = (q) => searchRepos(q, token)): Promise<Repo[]> {
  const since = new Date(Date.now() - 90 * 86400000).toISOString().slice(0, 10);
  const filters = `fork:false archived:false stars:>=50 pushed:>${since}`;
  const lists = await Promise.all(terms.map(async (t) => {
    const q = t.includes(' ') ? `"${t}"` : t;
    try {
      return (await search(`${q} in:name,description,topics ${filters}`)).filter((r) => relevance(r, terms) > 0);
    } catch {
      return [];
    }
  }));
  const picked: Repo[] = [];
  const seen = new Set<string>();
  for (let depth = 0; picked.length < size && lists.some((l) => depth < l.length); depth++) {
    for (const l of lists) {
      const r = l[depth];
      if (r && !seen.has(r.full_name) && picked.length < size) {
        seen.add(r.full_name);
        picked.push(r);
      }
    }
  }
  return picked;
}

export type Launch = { id: string; name: string; tagline: string; url: string; match: string[] };

const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '@_' });
const FEED_LINK = /^https:\/\/www\.producthunt\.com\/products\/([a-z0-9][a-z0-9-]{0,80})/;

/** Today's featured launches (Product Hunt's public feed, no token), yours first. */
export async function fetchLaunches(weights: Weights, size = 20): Promise<Launch[]> {
  const r = await fetch('https://www.producthunt.com/feed');
  if (!r.ok) throw new Error(`Product Hunt said ${r.status}.`);
  const entries = parser.parse(await r.text())?.feed?.entry ?? [];
  const out: Launch[] = [];
  for (const e of Array.isArray(entries) ? entries : [entries]) {
    const links = Array.isArray(e.link) ? e.link : [e.link];
    const href = links.find((l: any) => !l?.['@_rel'] || l['@_rel'] === 'alternate')?.['@_href'] ?? '';
    const m = FEED_LINK.exec(href);
    const name = plain(e.title, 80);
    if (!m || !name) continue;
    const first = /<p>([\s\S]*?)<\/p>/.exec(typeof e.content === 'string' ? e.content : e.content?.['#text'] ?? '');
    const tagline = plain(first ? first[1] : '', 140);
    const [, hits] = match(`${name} ${tagline}`, weights);
    out.push({ id: m[1], name, tagline, url: `https://www.producthunt.com/products/${m[1]}`, match: hits });
  }
  return out.sort((a, b) => b.match.length - a.match.length).slice(0, size);
}

export async function fetchRepos(weights: Weights, token: string | null): Promise<Repo[]> {
  return fieldRepos(topTerms(weights, token ? 6 : 3), token, 25);
}
