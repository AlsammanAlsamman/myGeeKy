// "Sign in with GitHub": the device flow -- show a code, open GitHub, wait.
import * as Clipboard from 'expo-clipboard';
import { useRef, useState } from 'react';
import { Linking, Pressable, StyleSheet, Text } from 'react-native';
import { startLogin, waitForLogin, whoAmI } from '../lib/github-login';
import { C } from '../lib/theme';

export function SignInButton({ onSignedIn, signedInAs }: {
  onSignedIn: (login: string, token: string) => void | Promise<void>; signedInAs?: string;
}) {
  const [code, setCode] = useState('');
  const [note, setNote] = useState('');
  const busy = useRef(false);

  const go = async () => {
    if (busy.current) return;
    busy.current = true;
    setNote('Asking GitHub for a code…');
    try {
      const flow = await startLogin();
      setCode(flow.userCode);
      await Clipboard.setStringAsync(flow.userCode);
      setNote('The code is copied. Paste it on the GitHub page, tap Continue, then Authorize. Come back here after.');
      await Linking.openURL(flow.uri);
      const token = await waitForLogin(flow, () => false);
      const login = await whoAmI(token);
      await onSignedIn(login, token);
      setNote('');
    } catch (e) {
      setNote(e instanceof Error ? e.message : "The sign-in didn't finish. Try again.");
    } finally {
      setCode('');
      busy.current = false;
    }
  };

  return (
    <>
      <Pressable style={({ pressed }) => [st.gh, pressed && { opacity: 0.85 }]} onPress={go} disabled={!!code || !!signedInAs}>
        <Text style={st.ghText}>{signedInAs ? `✓ Signed in as ${signedInAs}` : '🔑  Sign in with GitHub'}</Text>
      </Pressable>
      {code ? <Text selectable style={st.code}>{code}</Text> : null}
      {note ? <Text style={st.hint}>{note}</Text> : null}
    </>
  );
}

const st = StyleSheet.create({
  gh: { backgroundColor: '#24292f', borderRadius: 14, paddingVertical: 14, marginTop: 12, alignItems: 'center',
        borderWidth: 1, borderColor: 'rgba(255,255,255,0.15)' },
  ghText: { color: '#fff', fontSize: 16, fontWeight: '800' },
  code: { color: C.pink, fontSize: 30, fontWeight: '900', letterSpacing: 4, textAlign: 'center', marginTop: 12 },
  hint: { color: C.muted, fontSize: 12, marginTop: 8, lineHeight: 17 },
});
