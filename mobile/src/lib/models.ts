// Hugging Face models trending in your field, and everywhere -- a port of the
// desktop's hfmodels.py (public API, no key).
import { fetchT } from './net';
import { match, Weights } from './interests';

export type Model = {
  id: string; likes: number; downloads: number; trending: number; pipeline: string; tags: string[];
  url: string; match: string[]; score: number; via?: string;
};

const ID_RE = /^[A-Za-z0-9][\w.-]{0,95}\/[\w.-]{1,95}$/;
const TAG_RE = /^[a-z0-9][a-z0-9_:.+-]{0,59}$/;
const FIELD_TAGS: Record<string, string[]> = {
  biology: ['biology', 'bioinformatics', 'gene', 'genome', 'genomics', 'genetics', 'gwas', 'protein', 'rna', 'dna', 'cell',
    'single cell', 'transcriptomics', 'proteomics', 'microbiome', 'phylogenetics', 'population genetics', 'plant', 'ecology', 'evolution'],
  genomics: ['genomics', 'genome', 'gwas', 'genetics', 'dna', 'sequencing', 'variant'],
  protein: ['protein', 'proteomics', 'structure', 'drug discovery', 'antibody', 'enzyme'],
  medical: ['medical', 'clinical', 'disease', 'health', 'imaging', 'radiology', 'epidemiology', 'drug'],
  chemistry: ['chemistry', 'molecule', 'molecular', 'cheminformatics', 'materials'],
  climate: ['climate', 'weather', 'earth', 'remote sensing', 'satellite'],
  finance: ['finance', 'economics', 'trading'],
  code: ['software', 'programming', 'code', 'developer'],
  math: ['math', 'mathematics', 'theorem', 'statistics'],
};

function clean(m: any): Model | null {
  if (!m || typeof m.id !== 'string' || !ID_RE.test(m.id)) return null;
  return {
    id: m.id, likes: Number(m.likes) || 0, downloads: Number(m.downloads) || 0, trending: Number(m.trendingScore) || 0,
    pipeline: typeof m.pipeline_tag === 'string' && TAG_RE.test(m.pipeline_tag) ? m.pipeline_tag : '',
    tags: (m.tags ?? []).filter((t: unknown) => typeof t === 'string' && TAG_RE.test(t)).slice(0, 20),
    url: `https://huggingface.co/${m.id}`, match: [], score: 0,
  };
}

async function get(params: Record<string, string>): Promise<Model[]> {
  const q = new URLSearchParams({ sort: 'trendingScore', limit: '40', ...params });
  const r = await fetchT(`https://huggingface.co/api/models?${q}`);
  if (!r.ok) throw new Error(`Hugging Face ${r.status}`);
  const data = await r.json();
  return (Array.isArray(data) ? data : []).map(clean).filter(Boolean) as Model[];
}

export function fieldTags(weights: Weights, extra: string[], n = 5): string[] {
  const scores: Record<string, number> = {};
  for (const [term, w] of Object.entries(weights)) {
    for (const [tag, words] of Object.entries(FIELD_TAGS)) {
      if (words.some((word) => word === term || (term.length > 3 && word.split(' ').includes(term)))) scores[tag] = (scores[tag] ?? 0) + w;
    }
  }
  for (const t of extra) {
    const s = t.toLowerCase().trim().replace(/ /g, '-');
    if (TAG_RE.test(s) && s.length >= 3) scores[s] = (scores[s] ?? 0) + 1;
  }
  return Object.entries(scores).sort((a, b) => b[1] - a[1]).slice(0, n).map(([t]) => t);
}

const text = (m: Model) => [m.id.replace(/[/_-]/g, ' '), m.pipeline.replace(/-/g, ' '), m.tags.join(' ').replace(/-/g, ' ')].join(' ');

export async function fetchModels(weights: Weights, extra: string[], size = 15): Promise<{ field: Model[]; trending: Model[]; tags: string[] }> {
  const tags = fieldTags(weights, extra);
  const field = new Map<string, Model>();
  await Promise.all(
    tags.map(async (tag) => {
      try {
        for (const m of await get({ filter: tag, limit: '30' })) if (m.trending > 0 || m.likes >= 20) if (!field.has(m.id)) field.set(m.id, { ...m, via: tag });
      } catch {
        /* one tag down is fine */
      }
    }),
  );
  const ranked = Array.from(field.values())
    .map((m) => {
      const [relevance, hits] = match(text(m), weights);
      return { ...m, match: hits, score: (1 + relevance) * Math.log1p(m.trending + m.likes / 20) };
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, size);
  const taken = new Set(ranked.map((m) => m.id));
  let everywhere: Model[] = [];
  try {
    everywhere = await get({ limit: '60' });
  } catch {
    /* fine */
  }
  return { field: ranked, trending: everywhere.filter((m) => !taken.has(m.id)).slice(0, size), tags };
}
