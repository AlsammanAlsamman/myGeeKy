// You, in the centre of the orbit: your model (keywords), your badges, and the rest.
import Constants from 'expo-constants';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Alert, Image, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { SignInButton } from './signin';
import { Card, Empty, open, s, Section } from './ui';
import { useApp } from '../lib/app-state';
import { Achievement, earned, Earned, githubAchievements, TIER_COLORS } from '../lib/badges';
import { Dict, lookup } from '../lib/interests';
import { loadDictionary } from '../lib/profile';
import { clearAll } from '../lib/storage';
import { C } from '../lib/theme';


export function ModelPart() {
  const { settings, profile, save } = useApp();
  const [word, setWord] = useState('');
  const [dict, setDict] = useState<Dict | null>(null);
  useEffect(() => {
    loadDictionary().then(setDict);
  }, []);
  if (!settings) return null;
  const addKeyword = async () => {
    const w = word.trim();
    setWord('');
    if (!w || settings.keywords.some((k) => k.toLowerCase() === w.toLowerCase())) return;
    await save({ ...settings, keywords: [...settings.keywords, w] });
  };
  const removeKeyword = (k: string) => save({ ...settings, keywords: settings.keywords.filter((x) => x !== k) });
  return (
    <>
      <Section>🔤 YOUR KEYWORDS</Section>
      <View style={st.chips}>
        {settings.keywords.map((k) => {
          const known = !dict || !!lookup(dict, k);
          return (
            <Pressable key={k} onPress={() => removeKeyword(k)} style={[st.chip, !known && st.chipNew]}>
              <Text style={[st.chipText, !known && { color: C.red }]}>{k}  ✕</Text>
            </Pressable>
          );
        })}
      </View>
      <View style={st.addRow}>
        <TextInput style={st.input} value={word} onChangeText={setWord} onSubmitEditing={addKeyword}
                   placeholder="Add a keyword: AI, single cell…" placeholderTextColor={C.muted} returnKeyType="done" />
        <Pressable style={st.add} onPress={addKeyword}><Text style={st.addText}>Add</Text></Pressable>
      </View>
      <Text style={s.small}>Green keywords carry their related words with them. Red ones are new to myGeeKy, so
        they only match as written.</Text>

      <Section>🧭 YOUR RESEARCH FIELD</Section>
      <Card>
        <Text style={st.body}>
          {profile?.field.length ? profile.field.join(' · ') :
            settings.orcid ? 'Looking it up from your ORCID…' : 'Add your ORCID (More → Start over) to find your exact research field.'}
        </Text>
        {settings.orcid ? <Text style={st.link} onPress={() => open(`https://orcid.org/${settings.orcid}`)}>ORCID {settings.orcid} ↗</Text> : null}
      </Card>

      <Section>🧠 WHAT YOUR FEEDS LOOK FOR</Section>
      <View style={st.chips}>
        {Object.entries(profile?.weights ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 24).map(([t, w]) => (
          <View key={t} style={[st.weight, { opacity: 0.45 + 0.55 * Math.min(w, 1) }]}><Text style={st.weightText}>{t}</Text></View>
        ))}
      </View>
    </>
  );
}

export function BadgesPart() {
  const { settings } = useApp();
  const [mine, setMine] = useState<Earned[]>([]);
  const [gh, setGh] = useState<Achievement[]>([]);
  useEffect(() => {
    earned(settings?.keywords.length ?? 0, settings?.desktopBadges ?? []).then(setMine);
    if (settings?.username) githubAchievements(settings.username).then(setGh);
  }, [settings]);
  return (
    <>
      <Section>🏅 MYGEEKY BADGES</Section>
      {mine.map((b) => (
        <Card key={b.id}>
          <View style={[s.row, { alignItems: 'center' }]}>
            <View style={[st.medal, { borderColor: b.tier ? TIER_COLORS[b.tier] : C.line, opacity: b.tier ? 1 : 0.45 }]}>
              <Text style={{ fontSize: 20 }}>{b.emoji}</Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s.name}>{b.name}{b.tier ? <Text style={{ color: TIER_COLORS[b.tier] }}>  {b.tier}</Text> : null}</Text>
              <Text style={s.small}>{b.count} {b.what}{b.next ? ` · next at ${b.next}` : ''}</Text>
            </View>
          </View>
        </Card>
      ))}
      <Section>🐙 ON GITHUB</Section>
      {gh.length ? (
        <View style={st.chips}>
          {gh.map((a) => (
            <View key={a.name} style={{ alignItems: 'center', width: 76 }}>
              <Image source={{ uri: a.image }} style={{ width: 56, height: 56 }} />
              <Text style={[s.small, { textAlign: 'center' }]} numberOfLines={2}>{a.name}</Text>
            </View>
          ))}
        </View>
      ) : <Empty>No GitHub achievements found on your profile yet.</Empty>}
    </>
  );
}

