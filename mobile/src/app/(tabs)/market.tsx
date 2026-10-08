import { useState } from 'react';
import { Image, Text, View } from 'react-native';
import { Card, Empty, open, s, Screen, Section, Segments } from '../../components/ui';
import { timeAgo, useApp, useFeed } from '../../lib/app-state';
import { Repo } from '../../lib/github';
import { fetchLaunches, fetchRepos, Launch } from '../../lib/market';
import { fetchModels, Model } from '../../lib/models';
import { C } from '../../lib/theme';

type Part = 'repos' | 'models' | 'launches';
const PARTS: [Part, string][] = [['repos', 'Repos'], ['models', 'AI models'], ['launches', 'Launches']];

const fmt = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n));

function RepoRow({ r, rank }: { r: Repo; rank: number }) {
  const [owner, name] = r.full_name.split('/');
  return (
    <Card onPress={() => open(r.html_url, 'repo')}>
      <View style={[s.row, { alignItems: 'center' }]}>
        <Text style={{ color: C.muted, fontWeight: '800', width: 22 }}>{rank}</Text>
        <Image source={{ uri: `${r.owner.avatar_url}&s=64` }} style={{ width: 30, height: 30, borderRadius: 8 }} />
        <View style={{ flex: 1 }}>
          <Text style={s.itemTitle} numberOfLines={1}>
            <Text style={{ fontWeight: '800' }}>{name}</Text> <Text style={{ color: C.muted }}>{owner}</Text>
          </Text>
          {r.description ? <Text style={s.small} numberOfLines={2}>{r.description}</Text> : null}
          <Text style={s.small}>{[r.language, `pushed ${timeAgo(r.pushed_at)}`].filter(Boolean).join('  ·  ')}</Text>
        </View>
        <Text style={{ color: C.amber, fontWeight: '800' }}>★ {fmt(r.stargazers_count)}</Text>
      </View>
    </Card>
  );
}

function Repos({ top }: { top: React.ReactNode }) {
  const { token } = useApp();
  const feed = useFeed('market-repos', 24, (p) => fetchRepos(p.weights, token));
  return (
    <Screen title="Market" top={top} loading={feed.loading} onRefresh={feed.refresh} updated={feed.at} error={feed.error}
            subtitle="The popular, active projects your field runs on.">
      {(feed.data ?? []).map((r, i) => <RepoRow key={r.full_name} r={r} rank={i + 1} />)}
      {feed.data && !feed.data.length ? <Empty>Nothing found for your keywords yet: add a few on the You tab.</Empty> : null}
      {!feed.data && !feed.loading ? <Empty>Pull down to load.</Empty> : null}
    </Screen>
  );
}

function ModelRow({ m }: { m: Model }) {
  const [owner, name] = m.id.split('/');
  return (
    <Card onPress={() => open(m.url, 'model', 'ai')}>
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

function Models({ top }: { top: React.ReactNode }) {
  const { settings } = useApp();
  const feed = useFeed('models', 6, (p) => fetchModels(p.weights, [...(settings?.keywords ?? []), ...(settings?.topics ?? [])]));
  return (
    <Screen title="Market" top={top} loading={feed.loading} onRefresh={feed.refresh} updated={feed.at} error={feed.error}
            subtitle="Trending on Hugging Face: first in your field, then everywhere.">
      <Section>IN YOUR FIELD{feed.data?.tags.length ? ` · ${feed.data.tags.join(', ')}` : ''}</Section>
      {(feed.data?.field ?? []).map((m) => <ModelRow key={m.id} m={m} />)}
      {feed.data && !feed.data.field.length ? <Empty>No field tags yet: add keywords on the You tab.</Empty> : null}
      {!feed.data && !feed.loading ? <Empty>Pull down to load.</Empty> : null}
      {feed.data?.trending.length ? <Section>🌍 TRENDING EVERYWHERE</Section> : null}
      {(feed.data?.trending ?? []).map((m) => <ModelRow key={`t${m.id}`} m={m} />)}
    </Screen>
  );
}

function LaunchRow({ l }: { l: Launch }) {
  return (
    <Card onPress={() => open(l.url, 'launch')}>
      <View style={s.row}>
        <Text style={{ fontSize: 20 }}>🚀</Text>
        <View style={{ flex: 1 }}>
          <Text style={[s.itemTitle, { fontWeight: '800' }]}>{l.name}</Text>
          {l.tagline ? <Text style={s.small}>{l.tagline}</Text> : null}
          {l.match.length ? <Text style={[s.small, { color: C.green }]}>your field: {l.match.slice(0, 3).join(', ')}</Text> : null}
        </View>
      </View>
    </Card>
  );
}

function Launches({ top }: { top: React.ReactNode }) {
  const feed = useFeed('launches', 6, (p) => fetchLaunches(p.weights));
  return (
    <Screen title="Market" top={top} loading={feed.loading} onRefresh={feed.refresh} updated={feed.at} error={feed.error}
            subtitle="Today's launches on Product Hunt, the ones in your field first.">
      {(feed.data ?? []).map((l) => <LaunchRow key={l.id} l={l} />)}
      {!feed.data && !feed.loading ? <Empty>Pull down to load.</Empty> : null}
    </Screen>
  );
}

export default function Market() {
  const [part, setPart] = useState<Part>('repos');
  const top = <Segments value={part} options={PARTS} onChange={setPart} />;
  return part === 'repos' ? <Repos top={top} /> : part === 'models' ? <Models top={top} /> : <Launches top={top} />;
}
