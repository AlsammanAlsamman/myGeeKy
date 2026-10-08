// The whole app on one screen: what you picked on top, the orbit below (under
// your thumb, clear of the phone's own buttons). Reading folds the orbit into a
// slim dock; scrolling back to the top, or "Spin the rings", brings it back.
import AsyncStorage from '@react-native-async-storage/async-storage';
import Ionicons from '@expo/vector-icons/Ionicons';
import { useEffect, useMemo, useState } from 'react';
import { Image, NativeScrollEvent, NativeSyntheticEvent, Pressable, RefreshControl, ScrollView, StyleSheet, Text,
         useWindowDimensions, View } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { Orbit, orbitHeight } from '../components/orbit';
import { Card, Empty, open, Segments } from '../components/ui';
import { BadgesPart, ModelPart, MorePart } from '../components/you-parts';
import { timeAgo, useApp, useFeed } from '../lib/app-state';
import { fetchHeadlines } from '../lib/headlines';
import { fetchLive } from '../lib/live';
import { fetchLaunches, fetchRepos } from '../lib/market';
import { fetchModels } from '../lib/models';
import { fetchPeople } from '../lib/people';
import { fetchResearch } from '../lib/research';
import { INNER, OUTER, RING_NAME, Row, rowsFor, SECTIONS, SectionId } from '../lib/sections';
import { C } from '../lib/theme';

const HINT_KEY = 'mygeeky.orbitHinted';
type YouPart = 'model' | 'badges' | 'more';
const YOU_PARTS: [YouPart, string][] = [['model', 'Your model'], ['badges', 'Badges'], ['more', 'More']];
const DOCK: SectionId[] = ['you', ...INNER, ...OUTER];

const EMPTY: Partial<Record<SectionId, string>> = {
  live: 'Nothing new around you yet. Pull down to check again.',
  activity: "The people you follow haven't done anything public lately.",
  people: 'No one found for your keywords yet: add a few in You → Your model.',
  news: 'No headlines yet. Pull down to load them.',
  papers: 'No rising papers found yet. Adding your ORCID (You → More → Start over) finds your exact field.',
  repos: 'Nothing found for your keywords yet: add a few in You → Your model.',
  models: 'No trending models yet. Pull down to load them.',
  launches: 'No launches yet. Pull down to load them.',
};

function RowView({ r, color, isOpen, onPick }: { r: Row; color: string; isOpen: boolean; onPick: () => void }) {
  return (
    <View style={[st.rowBox, isOpen && st.rowOpen]}>
      <Pressable onPress={onPick} style={st.row} accessibilityRole="button" accessibilityLabel={`${r.title}. ${r.sub}`}>
        {r.avatar ? (
          <Image source={{ uri: `${r.avatar}${r.avatar.includes('?') ? '&' : '?'}s=80` }} style={st.avatar} />
        ) : (
          <View style={[st.letter, { backgroundColor: r.letterBg }]}><Text style={[st.letterText, { color: r.letterFg }]}>{r.letter}</Text></View>
        )}
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text style={st.title} numberOfLines={isOpen ? undefined : 2}>{r.title}</Text>
          <Text style={st.sub} numberOfLines={isOpen ? undefined : 1}>{r.sub}</Text>
        </View>
        {r.right ? <Text style={st.right}>{r.right}</Text> : null}
      </Pressable>
      {isOpen ? (
        <View style={st.actions}>
          <Pressable onPress={() => open(r.url, r.kind, r.cat, r.explore)} style={[st.go, { backgroundColor: color }]}>
            <Text style={st.goText}>{r.action}</Text>
          </Pressable>
          <Pressable onPress={onPick} style={st.close} accessibilityLabel="Close"><Text style={st.closeText}>×</Text></Pressable>
        </View>
      ) : null}
    </View>
  );
}

