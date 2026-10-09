// Someone at a glance, unfolding inside a list (or on its own screen): their two
// most active repos, their most-starred one, 30 days of activity, their
// interests and their links elsewhere. Then, if you like, GitHub to follow.
import Ionicons from '@expo/vector-icons/Ionicons';
import { useEffect, useState } from 'react';
import { Animated, Easing, Image, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { open } from './ui';
import { timeAgo, useApp } from '../lib/app-state';
import { Card, CardRepo, fetchCard, LinkKind } from '../lib/profile-card';
import { C } from '../lib/theme';

const MARKS: Record<LinkKind, { label: string; color: string; icon?: keyof typeof Ionicons.glyphMap; text?: string }> = {
  linkedin: { label: 'LinkedIn', color: '#0a66c2', icon: 'logo-linkedin' },
  orcid: { label: 'ORCID', color: '#a6ce39', text: 'iD' },
  scholar: { label: 'Google Scholar', color: '#4285f4', icon: 'school' },
  researchgate: { label: 'ResearchGate', color: '#00ccbb', text: 'RG' },
  facebook: { label: 'Facebook', color: '#1877f2', icon: 'logo-facebook' },
  x: { label: 'X', color: '#3a3a44', icon: 'logo-twitter' },
  web: { label: 'Website', color: '#4b5563', icon: 'globe-outline' },
};

/** A slim loading bar: a pink-to-violet glow sweeping across a faint track. */
export function ShimmerBar() {
  const [x] = useState(() => new Animated.Value(0));
  const [w, setW] = useState(300);
  useEffect(() => {
    const loop = Animated.loop(Animated.timing(x, {
      toValue: 1, duration: 1100, easing: Easing.inOut(Easing.cubic), useNativeDriver: Platform.OS !== 'web',
    }));
    loop.start();
    return () => loop.stop();
  }, [x]);
  const seg = w * 0.38;
  return (
    <View style={st.track} onLayout={(e) => setW(e.nativeEvent.layout.width)}>
      <Animated.View style={[st.glow, { width: seg, transform: [{ translateX: x.interpolate({ inputRange: [0, 1], outputRange: [-seg, w] }) }] }]}>
        <View style={{ flex: 1, backgroundColor: C.pink }} />
        <View style={{ flex: 1, backgroundColor: C.violet }} />
      </Animated.View>
    </View>
  );
}

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

export function PersonCard({ login, onClose }: { login: string; onClose?: () => void }) {
  const { token } = useApp();
  const [card, setCard] = useState<Card | null>(null);
  const [error, setError] = useState('');
  const [fade] = useState(() => new Animated.Value(0));
  useEffect(() => {
    let alive = true;
    fetchCard(login, token).then((c) => {
      if (!alive) return;
      setCard(c);
      Animated.timing(fade, { toValue: 1, duration: 320, useNativeDriver: Platform.OS !== 'web' }).start();
    }).catch((e) => {
      if (alive) setError(e instanceof Error ? e.message : String(e));
    });
    return () => {
      alive = false;
    };
  }, [login, token, fade]);

  if (!card) {
    return (
      <View style={st.box}>
        <Text style={st.muted}>{error || `Looking up ${login}…`}</Text>
        {error ? null : <ShimmerBar />}
      </View>
    );
  }
  return (
    <Animated.View style={[st.box, { opacity: fade.interpolate({ inputRange: [0, 1], outputRange: [0.5, 1] }), transform: [{ translateY: fade.interpolate({ inputRange: [0, 1], outputRange: [8, 0] }) }] }]}>
      <View style={st.head}>
        <Image source={{ uri: `${card.avatar}${card.avatar.includes('?') ? '&' : '?'}s=144` }} style={st.avatar} />
        <View style={{ flex: 1 }}>
          <Text style={st.name}>{card.name || card.login}{card.name ? <Text style={st.muted}>  @{card.login}</Text> : null}</Text>
          <Text style={[st.muted, { marginTop: 3 }]}>
            {[card.location, card.company, `${card.followers.toLocaleString()} followers`, `${card.publicRepos} repos`,
              card.since ? `since ${card.since}` : ''].filter(Boolean).join('  ·  ')}
          </Text>
        </View>
        {onClose ? (
          <Pressable onPress={onClose} style={st.x} accessibilityLabel="Fold it away">
            <Ionicons name="close" size={18} color={C.muted} />
          </Pressable>
        ) : null}
      </View>
      {card.bio ? <Text style={st.bio}>{card.bio}</Text> : null}
      {card.links.length ? (
        <View style={st.links}>
          {card.links.map((l) => {
            const m = MARKS[l.kind];
            return (
              <Pressable key={l.kind} onPress={() => open(l.url)} style={[st.link, { backgroundColor: m.color }]} accessibilityLabel={m.label}>
                {m.icon ? <Ionicons name={m.icon} size={18} color="#fff" /> : <Text style={st.linkText}>{m.text}</Text>}
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
    </Animated.View>
  );
}

const st = StyleSheet.create({
  box: { backgroundColor: 'rgba(255,255,255,0.04)', borderColor: 'rgba(127,216,255,0.5)', borderWidth: 1, borderRadius: 14,
         padding: 14, marginBottom: 12, gap: 2 },
  track: { height: 5, borderRadius: 3, backgroundColor: 'rgba(255,255,255,0.10)', overflow: 'hidden', marginTop: 10 },
  glow: { position: 'absolute', top: 0, bottom: 0, flexDirection: 'row', borderRadius: 3, overflow: 'hidden' },
  x: { width: 36, height: 36, alignItems: 'center', justifyContent: 'center' },
  head: { flexDirection: 'row', gap: 12, alignItems: 'center' },
  avatar: { width: 56, height: 56, borderRadius: 28, backgroundColor: C.cardHi },
  name: { color: C.text, fontSize: 18, fontWeight: '800' },
  muted: { color: C.muted, fontSize: 12.5, lineHeight: 18 },
  bio: { color: C.text, fontSize: 14, lineHeight: 20, marginTop: 10 },
  links: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 12 },
  link: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  linkText: { color: '#fff', fontWeight: '900', fontSize: 14 },
  section: { color: C.muted, fontSize: 11, fontWeight: '800', letterSpacing: 0.8, marginTop: 16, marginBottom: 8 },
  repo: { backgroundColor: C.card, borderColor: C.line, borderWidth: 1, borderRadius: 12, padding: 11, marginBottom: 8 },
  repoName: { color: C.text, fontSize: 15, fontWeight: '800' },
  chart: { flexDirection: 'row', alignItems: 'flex-end', height: 48, gap: 3 },
  bar: { flex: 1, borderRadius: 2, backgroundColor: C.cyan },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { backgroundColor: 'rgba(122,92,255,0.18)', borderRadius: 999, paddingHorizontal: 11, paddingVertical: 6 },
  chipText: { color: C.text, fontSize: 13 },
  follow: { backgroundColor: C.violet, borderRadius: 12, paddingVertical: 13, alignItems: 'center', marginTop: 16 },
  followText: { color: '#fff', fontSize: 16, fontWeight: '800' },
});
