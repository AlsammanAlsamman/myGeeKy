// Small building blocks shared by the screens, in myGeeKy's style.
import { ReactNode } from 'react';
import { Linking, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { timeAgo } from '../lib/app-state';
import { BADGES, C } from '../lib/theme';

export function Screen({ title, subtitle, loading, onRefresh, updated, error, children }: {
  title: string; subtitle?: string; loading?: boolean; onRefresh?: () => void; updated?: string | null;
  error?: string | null; children: ReactNode;
}) {
  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <ScrollView
        contentContainerStyle={s.scroll}
        refreshControl={onRefresh ? <RefreshControl refreshing={!!loading} onRefresh={onRefresh} tintColor={C.pink} colors={[C.pink]} /> : undefined}
      >
        <Text style={s.title}>{title}</Text>
        {subtitle ? <Text style={s.subtitle}>{subtitle}</Text> : null}
        {updated || loading ? <Text style={s.meta}>{loading ? 'updating…' : `updated ${timeAgo(updated)} · pull down to refresh`}</Text> : null}
        {error ? <Text style={s.error}>{error}</Text> : null}
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

export function Section({ children }: { children: ReactNode }) {
  return <Text style={s.section}>{children}</Text>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <Text style={s.empty}>{children}</Text>;
}

export function Badge({ letter }: { letter: string }) {
  const b = BADGES[letter];
  return (
    <View style={[s.badge, { backgroundColor: b.color }]} accessibilityLabel={b.label}>
      <Text style={[s.badgeText, { color: b.text }]}>{letter}</Text>
    </View>
  );
}

export function Card({ onPress, children, style }: { onPress?: () => void; children: ReactNode; style?: object }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [s.card, pressed && s.cardPressed, style]}>
      {children}
    </Pressable>
  );
}

/** Opens in the phone's browser -- only https links ever reach here. */
export function open(url: string) {
  if (url.startsWith('https://')) Linking.openURL(url);
}

export const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: C.bg },
  scroll: { padding: 16, paddingBottom: 40 },
  title: { color: C.text, fontSize: 26, fontWeight: '800', letterSpacing: -0.4 },
  subtitle: { color: C.muted, fontSize: 14, marginTop: 4, lineHeight: 20 },
  meta: { color: C.muted, fontSize: 12, marginTop: 8 },
  error: { color: C.red, fontSize: 13, marginTop: 8 },
  section: { color: C.text, fontSize: 12, fontWeight: '800', letterSpacing: 0.8, marginTop: 20, marginBottom: 8 },
  empty: { color: C.muted, fontSize: 14, marginTop: 8, lineHeight: 20 },
  card: { backgroundColor: C.card, borderRadius: 14, padding: 12, marginBottom: 8, borderWidth: 1, borderColor: C.line },
  cardPressed: { backgroundColor: C.cardHi },
  badge: { width: 20, height: 20, borderRadius: 5, alignItems: 'center', justifyContent: 'center' },
  badgeText: { fontSize: 11, fontWeight: '900' },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  itemTitle: { color: C.text, fontSize: 15, lineHeight: 21, flex: 1 },
  small: { color: C.muted, fontSize: 12, marginTop: 4 },
});