export default function Home() {
  const { settings, token } = useApp();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const user = settings?.username ?? '';
  const keywords = [...(settings?.keywords ?? []), ...(settings?.topics ?? [])];

  const live = useFeed('live', 0.25, () => fetchLive(user, token));
  const people = useFeed('people', 12, (p) => fetchPeople(user, token, p.weights));
  const headlines = useFeed('headlines', 3, (p) => fetchHeadlines(p.weights));
  const research = useFeed('research', 12, (p) => fetchResearch(p));
  const repos = useFeed('market-repos', 24, (p) => fetchRepos(p.weights, token));
  const models = useFeed('models', 6, (p) => fetchModels(p.weights, keywords));
  const launches = useFeed('launches', 6, (p) => fetchLaunches(p.weights));
  const feedsOf: Record<SectionId, { loading: boolean; error: string | null; at: string | null; refresh: () => Promise<void> }[]> = {
    live: [live, people], activity: [live], people: [people], signals: [], news: [headlines], papers: [research],
    repos: [repos], models: [models], launches: [launches], you: [],
  };

  const [sel, setSel] = useState<SectionId>('live');
  const [collapsed, setCollapsed] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [youPart, setYouPart] = useState<YouPart>('model');
  const [hint, setHint] = useState(false);
  const [viewH, setViewH] = useState(0);

  useEffect(() => {
    AsyncStorage.getItem(HINT_KEY).then((v) => setHint(!v)).catch(() => undefined);
  }, []);
  const touched = () => {
    if (hint) {
      setHint(false);
      AsyncStorage.setItem(HINT_KEY, '1').catch(() => undefined);
    }
  };

  const data = {
    live: live.data, people: people.data, headlines: headlines.data, research: research.data,
    repos: repos.data, models: models.data, launches: launches.data,
  };
  const counts = useMemo(() => {
    const c: Partial<Record<SectionId, number>> = {};
    for (const id of [...INNER, ...OUTER]) c[id] = rowsFor(id, data).length;
    return c;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live.data, people.data, headlines.data, research.data, repos.data, models.data, launches.data]);
  const rows = rowsFor(sel, data);
  const section = SECTIONS[sel];
  const ring = INNER.includes(sel) ? RING_NAME.inner : OUTER.includes(sel) ? RING_NAME.outer : RING_NAME.you;
  const fs = feedsOf[sel];
  const loading = fs.some((f) => f.loading);
  const error = fs.map((f) => f.error).find(Boolean) ?? null;
  const at = fs.map((f) => f.at).filter(Boolean).sort()[0] ?? null;

  const pick = (id: SectionId) => {
    setSel(id);
    setOpenId(null);
    touched();
  };
  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const y = e.nativeEvent.contentOffset.y;
    if (y > 24 && !collapsed) setCollapsed(true);
    else if (y <= 0 && collapsed) setCollapsed(false);
  };
  const ringsH = collapsed ? 0 : orbitHeight(width);

  return (
    <SafeAreaView style={st.safe} edges={['top']}>
      <View style={st.panel}>
        <View style={st.head}>
          <Text style={st.h1}>{section.label}</Text>
          <Text style={[st.ring, { color: section.color }]}>{ring}</Text>
        </View>
        <Text style={st.about}>{section.about}</Text>
        {fs.length ? (
          <Text style={st.meta}>{loading ? 'updating…' : at ? `updated ${timeAgo(at)} · pull down to refresh` : ''}</Text>
        ) : null}
        {error ? <Text style={st.error}>{error}</Text> : null}
        {sel === 'you' ? <View style={{ marginTop: 10 }}><Segments value={youPart} options={YOU_PARTS} onChange={setYouPart} /></View> : null}

        <ScrollView
          onLayout={(e) => setViewH(e.nativeEvent.layout.height)}
          onScroll={onScroll} scrollEventThrottle={32}
          contentContainerStyle={[st.list, { minHeight: viewH + (collapsed ? 0 : 60) }]}
          refreshControl={fs.length ? (
            <RefreshControl refreshing={loading} onRefresh={() => fs.forEach((f) => f.refresh())} tintColor={C.pink} colors={[C.pink]} />
          ) : undefined}
        >
          {sel === 'you' ? (
            <View style={{ marginHorizontal: -4 }}>
              {youPart === 'model' ? <ModelPart /> : youPart === 'badges' ? <BadgesPart /> : <MorePart />}
            </View>
          ) : sel === 'signals' ? (
            <Card>
              <Text style={st.title}>Signals are on the desktop panel for now</Text>
              <Text style={[st.sub, { marginTop: 6 }]}>Private thank-yous and collab invites between myGeeKy users. They are coming to the phone.</Text>
            </Card>
          ) : rows.length ? rows.map((r) => (
            <RowView key={r.id} r={r} color={section.color} isOpen={openId === r.id}
                     onPick={() => {
                       setOpenId(openId === r.id ? null : r.id);
                       setCollapsed(true);                // reading: the rings make room
                       touched();
                     }} />
          )) : (
            <Empty>{loading ? 'Loading…' : error ? 'Pull down to try again.' : EMPTY[sel]}</Empty>
          )}
        </ScrollView>
      </View>

      {collapsed ? (
        <View style={st.dock}>
          <Pressable onPress={() => setCollapsed(false)} style={st.unfold} accessibilityLabel="Show the rings">
            <Ionicons name="chevron-up" size={16} color={C.muted} />
            <Text style={st.unfoldText}>Spin the rings</Text>
          </Pressable>
          <View style={st.dockRow}>
            {DOCK.map((id) => {
              const s = SECTIONS[id];
              const on = sel === id;
              return (
                <Pressable key={id} onPress={() => pick(id)} style={st.dockBtn} accessibilityRole="button"
                           accessibilityLabel={`${s.label}${counts[id] ? `, ${counts[id]} new` : ''}`}>
                  <View style={[st.dockDot, { borderColor: s.color, backgroundColor: on ? s.color : '#1c1c2c' }]}>
                    <Ionicons name={s.icon} size={15} color={on ? '#0d0d16' : s.color} />
                  </View>
                </Pressable>
              );
            })}
          </View>
        </View>
      ) : (
        <View style={{ height: ringsH }}>
          <Orbit width={width} sel={sel} counts={counts} onSelect={pick} hint={hint} onTouched={touched}
                 youLetter={(user[0] ?? '?').toUpperCase()} />
          <Pressable onPress={() => setCollapsed(true)} style={[st.fold, { top: ringsH - 50 }]} accessibilityLabel="Fold the rings away">
            <Ionicons name="chevron-down" size={20} color={C.muted} />
          </Pressable>
        </View>
      )}
      <View style={{ height: Math.max(insets.bottom, 12) + 8 }} />
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#0d0d16' },
  panel: { flex: 1, backgroundColor: '#14141f', borderBottomLeftRadius: 26, borderBottomRightRadius: 26,
           borderBottomWidth: 1, borderColor: 'rgba(255,255,255,0.10)', paddingTop: 12, overflow: 'hidden' },
  head: { flexDirection: 'row', alignItems: 'baseline', gap: 10, paddingHorizontal: 20 },
  h1: { color: C.text, fontSize: 26, fontWeight: '800', letterSpacing: -0.4 },
  ring: { fontSize: 11, fontWeight: '800', letterSpacing: 0.8 },
  about: { color: C.muted, fontSize: 13, lineHeight: 18, paddingHorizontal: 20, marginTop: 2 },
  meta: { color: C.muted, fontSize: 11, paddingHorizontal: 20, marginTop: 4 },
  error: { color: C.red, fontSize: 13, paddingHorizontal: 20, marginTop: 6 },
  list: { paddingHorizontal: 20, paddingTop: 6, paddingBottom: 16 },
  rowBox: { borderBottomWidth: 1, borderColor: 'rgba(255,255,255,0.07)' },
  rowOpen: { backgroundColor: 'rgba(255,255,255,0.04)', marginHorizontal: -12, paddingHorizontal: 12, borderRadius: 14 },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12 },
  avatar: { width: 38, height: 38, borderRadius: 19, backgroundColor: C.cardHi, alignItems: 'center', justifyContent: 'center' },
  letter: { width: 24, height: 24, borderRadius: 6, alignItems: 'center', justifyContent: 'center' },
  letterText: { fontSize: 12, fontWeight: '900' },
  title: { color: C.text, fontSize: 15, fontWeight: '700', lineHeight: 20 },
  sub: { color: C.muted, fontSize: 12, marginTop: 3 },
  right: { color: C.muted, fontSize: 12 },
  actions: { flexDirection: 'row', gap: 8, paddingBottom: 12 },
  go: { flex: 1, minHeight: 44, borderRadius: 12, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 10 },
  goText: { color: '#0d0d16', fontSize: 14, fontWeight: '800' },
  close: { width: 44, minHeight: 44, borderRadius: 12, backgroundColor: 'rgba(255,255,255,0.08)', alignItems: 'center', justifyContent: 'center' },
  closeText: { color: C.text, fontSize: 20 },
  dock: { paddingHorizontal: 6, paddingTop: 2 },
  unfold: { height: 30, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
  unfoldText: { color: C.muted, fontSize: 12, fontWeight: '700' },
  dockRow: { flexDirection: 'row', justifyContent: 'space-between' },
  dockBtn: { flex: 1, height: 48, alignItems: 'center', justifyContent: 'center' },
  dockDot: { width: 34, height: 34, borderRadius: 17, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  fold: { position: 'absolute', right: 10, width: 44, height: 44, borderRadius: 22, backgroundColor: 'rgba(255,255,255,0.06)',
          alignItems: 'center', justifyContent: 'center' },
});
