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
        tabBarStyle: { backgroundColor: '#17172a', borderTopColor: C.line },
        sceneStyle: { backgroundColor: C.bg },
      }}
    >
      <Tabs.Screen name="headlines" options={{ title: 'Headlines', tabBarIcon: icon('newspaper-outline') }} />
      <Tabs.Screen name="research" options={{ title: 'Research', tabBarIcon: icon('flask-outline') }} />
      <Tabs.Screen name="models" options={{ title: 'Models', tabBarIcon: icon('sparkles-outline') }} />
      <Tabs.Screen name="settings" options={{ title: 'You', tabBarIcon: icon('person-circle-outline') }} />
    </Tabs>
  );
}
