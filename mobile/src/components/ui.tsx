// Small building blocks shared by the screens, in myGeeKy's style.
import { ReactNode } from 'react';
import { Image, Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import { timeAgo } from '../lib/app-state';
import { logClick } from '../lib/badges';
import { BADGES, C } from '../lib/theme';

/** A small switch between the parts of a tab (e.g. Headlines | Papers). */
export function Segments<T extends string>({ value, options, onChange }: {
  value: T; options: [T, string][]; onChange: (v: T) => void;
}) {
  return (
    <View style={s.segments}>
      {options.map(([v, label]) => (
        <Pressable key={v} onPress={() => onChange(v)} style={[s.segment, v === value && s.segmentOn]}>
          <Text style={[s.segmentText, v === value && s.segmentTextOn]} numberOfLines={1}>{label}</Text>
        </Pressable>
      ))}
    </View>
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

/** One person: avatar, name, why they're here; opens their GitHub profile. */
export function PersonRow({ login, avatar, line, right }: { login: string; avatar: string; line: string; right?: string }) {
  return (
    <Card onPress={() => open(`https://github.com/${login}`, 'person')}>
      <View style={[s.row, { alignItems: 'center' }]}>
        <Image source={{ uri: `${avatar}${avatar.includes('?') ? '&' : '?'}s=88` }} style={s.avatar} />
        <View style={{ flex: 1 }}>
          <Text style={s.name} numberOfLines={1}>{login}</Text>
          <Text style={s.small} numberOfLines={2}>{line}</Text>
        </View>
        {right ? <Text style={s.small}>{right}</Text> : null}
      </View>
    </Card>
  );
}

/** Opens in the phone's browser -- only https links ever reach here. `kind`
 *  (headline, paper, model…) counts toward your badges; nothing else is kept. */
export function open(url: string, kind?: string, cat?: string, explore?: boolean) {
  if (!url.startsWith('https://')) return;
  if (kind) logClick(kind, cat, explore);
  Linking.openURL(url);
}

export { timeAgo };

export const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: C.bg },
  header: { flexDirection: 'row', alignItems: 'center', gap: 10, paddingHorizontal: 16, paddingTop: 8, paddingBottom: 10 },
  logo: { width: 30, height: 30, borderRadius: 8 },
  title: { color: C.text, fontSize: 24, fontWeight: '800', letterSpacing: -0.4, flex: 1 },
  strip: { flexDirection: 'row', gap: 4 },
  stripIcon: { width: 26, height: 26, borderRadius: 13, borderWidth: 2, alignItems: 'center', justifyContent: 'center',
               backgroundColor: 'rgba(255,255,255,0.06)' },
  segments: { flexDirection: 'row', marginHorizontal: 16, marginBottom: 6, padding: 3, borderRadius: 12,
              backgroundColor: C.card, borderWidth: 1, borderColor: C.line },
  segment: { flex: 1, paddingVertical: 8, borderRadius: 9, alignItems: 'center' },
  segmentOn: { backgroundColor: C.violet },
  segmentText: { color: C.muted, fontSize: 13, fontWeight: '700' },
  segmentTextOn: { color: '#fff' },
  scroll: { paddingHorizontal: 16, paddingTop: 4, paddingBottom: 40 },
  subtitle: { color: C.muted, fontSize: 13, lineHeight: 19 },
  meta: { color: C.muted, fontSize: 12, marginTop: 6 },
  error: { color: C.red, fontSize: 13, marginTop: 8 },
  section: { color: C.text, fontSize: 12, fontWeight: '800', letterSpacing: 0.8, marginTop: 18, marginBottom: 8 },
  empty: { color: C.muted, fontSize: 14, marginTop: 8, lineHeight: 20 },
  card: { backgroundColor: C.card, borderRadius: 14, padding: 12, marginBottom: 8, borderWidth: 1, borderColor: C.line },
  cardPressed: { backgroundColor: C.cardHi },
  badge: { width: 20, height: 20, borderRadius: 5, alignItems: 'center', justifyContent: 'center' },
  badgeText: { fontSize: 11, fontWeight: '900' },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  itemTitle: { color: C.text, fontSize: 15, lineHeight: 21, flex: 1 },
  name: { color: C.text, fontSize: 15, fontWeight: '800' },
  avatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: C.cardHi },
  small: { color: C.muted, fontSize: 12, marginTop: 3 },
});
