import { CameraView, useCameraPermissions } from 'expo-camera';
import { router } from 'expo-router';
import { useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useApp } from '../lib/app-state';
import { parsePairing } from '../lib/pairing';
import { C } from '../lib/theme';

// Scan the QR code from myGeeKy on your computer (⚙ → Connect your phone).
export default function Scan() {
  const { save } = useApp();
  const [permission, requestPermission] = useCameraPermissions();
  const [message, setMessage] = useState('');
  const busy = useRef(false);

  const onScan = async ({ data }: { data: string }) => {
    if (busy.current) return;
    busy.current = true;
    const result = parsePairing(data);
    if ('error' in result) {
      setMessage(result.error);
      setTimeout(() => (busy.current = false), 1500);
      return;
    }
    setMessage(`Connected as @${result.settings.username}…`);
    await save(result.settings, result.token ?? undefined);
    router.replace('/home');
  };

  if (!permission) return <View style={st.safe} />;
  if (!permission.granted) {
    return (
      <SafeAreaView style={[st.safe, st.center]}>
        <Text style={st.title}>Scan from your computer</Text>
        <Text style={st.body}>myGeeKy needs the camera only to read the QR code from myGeeKy on your computer.</Text>
        <Pressable style={st.button} onPress={requestPermission}>
          <Text style={st.buttonText}>Allow the camera</Text>
        </Pressable>
        <Pressable onPress={() => router.back()}><Text style={st.link}>Back</Text></Pressable>
      </SafeAreaView>
    );
  }
  return (
    <View style={st.safe}>
      <CameraView style={StyleSheet.absoluteFill} facing="back" barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
                  onBarcodeScanned={onScan} />
      <SafeAreaView style={st.overlay} pointerEvents="box-none">
        <Text style={st.title}>Scan from your computer</Text>
        <Text style={st.body}>On your computer, open myGeeKy: ⚙ → <Text style={{ fontWeight: '800' }}>Connect your phone</Text>.
          Point this camera at the QR code.</Text>
        <View style={st.frame} />
        {message ? <Text style={st.message}>{message}</Text> : null}
        <Pressable onPress={() => router.back()}><Text style={st.link}>Back</Text></Pressable>
      </SafeAreaView>
    </View>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#000' },
  center: { alignItems: 'center', justifyContent: 'center', padding: 24, backgroundColor: C.bg },
  overlay: { flex: 1, alignItems: 'center', padding: 20, backgroundColor: 'rgba(0,0,0,0.25)' },
  title: { color: '#fff', fontSize: 22, fontWeight: '800', marginTop: 12, textAlign: 'center' },
  body: { color: 'rgba(255,255,255,0.85)', fontSize: 14, textAlign: 'center', marginTop: 8, lineHeight: 20 },
  frame: { width: 250, height: 250, marginTop: 36, borderWidth: 3, borderColor: C.pink, borderRadius: 24 },
  message: { color: '#fff', backgroundColor: 'rgba(0,0,0,0.6)', padding: 10, borderRadius: 10, marginTop: 20, textAlign: 'center' },
  button: { backgroundColor: C.violet, borderRadius: 14, paddingVertical: 14, paddingHorizontal: 22, marginTop: 22 },
  buttonText: { color: '#fff', fontWeight: '800', fontSize: 16 },
  link: { color: C.cyan, fontSize: 15, marginTop: 22, padding: 8 },
});
