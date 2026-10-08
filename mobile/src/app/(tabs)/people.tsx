import { useState } from 'react';
import { Empty, PersonRow, Screen, Segments } from '../../components/ui';
import { useApp, useFeed } from '../../lib/app-state';
import { fetchPeople } from '../../lib/people';

type Part = 'field' | 'followBack';
const PARTS: [Part, string][] = [['field', 'In your field'], ['followBack', 'Follow you']];

// Suggestions only: tapping opens their GitHub profile; myGeeKy never follows anyone.
export default function People() {
  const { settings, token } = useApp();
  const [part, setPart] = useState<Part>('field');
  const feed = useFeed('people', 12, (p) => fetchPeople(settings?.username ?? '', token, p.weights));
  const list = feed.data?.[part] ?? [];
  return (
    <Screen title="People" top={<Segments value={part} options={PARTS} onChange={setPart} />}
            loading={feed.loading} onRefresh={feed.refresh} updated={feed.at} error={feed.error}
            subtitle={part === 'field' ? 'People building the tools of your field. Tap to see their profile.'
                                       : "People who follow you that you don't follow back yet."}>
      {list.map((p) => <PersonRow key={p.login} login={p.login} avatar={p.avatar} line={p.why} />)}
      {feed.data && !list.length ? (
        <Empty>{part === 'field' ? 'No one found for your keywords yet: add a few on the You tab.' : "You follow everyone who follows you. 👏"}</Empty>
      ) : null}
      {!feed.data && !feed.loading ? <Empty>Pull down to load.</Empty> : null}
    </Screen>
  );
}
