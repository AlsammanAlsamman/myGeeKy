import { useState } from 'react';
import { Text, View } from 'react-native';
import { Badge, Card, Empty, open, s, Screen, Section, Segments } from '../../components/ui';
import { timeAgo, useApp, useFeed } from '../../lib/app-state';
import { fetchHeadlines, Headline, kindOf } from '../../lib/headlines';
import { fetchResearch, Paper } from '../../lib/research';
import { C, CATEGORY_COLORS } from '../../lib/theme';

type Part = 'headlines' | 'papers';
const PARTS: [Part, string][] = [['headlines', 'Headlines'], ['papers', 'Papers']];

function HeadlineRow({ h }: { h: Headline }) {
  const letter = kindOf(h);
  return (
    <Card onPress={() => open(h.link, letter === 'P' ? 'paper' : 'headline', h.category, h.explore)}>
      <View style={s.row}>
        <Badge letter={letter} />
        <Text style={s.itemTitle}>{h.title}</Text>
      </View>
      <Text style={s.small}>
        <Text style={{ color: CATEGORY_COLORS[h.category], fontWeight: '700' }}>{h.explore ? '🌍 ' : ''}{h.source}</Text>
        {'  ·  '}{timeAgo(h.published)}{h.match.length && !h.explore ? `  ·  ${h.match.slice(0, 3).join(', ')}` : ''}
      </Text>
    </Card>
  );
}

function Headlines({ top }: { top: React.ReactNode }) {
  const feed = useFeed('headlines', 3, async (p) => fetchHeadlines(p.weights));
  const items = feed.data?.items ?? [];
  const mine = items.filter((x) => !x.explore);
  const wide = items.filter((x) => x.explore);
  return (
    <Screen title="News" top={top} loading={feed.loading} onRefresh={feed.refresh} updated={feed.at} error={feed.error}
            subtitle="AI labs, journals and the tech press, ranked by your interests.">
      {!items.length && !feed.loading ? <Empty>No headlines yet. Pull down to load them.</Empty> : null}
      <Section>FOR YOUR WORK</Section>
      {mine.length ? mine.map((h) => <HeadlineRow key={h.id} h={h} />) :
        <Empty>Nothing matches your work today. Add keywords on the You tab to sharpen this.</Empty>}
      {wide.length ? <Section>🌍 THE BIG PICTURE</Section> : null}
      {wide.map((h) => <HeadlineRow key={h.id} h={h} />)}
    </Screen>
  );
}

function PaperRow({ p }: { p: Paper }) {
  return (
    <Card onPress={() => open(p.url, 'paper', 'science')}>
      <View style={s.row}>
        <Badge letter="P" />
        <Text style={s.itemTitle}>{p.title}</Text>
      </View>
      <Text style={s.small}>
        <Text style={{ color: C.amber, fontWeight: '700' }}>🔥 {p.velocity}/month</Text>
        {'  ·  '}{p.venue || 'preprint'}{'  ·  '}cited {p.cited}{p.date ? `  ·  ${p.date.slice(0, 4)}` : ''}
      </Text>
      {p.authors.length ? <Text style={s.small} numberOfLines={1}>{p.authors.join(', ')}</Text> : null}
      {p.repos.length ? (
        <Text style={[s.small, { color: C.cyan }]} onPress={() => open(`https://github.com/${p.repos[0]}`, 'repo')}>
          code: {p.repos[0]} ↗
        </Text>
      ) : null}
    </Card>
  );
}

function Papers({ top }: { top: React.ReactNode }) {
  const { profile } = useApp();
  const feed = useFeed('research', 12, (p) => fetchResearch(p));
  const topics = profile?.topicIds.map((t) => t.name) ?? [];
  return (
    <Screen title="News" top={top} loading={feed.loading} onRefresh={feed.refresh} updated={feed.at} error={feed.error}
            subtitle={topics.length ? `Rising in your field: ${topics.slice(0, 3).join('; ')}…`
                                    : 'Papers gaining citations fastest, matched to your interests (add your ORCID for your exact field).'}>
      <Section>🔥 RISING IN YOUR FIELD</Section>
      {(feed.data?.rising ?? []).map((p) => <PaperRow key={p.id} p={p} />)}
      {!feed.data && !feed.loading ? <Empty>Pull down to load.</Empty> : null}
      {feed.data?.tools.length ? <Section>🛠️ NEW TOOLS WITH THEIR CODE</Section> : null}
      {(feed.data?.tools ?? []).map((p) => <PaperRow key={`t${p.id}`} p={p} />)}
    </Screen>
  );
}

export default function News() {
  const [part, setPart] = useState<Part>('headlines');
  const top = <Segments value={part} options={PARTS} onChange={setPart} />;
  return part === 'headlines' ? <Headlines top={top} /> : <Papers top={top} />;
}
