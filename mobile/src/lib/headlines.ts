// Headlines: titles from AI labs, journals and the tech press, ranked by your
// interests -- a port of the desktop's headlines.py. On the phone there's no
// browser CORS, so the feeds are read directly.
import { XMLParser } from 'fast-xml-parser';
import { match, mix, strongMatch, todaySeed, Weights } from './interests';

type Feed = { id: string; label: string; category: 'ai' | 'science' | 'tech'; url: string; hosts: string[] };

export const FEEDS: Feed[] = [
  { id: 'mittr-ai', label: 'MIT Tech Review', category: 'ai', url: 'https://www.technologyreview.com/topic/artificial-intelligence/feed', hosts: ['www.technologyreview.com'] },
  { id: 'huggingface', label: 'Hugging Face', category: 'ai', url: 'https://huggingface.co/blog/feed.xml', hosts: ['huggingface.co'] },
  { id: 'google-ai', label: 'Google AI', category: 'ai', url: 'https://blog.google/technology/ai/rss/', hosts: ['blog.google'] },
  { id: 'deepmind', label: 'Google DeepMind', category: 'ai', url: 'https://deepmind.google/blog/rss.xml', hosts: ['deepmind.google'] },
  { id: 'openai', label: 'OpenAI', category: 'ai', url: 'https://openai.com/news/rss.xml', hosts: ['openai.com'] },
  { id: 'verge-ai', label: 'The Verge', category: 'ai', url: 'https://www.theverge.com/rss/ai-artificial-intelligence/index.xml', hosts: ['www.theverge.com'] },
  { id: 'techcrunch-ai', label: 'TechCrunch', category: 'ai', url: 'https://techcrunch.com/category/artificial-intelligence/feed/', hosts: ['techcrunch.com'] },
  { id: 'nature', label: 'Nature', category: 'science', url: 'https://www.nature.com/nature.rss', hosts: ['www.nature.com'] },
  { id: 'nature-genetics', label: 'Nature Genetics', category: 'science', url: 'https://www.nature.com/ng.rss', hosts: ['www.nature.com'] },
  { id: 'nature-biotech', label: 'Nature Biotechnology', category: 'science', url: 'https://www.nature.com/nbt.rss', hosts: ['www.nature.com'] },
  { id: 'science', label: 'Science', category: 'science', url: 'https://www.science.org/rss/news_current.xml', hosts: ['www.science.org'] },
  { id: 'quanta', label: 'Quanta', category: 'science', url: 'https://www.quantamagazine.org/feed/', hosts: ['www.quantamagazine.org'] },
  { id: 'ars-science', label: 'Ars Technica', category: 'science', url: 'https://feeds.arstechnica.com/arstechnica/science', hosts: ['arstechnica.com'] },
  { id: 'sciencedaily', label: 'ScienceDaily', category: 'science', url: 'https://www.sciencedaily.com/rss/top/science.xml', hosts: ['www.sciencedaily.com'] },
  { id: 'ars-tech', label: 'Ars Technica', category: 'tech', url: 'https://feeds.arstechnica.com/arstechnica/technology-lab', hosts: ['arstechnica.com'] },
  { id: 'github-blog', label: 'GitHub', category: 'tech', url: 'https://github.blog/feed/', hosts: ['github.blog'] },
  { id: 'register', label: 'The Register', category: 'tech', url: 'https://www.theregister.com/headlines.atom', hosts: ['www.theregister.com'] },
];

export type Headline = {
  id: string; title: string; link: string; source: string; feed: string; category: string;
  published: string; summary: string; match: string[]; score: number; explore?: boolean;
};

const ANNOUNCEMENT_FEEDS = new Set(['openai', 'google-ai', 'deepmind', 'huggingface', 'github-blog']);
const PAPER_FEEDS = new Set(['nature-genetics', 'nature-biotech']);

/** P paper, N news, D discussion, A announcement. */
export function kindOf(h: { feed?: string; link?: string; source?: string }): 'P' | 'N' | 'D' | 'A' {
  if (h.source === 'arxiv' || h.source === 'biorxiv') return 'P';
  if (h.source === 'hackernews') return 'D';
  if (h.feed && ANNOUNCEMENT_FEEDS.has(h.feed)) return 'A';
  if ((h.feed && PAPER_FEEDS.has(h.feed)) || /nature\.com\/articles\/s4\d{4}-/.test(h.link ?? '')) return 'P';
  return 'N';
}

const ENTITIES: Record<string, string> = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };
export function plain(text: unknown, n: number): string {
  let t = typeof text === 'string' ? text : (text as { '#text'?: string })?.['#text'] ?? '';
  for (let i = 0; i < 2; i++) {   // some feeds escape twice
    t = t.replace(/<[^>]{0,200}>/g, ' ')
      .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(Number(d)))
      .replace(/&#x([0-9a-f]+);/gi, (_, h) => String.fromCodePoint(parseInt(h, 16)))
      .replace(/&([a-z]+);/gi, (m, e) => ENTITIES[e.toLowerCase()] ?? m);
  }
  return t.split(/\s+/).join(' ').trim().slice(0, n);
}

