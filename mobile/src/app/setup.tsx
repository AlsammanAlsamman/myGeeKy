import { router } from 'expo-router';
import { useState } from 'react';
import { Image, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useApp } from '../lib/app-state';
import { DEFAULT_SETTINGS } from '../lib/storage';
import { C } from '../lib/theme';

const split = (v: string) => v.split(',').map((x) => x.trim()).filter(Boolean);

// Who you are: only your GitHub username is required. Your ORCID and keywords
// make every list much better. The token is optional (and stays on this phone).
export default function Setup() {
  const { settings, save } = useApp();
  const [username, setUsername] = useState(settings?.username ?? '');
  const [orcid, setOrcid] = useState(settings?.orcid ?? '');
  const [keywords, setKeywords] = useState(settings?.keywords.join(', ') ?? '');
  const [token, setToken] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const u = username.trim().replace(/^@/, '');
    if (!/^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/.test(u)) return setError('That isn\'t a GitHub username.');
    const o = orcid.trim().replace(/^https?:\/\/orcid\.org\//, '');
    if (o && !/^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/.test(o)) return setError('An ORCID looks like 0000-0002-1825-0097.');
    setBusy(true);
    setError('');
    await save({ ...(settings ?? DEFAULT_SETTINGS), username: u, orcid: o, keywords: split(keywords) }, token.trim() || undefined);
    setBusy(false);
    router.replace('/headlines');
  };

  return (
    <SafeAreaView style={st.safe}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={st.wrap} keyboardShouldPersistTaps="handled">
          <Image source={require('../../assets/icon.png')} style={st.logo} />
          <Text style={st.brand}>myGeeKy</Text>
          <Text style={st.lead}>{"What's new in your field: research, AI news and models, picked for your own work."}</Text>

          <Pressable style={({ pressed }) => [st.scan, pressed && { opacity: 0.85 }]} onPress={() => router.push('/scan')}>
            <Text style={st.scanTitle}>📷  Scan from your computer</Text>
            <Text style={st.scanSub}>Already use myGeeKy on your computer? Open ⚙ → Connect your phone there, and
              scan the code: everything is set up at once.</Text>
          </Pressable>
          <Text style={st.or}>or fill it in</Text>

          <Text style={st.label}>GitHub username</Text>
          <TextInput style={st.input} value={username} onChangeText={setUsername} autoCapitalize="none"
                     autoCorrect={false} placeholder="e.g. octocat" placeholderTextColor={C.muted} />

          <Text style={st.label}>ORCID <Text style={st.opt}>(optional, but it finds your research field)</Text></Text>
          <TextInput style={st.input} value={orcid} onChangeText={setOrcid} autoCapitalize="none"
                     placeholder="0000-0002-1825-0097" placeholderTextColor={C.muted} />

          <Text style={st.label}>Keywords <Text style={st.opt}>(comma separated)</Text></Text>
          <TextInput style={st.input} value={keywords} onChangeText={setKeywords}
                     placeholder="GWAS, single cell, AI" placeholderTextColor={C.muted} />

          <Text style={st.label}>GitHub token <Text style={st.opt}>(optional: read-only)</Text></Text>
          <TextInput style={st.input} value={token} onChangeText={setToken} autoCapitalize="none" secureTextEntry
                     placeholder="github_pat_…" placeholderTextColor={C.muted} />
          <Text style={st.hint}>{"Only needed later, for People. It stays in this phone's secure storage."}</Text>

          {error ? <Text style={st.error}>{error}</Text> : null}
          <Pressable style={({ pressed }) => [st.button, pressed && { opacity: 0.85 }]} onPress={submit} disabled={busy}>
            <Text style={st.buttonText}>{busy ? 'Getting to know your field…' : 'Start'}</Text>
          </Pressable>
          <Text style={st.hint}>myGeeKy only suggests. It never follows, stars or posts for you.</Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: C.bg },
  wrap: { padding: 22, paddingBottom: 48 },
  logo: { width: 84, height: 84, alignSelf: 'center', marginTop: 8 },
  brand: { color: C.pink, fontSize: 34, fontWeight: '900', textAlign: 'center', marginTop: 10, letterSpacing: -0.8 },
  lead: { color: C.muted, fontSize: 15, textAlign: 'center', marginTop: 6, marginBottom: 18, lineHeight: 21 },
  label: { color: C.text, fontSize: 14, fontWeight: '700', marginTop: 14, marginBottom: 6 },
  opt: { color: C.muted, fontWeight: '400' },
  input: { backgroundColor: C.card, borderColor: C.line, borderWidth: 1, borderRadius: 12, color: C.text,
           paddingHorizontal: 14, paddingVertical: 12, fontSize: 16 },
  hint: { color: C.muted, fontSize: 12, marginTop: 8, lineHeight: 17 },
  error: { color: C.red, fontSize: 14, marginTop: 14 },
  scan: { backgroundColor: 'rgba(255,111,216,0.12)', borderColor: 'rgba(255,111,216,0.45)', borderWidth: 1,
          borderRadius: 16, padding: 16 },
  scanTitle: { color: C.text, fontSize: 17, fontWeight: '800' },
  scanSub: { color: C.muted, fontSize: 13, marginTop: 6, lineHeight: 18 },
  or: { color: C.muted, textAlign: 'center', marginTop: 16, marginBottom: 2, fontSize: 13 },
  button: { backgroundColor: C.violet, borderRadius: 14, paddingVertical: 15, marginTop: 22, alignItems: 'center' },
  buttonText: { color: '#fff', fontSize: 16, fontWeight: '800' },
});

void View;
