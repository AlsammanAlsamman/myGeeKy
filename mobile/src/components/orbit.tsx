// The orbit: you in the middle, your circle on the inner ring, the world on the
// outer one. Spin a ring with your finger; when you let go, the planet nearest
// the lens (the top of the ring) locks in with a small click. Tapping a planet
// spins it to the lens too.
import Ionicons from '@expo/vector-icons/Ionicons';
import * as Haptics from 'expo-haptics';
import { useEffect, useRef, useState } from 'react';
import { GestureResponderEvent, Platform, StyleSheet, Text, View } from 'react-native';
import { INNER, OUTER, SECTIONS, SectionId } from '../lib/sections';
import { C } from '../lib/theme';

type Ring = 'inner' | 'outer';
const TAU = Math.PI * 2;
const IDS: Record<Ring, SectionId[]> = { inner: INNER, outer: OUTER };

/** The rotation that brings planet i to the lens, the shortest way round from `cur`. */
function targetRot(ring: Ring, i: number, cur: number) {
  const n = IDS[ring].length;
  const want = (-i * TAU) / n;
  return want + Math.round((cur - want) / TAU) * TAU;
}

function nearest(ring: Ring, rot: number) {
  const n = IDS[ring].length;
  return ((Math.round(-rot / (TAU / n)) % n) + n) % n;
}

export function orbitHeight(width: number) {
  return Math.round(410 * (width / 390));
}