export function allowedLink(url: string, hosts: string[]): boolean {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && hosts.includes(u.hostname) && !u.username;
  } catch {
    return false;
  }
}

const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '@_', processEntities: true });

function asList<T>(x: T | T[] | undefined): T[] {
  return x === undefined ? [] : Array.isArray(x) ? x : [x];
}

function hash(s: string): string {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return (h >>> 0).toString(16);
}

export function parseFeed(xml: string, feed: Feed): Headline[] {
  const doc = parser.parse(xml);
  const entries = [
    ...asList(doc?.rss?.channel?.item),
    ...asList(doc?.feed?.entry),
    ...asList(doc?.['rdf:RDF']?.item),
  ];
  const out: Headline[] = [];
  for (const e of entries) {
    const title = plain(e.title, 180);
    let link = typeof e.link === 'string' ? e.link : '';
    if (!link) {
      const links = asList(e.link) as { '@_href'?: string; '@_rel'?: string }[];
      link = links.find((l) => !l['@_rel'] || l['@_rel'] === 'alternate')?.['@_href'] ?? '';
    }
    const when = new Date(e.pubDate ?? e.published ?? e.updated ?? e['dc:date'] ?? '');
    if (!title || !allowedLink(link.trim(), feed.hosts) || isNaN(when.getTime())) continue;
    out.push({
      id: hash(link), title, link: link.trim(), source: feed.label, feed: feed.id, category: feed.category,
      published: when.toISOString(), summary: plain(e.description ?? e.summary ?? '', 400), match: [], score: 0,
    });
  }
  return out.sort((a, b) => b.published.localeCompare(a.published)).slice(0, 40);
}

const ageDays = (h: Headline) => Math.max((Date.now() - new Date(h.published).getTime()) / 86400000, 0);

export function select(items: Headline[], weights: Weights, size = 30, share = 0.2, aiMin = 3, days = 4): Headline[] {
  const seen = new Set<string>();
  const fresh = items
    .filter((x) => ageDays(x) <= days)
    .sort((a, b) => b.published.localeCompare(a.published))
    .filter((x) => !seen.has(x.title.toLowerCase()) && seen.add(x.title.toLowerCase()));
  const ranked = fresh
    .map((x) => {
      let [relevance, matched] = match(`${x.title} ${x.summary.slice(0, 300)}`, weights);
      if (matched.length < 2 && !matched.some((m) => m.includes(' '))) relevance *= 0.3;
      return { ...x, match: matched, score: relevance * Math.exp(-ageDays(x) / 3) };
    })
    .filter((x) => x.score > 0 && strongMatch(x.match, weights))
    .sort((a, b) => b.score - a.score);
  const bigPicture = (exclude: Set<string>) => {   // newest of the rest, taking turns across AI, science and tech
    const byCat: Record<string, Headline[]> = {};
    for (const x of fresh) if (!exclude.has(x.id)) (byCat[x.category] ??= []).push(x);
    const out: Headline[] = [];
    for (let i = 0; Object.values(byCat).some((v) => i < v.length); i++) for (const v of Object.values(byCat)) if (i < v.length) out.push(v[i]);
    return out;
  };
  const picks = mix(ranked, size, share, bigPicture(new Set(ranked.slice(0, size).map((x) => x.id))).slice(0, size));
  const taken = new Set(picks.map((x) => x.id));
  const rest = bigPicture(taken);
  const aiHave = picks.filter((x) => x.category === 'ai').length;
  for (const x of rest.filter((b) => b.category === 'ai').slice(0, Math.max(0, aiMin - aiHave))) {
    picks.push({ ...x, explore: true });
    taken.add(x.id);
  }
  for (const x of rest) {
    if (picks.length >= size) break;
    if (!taken.has(x.id)) {
      picks.push({ ...x, explore: true });
      taken.add(x.id);
    }
  }
  return picks.map((x) => ({ ...x, summary: '' }));
}

export async function fetchHeadlines(weights: Weights): Promise<{ items: Headline[]; errors: string[] }> {
  const errors: string[] = [];
  const results = await Promise.all(
    FEEDS.map(async (f) => {
      try {
        const r = await fetch(f.url, { headers: { 'User-Agent': 'mygeeky-mobile' } });
        if (!r.ok) throw new Error(String(r.status));
        return parseFeed(await r.text(), f);
      } catch {
        errors.push(f.label);
        return [];
      }
    }),
  );
  void todaySeed;
  return { items: select(results.flat(), weights), errors };
}