export function MorePart() {
  const { settings, token, save } = useApp();
  if (!settings) return null;
  const reset = async () => {
    const go = async () => {
      await clearAll();
      router.replace('/setup');
    };
    if (Platform.OS === 'web') return go();
    Alert.alert('Start over?', 'This forgets your settings and sign-in on this phone.', [
      { text: 'Cancel', style: 'cancel' }, { text: 'Start over', style: 'destructive', onPress: go },
    ]);
  };
  const rows: [string, string, boolean][] = [
    ['GitHub', settings.username, true],
    ['Signed in', token ? 'yes: Live and People refresh freely' : 'no (sign in below)', !!token],
    ['ORCID', settings.orcid || 'not set', !!settings.orcid],
    ['Keywords', settings.keywords.length ? settings.keywords.join(', ') : 'none yet (add them in Your model)', settings.keywords.length > 0],
    ['From computer', Object.keys(settings.interests ?? {}).length
      ? `${Object.keys(settings.interests).length} interests, ${settings.field?.length ?? 0} research topics, ${settings.desktopBadges?.length ?? 0} badges`
      : 'nothing yet: scan the code above', Object.keys(settings.interests ?? {}).length > 0],
    ['Signals', 'on the desktop panel for now', false],
    ['App version', Constants.expoConfig?.version ?? '', true],
  ];
  return (
    <>
      <Pressable onPress={() => router.push('/scan')} style={st.scan}>
        <Text style={st.scanTitle}>📷  Scan from your computer</Text>
        <Text style={st.scanSub}>On your computer: ⚙ → Connect your phone. One scan brings over your profile, your
          interests and your badges (do it again any time to refresh them).</Text>
      </Pressable>

      <Section>⚙️ YOUR SETUP</Section>
      <Card>
        {rows.map(([k, v, on]) => (
          <View key={k} style={st.setupRow}>
            <Text style={st.setupKey}>{k}</Text>
            <Text style={[st.setupVal, !on && { color: C.muted }]}>{v}</Text>
          </View>
        ))}
      </Card>

      <Section>🔑 GITHUB</Section>
      <Card>
        <Text style={st.body}>{token ? 'Signed in: Live and People refresh freely. Read-only: myGeeKy can never follow, star or post.'
          : 'Sign in so Live and People can refresh freely. Read-only: myGeeKy can never follow, star or post.'}</Text>
        {!token ? (
          <SignInButton onSignedIn={async (login, t) => {
            if (login.toLowerCase() !== settings.username.toLowerCase()) {
              throw new Error(`You signed in as ${login}, but this phone is set up for ${settings.username}.`);
            }
            await save(settings, t);
          }} />
        ) : null}
      </Card>

      <Section>📡 SIGNALS</Section>
      <Card>
        <Text style={st.body}>Private thank-yous and collab invites between myGeeKy users live on the desktop panel
          for now. They are coming to the phone.</Text>
      </Card>

      <Section>🔒 PRIVACY</Section>
      <Card>
        <Text style={st.body}>Everything stays on this phone. myGeeKy only reads public data (news feeds, OpenAlex,
          Hugging Face, Product Hunt, GitHub) and never posts, follows or stars anything for you.</Text>
      </Card>

      <Pressable onPress={() => open('https://mygeeky.org')}>
        <Text style={[st.link, { marginTop: 18 }]}>myGeeKy for your computer ↗</Text>
      </Pressable>
      <Pressable onPress={reset}><Text style={[st.link, { color: C.red, marginTop: 14 }]}>Start over</Text></Pressable>
    </>
  );
}

const st = StyleSheet.create({
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { backgroundColor: 'rgba(52,211,153,0.14)', borderColor: 'rgba(52,211,153,0.5)', borderWidth: 1, borderRadius: 999,
          paddingHorizontal: 12, paddingVertical: 7 },
  chipNew: { backgroundColor: 'rgba(248,113,113,0.12)', borderColor: 'rgba(248,113,113,0.5)' },
  chipText: { color: C.green, fontWeight: '700', fontSize: 14 },
  weight: { backgroundColor: 'rgba(122,92,255,0.18)', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 },
  weightText: { color: C.text, fontSize: 12 },
  addRow: { flexDirection: 'row', gap: 8, marginTop: 10, marginBottom: 6 },
  input: { flex: 1, backgroundColor: C.card, borderColor: C.line, borderWidth: 1, borderRadius: 12, color: C.text,
           paddingHorizontal: 12, paddingVertical: 10, fontSize: 15 },
  add: { backgroundColor: C.violet, borderRadius: 12, paddingHorizontal: 16, justifyContent: 'center' },
  addText: { color: '#fff', fontWeight: '800' },
  body: { color: C.text, fontSize: 14, lineHeight: 20 },
  link: { color: C.cyan, fontSize: 14, marginTop: 8 },
  scan: { backgroundColor: 'rgba(255,111,216,0.12)', borderColor: 'rgba(255,111,216,0.45)', borderWidth: 1,
          borderRadius: 16, padding: 14, marginTop: 6 },
  scanTitle: { color: C.text, fontSize: 16, fontWeight: '800' },
  scanSub: { color: C.muted, fontSize: 12.5, marginTop: 5, lineHeight: 17 },
  setupRow: { flexDirection: 'row', paddingVertical: 4, gap: 10 },
  setupKey: { color: C.muted, fontSize: 13, width: 92 },
  setupVal: { color: C.text, fontSize: 13, flex: 1 },
  medal: { width: 42, height: 42, borderRadius: 21, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
});
