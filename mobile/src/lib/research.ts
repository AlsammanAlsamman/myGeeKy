// Research that's rising in your field, from OpenAlex -- a port of the
// desktop's papers.refresh_trends: papers in your research topics (from your
// ORCID) or matching your strongest interests, ranked by citations per month.
import { match, Profile } from './interests';

export type Paper = {
  id: string; title: string; url: string; date: string; venue: string; cited: number;
  authors: string[]; repos: string[]; velocity: number; match: string[]; score: number; kind: 'P';
};

const SELECT = 'id,doi,title,publication_date,cited_by_count,authorships,primary_location,abstract_inverted_index';
const GH_REPO = /github\.com\/([A-Za-z0-9][A-Za-z0-9-]{0,38})\/([A-Za-z0-9._-]{1,100})/gi;

function abstract(w: any): string {
  const inv = w.abstract_inverted_index;
  if (!inv || typeof inv !== 'object') return '';
  const words: [number, string][] = [];
  for (const [word, ps] of Object.entries(inv)) for (const p of (ps as number[]) ?? []) words.push([p, word]);
  return words.sort((a, b) => a[0] - b[0]).map(([, w2]) => w2).join(' ');
}

export function toPaper(w: any): Paper | null {
  if (!w?.title) return null;
  const id = String(w.id ?? '').split('/').pop() ?? '';
  if (!/^W\d+$/.test(id)) return null;
  const doi = String(w.doi ?? '').replace(/^https?:\/\/doi\.org\//i, '');
  const date = String(w.publication_date ?? '').slice(0, 10);
  const cited = Number(w.cited_by_count) || 0;
  const months = Math.max((Date.now() - new Date(date).getTime()) / (86400000 * 30.4), 1);
  const ships = (w.authorships ?? []) as any[];
  const lead = ships.length > 4 ? [...ships.slice(0, 3), ships[ships.length - 1]] : ships;
  const text = abstract(w);
  const repos = Array.from(new Set(Array.from(text.matchAll(GH_REPO)).map((m) => `${m[1]}/${m[2].replace(/[.,;)]+$/, '')}`))).slice(0, 3);
  return {
    id, title: String(w.title).slice(0, 240), date, cited, repos, kind: 'P',
    url: /^10\.\d{4,9}\//.test(doi) ? `https://doi.org/${doi}` : `https://openalex.org/${id}`,
    venue: String(w.primary_location?.source?.display_name ?? '').slice(0, 80),
    authors: lead.map((a) => String(a?.author?.display_name ?? '')).filter(Boolean).slice(0, 4),
    velocity: Math.round((cited / months) * 100) / 100, match: [], score: 0,
    ...({ abstract: text.slice(0, 600) } as object),
  } as Paper;
}

async function works(filter: string, perPage = 50): Promise<Paper[]> {
  const url = `https://api.openalex.org/works?filter=${encodeURIComponent(filter)}&sort=cited_by_count:desc&per-page=${perPage}&select=${SELECT}`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`OpenAlex ${r.status}`);
  return ((await r.json()).results ?? []).map(toPaper).filter(Boolean) as Paper[];
}

export async function fetchResearch(profile: Profile, months = 12, size = 20): Promise<{ rising: Paper[]; tools: Paper[] }> {
  const since = new Date(Date.now() - months * 30.4 * 86400000).toISOString().slice(0, 10);
  const base = `,from_publication_date:${since},type:article|preprint`;
  let found: Paper[] = [];
  let toolsRaw: Paper[] = [];
  const useTopics = profile.topicIds.length > 0;
  if (useTopics) {
    const field = 'primary_topic.id:' + profile.topicIds.map((t) => t.id).join('|');
    [found, toolsRaw] = await Promise.all([works(field + base), works(field + ',title_and_abstract.search:github' + base)]);
  } else {
    const terms = Object.entries(profile.weights).sort((a, b) => b[1] - a[1]).map(([t]) => t).slice(0, 3);
    for (const t of terms) {
      const f = `title_and_abstract.search:${t.replace(/[",]/g, ' ')}`;
      found.push(...(await works(f + base, 25)));
      toolsRaw.push(...(await works(`${f} github` + base, 25)));
    }
  }
  const unique = new Map(found.map((p) => [p.id, p]));
  const rising: Paper[] = [];
  for (const p of unique.values()) {
    const [relevance, hits] = match(`${p.title} ${(p as any).abstract ?? ''}`, profile.weights);
    const boost = useTopics ? 0.5 + relevance : hits.length >= 2 || hits.some((h) => h.includes(' ')) ? relevance : 0;
    if (boost > 0) rising.push({ ...p, match: hits, score: p.velocity * boost });
  }
  rising.sort((a, b) => b.score - a.score);
  const tools = Array.from(new Map(toolsRaw.filter((p) => p.repos.length).map((p) => [p.id, p])).values())
    .sort((a, b) => b.velocity - a.velocity || b.cited - a.cited);
  const slim = (p: Paper) => ({ ...p, abstract: undefined }) as Paper;
  return { rising: rising.slice(0, size).map(slim), tools: tools.slice(0, size).map(slim) };
}
