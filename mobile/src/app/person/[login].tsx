// Someone at a glance, before you (maybe) open GitHub to follow them.
import Ionicons from '@expo/vector-icons/Ionicons';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Image, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { open } from '../../components/ui';
import { timeAgo, useApp } from '../../lib/app-state';
import { Card, CardRepo, fetchCard, LinkKind } from '../../lib/profile-card';
import { C } from '../../lib/theme';

const MARKS: Record<LinkKind, { label: string; color: string; icon?: keyof typeof Ionicons.glyphMap; text?: string }> = {
  linkedin: { label: 'LinkedIn', color: '#0a66c2', icon: 'logo-linkedin' },
  orcid: { label: 'ORCID', color: '#a6ce39', text: 'iD' },
  scholar: { label: 'Google Scholar', color: '#4285f4', icon: 'school' },
  researchgate: { label: 'ResearchGate', color: '#00ccbb', text: 'RG' },
  facebook: { label: 'Facebook', color: '#1877f2', icon: 'logo-facebook' },
  x: { label: 'X', color: '#3a3a44', icon: 'logo-twitter' },
  web: { label: 'Website', color: '#4b5563', icon: 'globe-outline' },
};

function RepoRow({ r, right }: { r: CardRepo; right: string }) {
  return (
    <Pressable onPress={() => open(r.url, 'repo')} style={({ pressed }) => [st.repo, pressed && { backgroundColor: C.cardHi }]}>
      <Text style={st.repoName}>{r.name}  <Text style={st.muted}>{[r.language, right].filter(Boolean).join('  ·  ')}</Text></Text>
      {r.description ? <Text style={[st.muted, { marginTop: 3 }]}>{r.description}</Text> : null}
    </Pressable>
  );
}

function Chart({ counts }: { counts: number[] }) {
  const top = Math.max(1, ...counts);
  return (
    <View style={st.chart}>
      {counts.map((c, i) => (
        <View key={i} style={[st.bar, { height: c ? 6 + 40 * (c / top) : 3, opacity: c ? 1 : 0.25 }]} />
      ))}
    </View>
  );
}

export default function Person() {
  const { login } = useLocalSearchParams<{ login: string }>();
  const { token } = useApp();
  const [card, setCard] = useState<Card | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    fetchCard(String(login), token).then(setCard).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [login, token]);

  return (
    <SafeAreaView style={st.safe} edges={['top', 'bottom']}>
      <View style={st.top}>
        <Pressable onPress={() => router.back()} style={st.back} accessibilityLabel="Back">
          <Ionicons name="chevron-back" size={22} color={C.text} />
        </Pressable>
        <Text style={st.topTitle} numberOfLines={1}>@{login}</Text>
      </View>
      {!card ? (
        <View style={st.center}>{error ? <Text style={st.error}>{error}</Text> : <ActivityIndicator color={C.pink} />}</View>
      ) : (
        <ScrollView contentContainerStyle={st.body}>
          <View style={st.head}>
            <Image source={{ uri: `${card.avatar}${card.avatar.includes('?') ? '&' : '?'}s=160` }} style={st.avatar} />
            <View style={{ flex: 1 }}>
              <Text style={st.name}>{card.name || card.login}</Text>
              {card.name ? <Text style={st.muted}>@{card.login}</Text> : null}
              <Text style={[st.muted, { marginTop: 4 }]}>
                {[card.location, card.company, `${card.followers.toLocaleString()} followers`, `${card.publicRepos} repos`,
                  card.since ? `since ${card.since}` : ''].filter(Boolean).join('  ·  ')}
              </Text>
            </View>
          </View>
          {card.bio ? <Text style={st.bio}>{card.bio}</Text> : null}
          {card.links.length ? (
            <View style={st.links}>
              {card.links.map((l) => {
                const m = MARKS[l.kind];
                return (
                  <Pressable key={l.kind} onPress={() => open(l.url)} style={[st.link, { backgroundColor: m.color }]}
                             accessibilityLabel={m.label}>
                    {m.icon ? <Ionicons name={m.icon} size={20} color="#fff" /> : <Text style={st.linkText}>{m.text}</Text>}
                  </Pressable>
                );
              })}
            </View>
          ) : null}
          {card.active.length ? <Text style={st.section}>MOST ACTIVE</Text> : null}
          {card.active.map((r) => <RepoRow key={r.url} r={r} right={r.pushedAt ? `pushed ${timeAgo(r.pushedAt)}` : ''} />)}
          {card.top ? <Text style={st.section}>MOST STARRED</Text> : null}
          {card.top ? <RepoRow r={card.top} right={`★ ${card.top.stars.toLocaleString()}`} /> : null}
          <Text style={st.section}>ACTIVITY, LAST 30 DAYS · {card.daily.reduce((a, b) => a + b, 0)} public events</Text>
          <Chart counts={card.daily} />
          {card.interests.length ? <Text style={st.section}>INTERESTS</Text> : null}
          <View style={st.chips}>
            {card.interests.map((t) => <View key={t} style={st.chip}><Text style={st.chipText}>{t}</Text></View>)}
          </View>
          <Pressable onPress={() => open(card.url, 'person')} style={({ pressed }) => [st.follow, pressed && { opacity: 0.85 }]}>
            <Text style={st.followText}>Open on GitHub to follow</Text>
          </Pressable>
          <Text style={[st.muted, { textAlign: 'center', marginTop: 8 }]}>myGeeKy never follows anyone for you.</Text>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: C.bg },
  top: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 8, paddingVertical: 6 },
  back: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  topTitle: { color: C.muted, fontSize: 15, fontWeight: '700', flex: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  error: { color: C.red, fontSize: 14, textAlign: 'center' },
  body: { padding: 18, paddingBottom: 40 },
  head: { flexDirection: 'row', gap: 14, alignItems: 'center' },
  avatar: { width: 72, height: 72, borderRadius: 36, backgroundColor: C.cardHi },
  name: { color: C.text, fontSize: 22, fontWeight: '800' },
  muted: { color: C.muted, fontSize: 12.5, lineHeight: 18 },
  bio: { color: C.text, fontSize: 14, lineHeight: 20, marginTop: 12 },
  links: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 14 },
  link: { width: 44, height: 44, borderRadius: 22, alignItems: 'center', justifyContent: 'center' },
  linkText: { color: '#fff', fontWeight: '900', fontSize: 15 },
  section: { color: C.muted, fontSize: 11, fontWeight: '800', letterSpacing: 0.8, marginTop: 20, marginBottom: 8 },
  repo: { backgroundColor: C.card, borderColor: C.line, borderWidth: 1, borderRadius: 12, padding: 12, marginBottom: 8 },
  repoName: { color: C.text, fontSize: 15, fontWeight: '800' },
  chart: { flexDirection: 'row', alignItems: 'flex-end', height: 48, gap: 3 },
  bar: { flex: 1, borderRadius: 2, backgroundColor: C.cyan },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { backgroundColor: 'rgba(122,92,255,0.18)', borderRadius: 999, paddingHorizontal: 11, paddingVertical: 6 },
  chipText: { color: C.text, fontSize: 13 },
  follow: { backgroundColor: C.violet, borderRadius: 14, paddingVertical: 15, alignItems: 'center', marginTop: 24 },
  followText: { color: '#fff', fontSize: 16, fontWeight: '800' },
});
