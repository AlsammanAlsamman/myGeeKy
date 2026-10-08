import { Text, View } from 'react-native';
import { Card, Empty, open, s, Screen, Section } from '../../components/ui';
import { useApp, useFeed } from '../../lib/app-state';
import { fetchModels, Model } from '../../lib/models';
import { C } from '../../lib/theme';

const fmt = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n));

function ModelRow({ m }: { m: Model }) {
  const [owner, name] = m.id.split('/');
  return (
    <Card onPress={() => open(m.url)}>
      <View style={s.row}>
        <Text style={{ fontSize: 20 }}>🤗</Text>
        <View style={{ flex: 1 }}>
          <Text style={s.itemTitle}>
            <Text style={{ fontWeight: '800' }}>{name}</Text> <Text style={{ color: C.muted }}>{owner}</Text>
          </Text>
          <Text style={s.small}>
            {[m.pipeline.replace(/-/g, ' '), `♥ ${fmt(m.likes)}`, `↓ ${fmt(m.downloads)}`].filter(Boolean).join('  ·  ')}
          </Text>
        </View>
        <Text style={{ color: C.text, fontWeight: '700' }}>🔥 {fmt(m.trending)}</Text>
      </View>
    </Card>
  );
}

export default function Models() {
  const { settings } = useApp();
  const feed = useFeed('models', 6, (p) => fetchModels(p.weights, [...(settings?.keywords ?? []), ...(settings?.topics ?? [])]));
  return (
    <Screen title="Models" subtitle="Trending on Hugging Face: first in your field, then everywhere."
            loading={feed.loading} onRefresh={feed.refresh} updated={feed.at} error={feed.error}>
      <Section>IN YOUR FIELD{feed.data?.tags.length ? ` · ${feed.data.tags.join(', ')}` : ''}</Section>
      {(feed.data?.field ?? []).map((m) => <ModelRow key={m.id} m={m} />)}
      {feed.data && !feed.data.field.length ? <Empty>No field tags yet: add keywords on the You tab.</Empty> : null}
      {!feed.data && !feed.loading ? <Empty>Pull down to load.</Empty> : null}
      {feed.data?.trending.length ? <Section>🌍 TRENDING EVERYWHERE</Section> : null}
      {(feed.data?.trending ?? []).map((m) => <ModelRow key={`t${m.id}`} m={m} />)}
    </Screen>
  );
}