export function Orbit({ width, sel, counts, onSelect, hint, onTouched, youLetter }: {
  width: number; sel: SectionId; counts: Partial<Record<SectionId, number>>;
  onSelect: (id: SectionId) => void; hint: boolean; onTouched: () => void; youLetter: string;
}) {
  const k = width / 390;
  const geo = { cx: 195 * k, cy: 210 * k, r: { inner: 88 * k, outer: 160 * k }, size: { inner: 46 * k, outer: 56 * k }, split: 125 * k, center: 40 * k };
  const [rot, setRot] = useState<Record<Ring, number>>({ inner: 0, outer: 0 });

  // latest values for the touch handlers (they're created once)
  const live = useRef({ rot, geo, onSelect, onTouched });
  useEffect(() => {
    live.current = { rot, geo, onSelect, onTouched };
  });
  const drag = useRef<{ ring: Ring | 'center'; a0: number; rot0: number; x0: number; y0: number; moved: number; ox: number; oy: number } | null>(null);
  const anim = useRef<number | null>(null);

  const turn = (ring: Ring, to: number, ms: number, done?: () => void) => {
    if (anim.current) cancelAnimationFrame(anim.current);
    const from = live.current.rot[ring];
    const t0 = Date.now();
    const step = () => {
      const p = Math.min((Date.now() - t0) / ms, 1);
      const e = 1 - Math.pow(1 - p, 3);
      setRot((r) => ({ ...r, [ring]: from + (to - from) * e }));
      if (p < 1) anim.current = requestAnimationFrame(step);
      else {
        anim.current = null;
        done?.();
      }
    };
    anim.current = requestAnimationFrame(step);
  };
  const turnRef = useRef(turn);
  useEffect(() => {
    turnRef.current = turn;
  });

  const lock = (ring: Ring, i: number) => {
    const { rot: r, onSelect: pick } = live.current;
    pick(IDS[ring][i]);
    turnRef.current(ring, targetRot(ring, i, r[ring]), 320, () => {
      if (Platform.OS !== 'web') Haptics.selectionAsync().catch(() => undefined);
    });
  };
  const lockRef = useRef(lock);
  useEffect(() => {
    lockRef.current = lock;
  });

  // first launch: the outer ring turns a little by itself, so it reads as a dial
  useEffect(() => {
    if (!hint) return;
    const t = setTimeout(() => turnRef.current('outer', 0.55, 520, () => turnRef.current('outer', 0, 620)), 700);
    return () => clearTimeout(t);
  }, [hint]);

  // touch handling: plain responder props (event handlers, so the refs are fine)
  const where = (e: GestureResponderEvent) => {
    const g = drag.current!;
    return { x: e.nativeEvent.pageX - g.ox, y: e.nativeEvent.pageY - g.oy };
  };
  const touch = {
    onStartShouldSetResponder: () => true,
    onMoveShouldSetResponder: () => true,
    onResponderTerminationRequest: () => false,
    onResponderGrant: (e: GestureResponderEvent) => {
      const { geo: G, rot: r } = live.current;
      const { locationX: x, locationY: y, pageX, pageY } = e.nativeEvent;
      const dist = Math.hypot(x - G.cx, y - G.cy);
      const ring = dist < G.center ? 'center' : dist < G.split ? 'inner' : 'outer';
      drag.current = { ring, a0: Math.atan2(y - G.cy, x - G.cx), rot0: ring === 'center' ? 0 : r[ring],
                       x0: x, y0: y, moved: 0, ox: pageX - x, oy: pageY - y };
      live.current.onTouched();
    },
    onResponderMove: (e: GestureResponderEvent) => {
      const g = drag.current;
      if (!g || g.ring === 'center') return;
      const { geo: G } = live.current;
      const p = where(e);
      g.moved = Math.max(g.moved, Math.hypot(p.x - g.x0, p.y - g.y0));
      let da = Math.atan2(p.y - G.cy, p.x - G.cx) - g.a0;
      if (da > Math.PI) da -= TAU;
      if (da < -Math.PI) da += TAU;
      const ring = g.ring;
      if (anim.current) cancelAnimationFrame(anim.current);
      setRot((r) => ({ ...r, [ring]: g.rot0 + da }));
    },
    onResponderRelease: () => {
      const g = drag.current;
      drag.current = null;
      if (!g) return;
      const { geo: G, rot: r } = live.current;
      if (g.ring === 'center') {
        if (g.moved < 8) live.current.onSelect('you');
        return;
      }
      const n = IDS[g.ring].length;
      let i: number;
      if (g.moved < 8) {                                   // a tap: the planet under the finger
        const a = Math.atan2(g.y0 - G.cy, g.x0 - G.cx) + Math.PI / 2 - r[g.ring];
        i = ((Math.round(a / (TAU / n)) % n) + n) % n;
      } else {
        i = nearest(g.ring, r[g.ring]);                    // a spin: whichever is nearest the lens
      }
      lockRef.current(g.ring, i);
    },
  };

  const selRing = INNER.includes(sel) ? 'inner' : OUTER.includes(sel) ? 'outer' : null;
  const planets = (['outer', 'inner'] as Ring[]).flatMap((ring) => IDS[ring].map((id, i) => {
    const n = IDS[ring].length;
    const th = rot[ring] + (i * TAU) / n - Math.PI / 2;
    const s = SECTIONS[id];
    const count = counts[id] ?? 0;
    const on = sel === id;
    const d = Math.round(Math.max(44, geo.size[ring] * (0.86 + 0.04 * Math.min(count, 6)) * (on ? 1.08 : 1)));
    // labels sit below each planet, except an outer planet near the top: there,
    // below would land on your circle, so it goes above
    const nearTop = ring === 'outer' && Math.cos(th + Math.PI / 2) > Math.cos(Math.PI / 6);
    return { id, ring, i, s, count, on, d, nearTop, x: geo.cx + geo.r[ring] * Math.cos(th), y: geo.cy + geo.r[ring] * Math.sin(th) };
  }));
  const youOn = sel === 'you';

  return (
    <View style={{ width, height: orbitHeight(width) }} {...touch}>
      <View pointerEvents="none" style={[st.ring, { left: geo.cx - geo.r.outer, top: geo.cy - geo.r.outer, width: geo.r.outer * 2, height: geo.r.outer * 2, borderRadius: geo.r.outer }]} />
      <View pointerEvents="none" style={[st.ring, st.dashed, { left: geo.cx - geo.r.inner, top: geo.cy - geo.r.inner, width: geo.r.inner * 2, height: geo.r.inner * 2, borderRadius: geo.r.inner }]} />
      {selRing ? (
        <View pointerEvents="none" style={[st.lens, selRing === 'outer'
          ? { left: geo.cx - 28 * k, top: geo.cy - geo.r.outer - 44 * k, width: 56 * k }
          : { left: geo.cx - 24 * k, top: geo.cy - geo.r.inner - 36 * k, width: 48 * k }, { backgroundColor: SECTIONS[sel].color }]} />
      ) : null}

      <View pointerEvents="none" accessible accessibilityRole="button" accessibilityLabel="You: your model, badges and settings"
            onAccessibilityTap={() => onSelect('you')}
            style={[st.center, { left: geo.cx - 38 * k, top: geo.cy - 38 * k, width: 76 * k, height: 76 * k, borderRadius: 38 * k,
                                 backgroundColor: youOn ? '#3a3320' : '#22223a' }, youOn && st.youGlow]}>
        <Text style={{ color: C.text, fontSize: 22 * k, fontWeight: '800' }}>{youLetter}</Text>
        <Text style={{ color: C.muted, fontSize: 9 * k, fontWeight: '800', letterSpacing: 0.8 }}>YOU</Text>
      </View>

      {planets.map((p) => (
        <View key={p.id} pointerEvents="none" accessible accessibilityRole="button"
              accessibilityLabel={`${p.s.label}, ${p.count} new, ${p.ring === 'inner' ? 'your circle' : 'the world'}`}
              onAccessibilityTap={() => lockRef.current(p.ring, p.i)}
              style={{ position: 'absolute', left: p.x - 40, top: p.y - p.d / 2 - (p.nearTop && !p.on ? 17 : 0), width: 80, alignItems: 'center' }}>
          {p.nearTop && !p.on ? <Text style={[st.label, { marginTop: 0, marginBottom: 3 }]} numberOfLines={1}>{p.s.label}</Text> : null}
          <View style={[st.planet, { width: p.d, height: p.d, borderRadius: p.d / 2, borderColor: p.s.color,
                                     backgroundColor: p.on ? p.s.color : '#1c1c2c' },
                        p.on && { shadowColor: p.s.color, shadowOpacity: 0.8, shadowRadius: 14, elevation: 10 }]}>
            <Ionicons name={p.s.icon} size={Math.round(p.d * 0.44)} color={p.on ? '#0d0d16' : p.s.color} />
            {p.count ? <View style={st.count}><Text style={st.countText}>{p.count > 99 ? '99+' : p.count}</Text></View> : null}
          </View>
          {!p.nearTop && !p.on ? <Text style={st.label} numberOfLines={1}>{p.s.label}</Text> : null}
        </View>
      ))}

      {hint ? (
        <View pointerEvents="none" style={[st.hint, { left: geo.cx - 100, top: orbitHeight(width) - 30 }]}>
          <Text style={st.hintText}>Spin a ring, or tap a planet</Text>
        </View>
      ) : null}
    </View>
  );
}

