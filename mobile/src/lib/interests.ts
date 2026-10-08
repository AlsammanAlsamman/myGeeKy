// Your interests as weighted terms, and matching text against them: a port of
// the desktop's interests.py (profile_terms, match, mix, explore_terms), so the
// phone ranks things the same way.
const STOPWORDS = new Set(
  (
    'a about above after again all also am an and any are as at be because been before being below between both but by ' +
    'can could did do does doing down during each few for from further had has have having he her here hers him his how ' +
    'i if in into is it its itself just like more most my no nor not now of off on once only or other our out over own ' +
    'same she should so some such than that the their them then there these they this those through to too under until ' +
    'up very was we were what when where which while who whom why will with would you your yours new using use used based ' +
    'via tool tools library framework project projects repository repo code app apps simple fast easy small'
  ).split(' '),
);

export const EXPLORE_POOL = [
  'single-cell', 'spatial transcriptomics', 'protein design', 'llm agents', 'causal inference',
  'graph neural networks', 'reproducibility', 'data visualization', 'rust', 'webassembly',
  'privacy', 'climate', 'epidemiology', 'microscopy', 'robotics', 'quantum computing',
  'open science', 'bayesian', 'time series', 'drug discovery', 'metagenomics', 'neuroscience',
  'computer vision', 'education', 'accessibility', 'high performance computing', 'ecology',
  'statistics', 'knowledge graphs', 'workflow management',
];

export type Weights = Record<string, number>;

// ---- the keyword dictionary (built by the desktop's model, published on GitHub)
export type Dict = { version: string; terms: Record<string, { label: string; related: [string, number][] }> };

const ALIASES: Record<string, string> = {
  'artificial intelligence': 'artificial-intelligence', 'a.i.': 'ai', ml: 'machine-learning', dl: 'deep-learning',
  'large language models': 'llm', llms: 'llm', 'natural language processing': 'nlp', 'single cell': 'single-cell',
  'scrna-seq': 'single-cell', rnaseq: 'rna-seq', 'c++': 'cpp', js: 'javascript', quantum: 'quantum-computing',
};

export function slug(term: string): string {
  let t = term.trim().toLowerCase().split(/\s+/).join(' ');
  t = ALIASES[t] ?? t;
  t = t.replace(/[^a-z0-9+#. -]/g, '').replace(/ /g, '-');
  return ALIASES[t] ?? t;
}

export function lookup(dict: Dict | null, term: string) {
  if (!dict) return null;
  const s = slug(term);
  if (dict.terms[s]) return { topic: s, ...dict.terms[s] };
  if (s.endsWith('s') && dict.terms[s.slice(0, -1)]) return { topic: s.slice(0, -1), ...dict.terms[s.slice(0, -1)] };
  return null;
}

/** Each known keyword with its related concepts (weighted), each unknown one as itself. */
export function expand(dict: Dict | null, terms: string[], base = 1): Weights {
  const out: Weights = {};
  const put = (p: string, w: number) => {
    if (p.length >= 3) out[p] = Math.max(out[p] ?? 0, w);
  };
  for (const t of terms) {
    put(t.toLowerCase().split(/\s+/).join(' '), base);
    const e = lookup(dict, t);
    if (!e) continue;
    put(e.topic.replace(/-/g, ' '), base);
    for (const [rel, w] of e.related.slice(0, 12)) put(rel.replace(/-/g, ' '), Math.round(base * 0.6 * w * 1e4) / 1e4);
  }
  return out;
}

// ---- matching
const patterns = new Map<string, RegExp>();
function pattern(term: string): RegExp {
  let p = patterns.get(term);
  if (!p) {
    const words = term.split(' ').map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    p = new RegExp('\\b' + words.join('[\\s_-]+') + 's?\\b', 'i');
    patterns.set(term, p);
  }
  return p;
}

/** [score 0..1, matched terms] of text against your weights. */
export function match(text: string, weights: Weights): [number, string[]] {
  if (!text) return [0, []];
  const hits: [string, number][] = [];
  for (const [t, w] of Object.entries(weights)) {
    if (t.length >= 3 && !STOPWORDS.has(t) && pattern(t).test(text)) hits.push([t, w]);
  }
  if (!hits.length) return [0, []];
  hits.sort((a, b) => b[1] - a[1]);
  const score = 1 - hits.slice(0, 5).reduce((acc, [, w]) => acc * (1 - Math.min(w, 1) * 0.6), 1);
  return [Math.round(score * 1e4) / 1e4, hits.slice(0, 4).map(([t]) => t)];
}

/** Real evidence: two of your terms, a multi-word one, or one you chose yourself. */
export function strongMatch(matched: string[], weights: Weights): boolean {
  return matched.length >= 2 || matched.some((m) => m.includes(' ')) || matched.some((m) => (weights[m] ?? 0) >= 0.9);
}

// ---- exploration: a little room for what you don't usually look at
function seeded(seed: number) {
  let s = seed % 2147483647;
  return () => (s = (s * 16807) % 2147483647) / 2147483647;
}

export function todaySeed(): number {
  return Math.floor(Date.now() / 86400000);
}

export function exploreTerms(weights: Weights, k = 2): string[] {
  const known = Object.keys(weights);
  const pool = EXPLORE_POOL.filter((t) => !known.some((kt) => kt.includes(t) || t.includes(kt)));
  const rnd = seeded(todaySeed());
  return pool
    .map((t) => [t, rnd()] as const)
    .sort((a, b) => a[1] - b[1])
    .slice(0, k)
    .map(([t]) => t);
}

/** The best n - k items, then k "explore" picks from the pool, marked explore. */
export function mix<T extends { id: string }>(ranked: T[], n: number, share: number, pool: T[]): (T & { explore: boolean })[] {
  const k = share > 0 ? Math.max(1, Math.round(n * share)) : 0;
  const head = ranked.slice(0, n - k).map((x) => ({ ...x, explore: false }));
  const taken = new Set(head.map((x) => x.id));
  const rnd = seeded(todaySeed());
  const picks = pool
    .filter((x) => !taken.has(x.id))
    .map((x) => [x, rnd()] as const)
    .sort((a, b) => a[1] - b[1])
    .slice(0, k)
    .map(([x]) => ({ ...x, explore: true }));
  return [...head, ...picks];
}

export type Profile = { weights: Weights; topicIds: { id: string; name: string }[]; field: string[] };
