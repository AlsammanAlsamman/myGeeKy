import { Text, View } from 'react-native';
import { Badge, Card, Empty, open, s, Screen, Section } from '../../components/ui';
import { useApp, useFeed } from '../../lib/app-state';
import { fetchResearch, Paper } from '../../lib/research';
import { C } from '../../lib/theme';

function PaperRow({ p }: { p: Paper }) {
  return (
    <Card onPress={() => open(p.url)}>
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
        <Text style={[s.small, { color: C.cyan }]} onPress={() => open(`https://github.com/${p.repos[0]}`)}>
          code: {p.repos[0]} ↗
        </Text>
      ) : null}
    </Card>
  );
}

export default function Research() {
  const { profile } = useApp();
  const feed = useFeed('research', 12, (p) => fetchResearch(p));
  const topics = profile?.topicIds.map((t) => t.name) ?? [];
  return (
    <Screen title="Research" loading={feed.loading} onRefresh={feed.refresh} updated={feed.at} error={feed.error}
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