const st = StyleSheet.create({
  ring: { position: 'absolute', borderWidth: 1, borderColor: 'rgba(255,255,255,0.10)' },
  dashed: { borderStyle: 'dashed', borderColor: 'rgba(255,255,255,0.16)' },
  lens: { position: 'absolute', height: 8, borderRadius: 4 },
  center: { position: 'absolute', borderWidth: 2, borderColor: '#ffd24a', alignItems: 'center', justifyContent: 'center' },
  youGlow: { shadowColor: '#ffd24a', shadowOpacity: 0.6, shadowRadius: 16, elevation: 8 },
  planet: { borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  count: { position: 'absolute', top: -5, right: -7, minWidth: 18, height: 18, paddingHorizontal: 4, borderRadius: 9,
           backgroundColor: '#f0f0f5', alignItems: 'center', justifyContent: 'center' },
  countText: { color: '#0d0d16', fontSize: 10, fontWeight: '800' },
  label: { color: C.muted, fontSize: 11, fontWeight: '700', marginTop: 3 },
  hint: { position: 'absolute', width: 200, borderRadius: 999, backgroundColor: '#f0f0f5', paddingVertical: 6, alignItems: 'center' },
  hintText: { color: '#0d0d16', fontSize: 12, fontWeight: '700' },
});
