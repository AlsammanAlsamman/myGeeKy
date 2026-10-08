import { router } from 'expo-router';
import { Text, View } from 'react-native';
import { Card, Empty, open, PersonRow, s, Screen, Section, timeAgo } from '../../components/ui';
import { useApp, useFeed } from '../../lib/app-state';
import { Event, fetchLive } from '../../lib/live';
import { C } from '../../lib/theme';

function EventRow({ e }: { e: Event }) {
  return (
    <PersonRow login={e.actor} avatar={e.avatar} right={timeAgo(e.at)}
               line={`${e.icon} ${e.verb}${e.repo ? ` · ${e.repo}` : ''}`} />
  );
}

export default function Live() {
  const { settings, token } = useApp();
  const user = settings?.username ?? '';
  const feed = useFeed('live', 0.25, () => fetchLive(user, token));
  const events = feed.data?.events ?? [];
  return (
    <Screen title="Live" loading={feed.loading} onRefresh={feed.refresh} updated={feed.at} error={feed.error}
            subtitle={feed.data ? `What the ${feed.data.following} people you follow are doing on GitHub.`
                                : 'What the people you follow are doing on GitHub.'}>
      {!token ? (
        <Card onPress={() => router.navigate({ pathname: '/you', params: { part: 'more' } })}>
          <Text style={[s.small, { color: C.cyan, marginTop: 0 }]}>
            Tip: sign in with GitHub (You → More) so Live can refresh as often as you like.
          </Text>
        </Card>
      ) : null}
      {events.length ? <Section>LATEST</Section> : null}
      {events.map((e) => <EventRow key={e.id} e={e} />)}
      {feed.data && !events.length ? <Empty>Nothing new from the people you follow. Find people on the People tab.</Empty> : null}
      {!feed.data && !feed.loading ? <Empty>Pull down to load.</Empty> : null}
      {events.length ? (
        <View style={{ marginTop: 10 }}>
          <Text style={[s.small, { color: C.cyan }]} onPress={() => open(`https://github.com/${user}`)}>
            Your GitHub profile ↗
          </Text>
        </View>
      ) : null}
    </Screen>
  );
}
