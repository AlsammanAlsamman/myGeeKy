import { Text, View } from 'react-native';
import { Badge, Card, Empty, open, s, Screen, Section } from '../../components/ui';
import { timeAgo, useFeed } from '../../lib/app-state';
import { fetchHeadlines, Headline, kindOf } from '../../lib/headlines';
import { CATEGORY_COLORS } from '../../lib/theme';

function Row({ h }: { h: Headline }) {
  return (
    <Card onPress={() => open(h.link)}>
      <View style={s.row}>
        <Badge letter={kindOf(h)} />
        <Text style={s.itemTitle}>{h.title}</Text>
      </View>
      <Text style={s.small}>
        <Text style={{ color: CATEGORY_COLORS[h.category], fontWeight: '700' }}>{h.explore ? '🌍 ' : ''}{h.source}</Text>
        {'  ·  '}{timeAgo(h.published)}{h.match.length && !h.explore ? `  ·  ${h.match.slice(0, 3).join(', ')}` : ''}
      </Text>
    </Card>
  );
}

export default function Headlines() {
  const feed = useFeed('headlines', 3, async (p) => fetchHeadlines(p.weights));
  const items = feed.data?.items ?? [];
  const mine = items.filter((x) => !x.explore);
  const wide = items.filter((x) => x.explore);
  return (
    <Screen title="Headlines" subtitle="What's happening across your work: AI labs, journals and the tech press, ranked by your interests."
            loading={feed.loading} onRefresh={feed.refresh} updated={feed.at} error={feed.error}>
      {!items.length && !feed.loading ? <Empty>No headlines yet. Pull down to load them.</Empty> : null}
      <Section>FOR YOUR WORK</Section>
      {mine.length ? mine.map((h) => <Row key={h.id} h={h} />) :
        <Empty>Nothing matches your work today. Add keywords on the You tab to sharpen this.</Empty>}
      {wide.length ? <Section>🌍 THE BIG PICTURE</Section> : null}
      {wide.map((h) => <Row key={h.id} h={h} />)}
    </Screen>
  );
}
