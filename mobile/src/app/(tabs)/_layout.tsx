import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router';
import type { ColorValue } from 'react-native';
import { C } from '../../lib/theme';

type Icon = keyof typeof Ionicons.glyphMap;

function TabIcon({ name, color, size }: { name: Icon; color: ColorValue; size: number }) {
  return <Ionicons name={name} size={size} color={color as string} />;
}

const icon = (name: Icon) => {
  const Render = ({ color, size }: { color: ColorValue; size: number }) => <TabIcon name={name} color={color} size={size} />;
  Render.displayName = `TabIcon(${name})`;
  return Render;
};

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: C.pink,
        tabBarInactiveTintColor: C.muted,
        tabBarStyle: { backgroundColor: '#17172a', borderTopColor: C.line, height: 64, paddingTop: 6 },
        tabBarLabelStyle: { fontSize: 11, fontWeight: '700' },
        sceneStyle: { backgroundColor: C.bg },
      }}
    >
      <Tabs.Screen name="live" options={{ title: 'Live', tabBarIcon: icon('flash-outline') }} />
      <Tabs.Screen name="people" options={{ title: 'People', tabBarIcon: icon('people-outline') }} />
      <Tabs.Screen name="news" options={{ title: 'News', tabBarIcon: icon('newspaper-outline') }} />
      <Tabs.Screen name="market" options={{ title: 'Market', tabBarIcon: icon('trending-up-outline') }} />
      <Tabs.Screen name="you" options={{ title: 'You', tabBarIcon: icon('person-circle-outline') }} />
    </Tabs>
  );
}
