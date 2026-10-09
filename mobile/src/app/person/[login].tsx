// Someone at a glance on their own screen (for links); in lists it unfolds in place.
import Ionicons from '@expo/vector-icons/Ionicons';
import { router, useLocalSearchParams } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { PersonCard } from '../../components/person-card';
import { C } from '../../lib/theme';

export default function Person() {
  const { login } = useLocalSearchParams<{ login: string }>();
  return (
    <SafeAreaView style={st.safe} edges={['top', 'bottom']}>
      <View style={st.top}>
        <Pressable onPress={() => router.back()} style={st.back} accessibilityLabel="Back">
          <Ionicons name="chevron-back" size={22} color={C.text} />
        </Pressable>
        <Text style={st.title} numberOfLines={1}>@{login}</Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: 16 }}>
        <PersonCard login={String(login)} />
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: C.bg },
  top: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 8, paddingVertical: 6 },
  back: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  title: { color: C.muted, fontSize: 15, fontWeight: '700', flex: 1 },
});
