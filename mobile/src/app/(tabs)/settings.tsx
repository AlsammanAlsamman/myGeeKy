import { router } from 'expo-router';
import { useState } from 'react';
import { Alert, Platform, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { Card, open, Screen, Section } from '../../components/ui';
import { useApp } from '../../lib/app-state';
import { clearAll } from '../../lib/storage';
import { C } from '../../lib/theme';

// You: who myGeeKy thinks you are, your keywords, and where everything is stored.
export default function You() {
  const { settings, profile, token, save } = useApp();
  const [word, setWord] = useState('');
  if (!settings) return null;

  const addKeyword = async () => {
    const w = word.trim();
    if (!w || settings.keywords.some((k) => k.toLowerCase() === w.toLowerCase())) return setWord('');
    setWord('');
    await save({ ...settings, keywords: [...settings.keywords, w] });
  };
  const removeKeyword = (k: string) => save({ ...settings, keywords: settings.keywords.filter((x) => x !== k) });
  const reset = async () => {
    const go = async () => {
      await clearAll();
      router.replace('/setup');
    };
    if (Platform.OS === 'web') return go();
    Alert.alert('Start over?', 'This forgets your settings and token on this phone.', [
      { text: 'Cancel', style: 'cancel' }, { text: 'Start over', style: 'destructive', onPress: go },
    ]);
  };

  return (
    <Screen title={`@${settings.username}`} subtitle="What myGeeKy knows about you, on this phone.">
      <Section>🔤 YOUR KEYWORDS</Section>
      <View style={st.chips}>
        {settings.keywords.map((k) => (
          <Pressable key={k} onPress={() => removeKeyword(k)} style={st.chip}>
            <Text style={st.chipText}>{k}  ✕</Text>
          </Pressable>
        ))}
      </View>
      <View style={st.addRow}>
        <TextInput style={st.input} value={word} onChangeText={setWord} onSubmitEditing={addKeyword}
                   placeholder="Add a keyword: AI, single cell…" placeholderTextColor={C.muted} returnKeyType="done" />
        <Pressable style={st.add} onPress={addKeyword}><Text style={st.addText}>Add</Text></Pressable>
      </View>

      <Section>🧭 YOUR RESEARCH FIELD</Section>
      <Card>
        <Text style={st.body}>
          {profile?.field.length ? profile.field.join(' · ') :
            settings.orcid ? 'Looking it up from your ORCID…' : 'Add your ORCID (Start over, below) to find your exact research field.'}
        </Text>
        {settings.orcid ? <Text style={st.link} onPress={() => open(`https://orcid.org/${settings.orcid}`)}>ORCID {settings.orcid} ↗</Text> : null}
      </Card>

      <Section>🔒 PRIVACY</Section>
      <Card>
        <Text style={st.body}>Everything stays on this phone. myGeeKy only reads public data (news feeds, OpenAlex,
          Hugging Face, GitHub) and never posts, follows or stars anything for you.</Text>
        <Text style={[st.body, { marginTop: 8 }]}>GitHub token: {token ? 'saved in secure storage' : 'none'}</Text>
      </Card>

      <Pressable onPress={() => open('https://github.com/AlsammanAlsamman/myGeeKy')}>
        <Text style={[st.link, { marginTop: 18 }]}>myGeeKy on GitHub (and the desktop panel) ↗</Text>
      </Pressable>
      <Pressable onPress={reset}><Text style={[st.link, { color: C.red, marginTop: 14 }]}>Start over</Text></Pressable>
    </Screen>
  );
}

const st = StyleSheet.create({
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { backgroundColor: 'rgba(52,211,153,0.14)', borderColor: 'rgba(52,211,153,0.5)', borderWidth: 1, borderRadius: 999,
          paddingHorizontal: 12, paddingVertical: 7 },
  chipText: { color: C.green, fontWeight: '700', fontSize: 14 },
  addRow: { flexDirection: 'row', gap: 8, marginTop: 10 },
  input: { flex: 1, backgroundColor: C.card, borderColor: C.line, borderWidth: 1, borderRadius: 12, color: C.text,
           paddingHorizontal: 12, paddingVertical: 10, fontSize: 15 },
  add: { backgroundColor: C.violet, borderRadius: 12, paddingHorizontal: 16, justifyContent: 'center' },
  addText: { color: '#fff', fontWeight: '800' },
  body: { color: C.text, fontSize: 14, lineHeight: 20 },
  link: { color: C.cyan, fontSize: 14, marginTop: 8 },
});
