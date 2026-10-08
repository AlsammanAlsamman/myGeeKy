// "Connect your phone": the desktop panel shows a QR code that carries your
// profile (and, only if it's strictly read-only, your GitHub token), so the
// phone needs no typing at all. The format is `mygeeky:1:<base64url JSON>`:
//   { u: username, o: ORCID, k: [keywords], t: [topics], tok?: read-only token }
// A QR code is untrusted input: every field is checked before anything is saved.
import type { Settings } from './storage';

export const PREFIX = 'mygeeky:1:';
const LOGIN = /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$/;
const ORCID = /^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$/;
const TOKEN = /^(github_pat_[A-Za-z0-9_]{20,255}|gh[opu]_[A-Za-z0-9]{20,255})$/;

export type Pairing = { settings: Settings; token: string | null };

function fromBase64Url(s: string): string {
  const b64 = s.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((s.length + 3) % 4);
  return atob(b64);
}

const words = (v: unknown, n = 40): string[] =>
  (Array.isArray(v) ? v : [])
    .filter((x): x is string => typeof x === 'string')
    .map((x) => x.trim().slice(0, 40))
    .filter(Boolean)
    .slice(0, n);

/** The profile in a pairing QR code, or an error message saying what's wrong. */
export function parsePairing(data: string): Pairing | { error: string } {
  if (typeof data !== 'string' || !data.startsWith(PREFIX)) {
    return { error: "That's not a myGeeKy code. On your computer: ⚙ → Connect your phone." };
  }
  let raw: Record<string, unknown>;
  try {
    raw = JSON.parse(fromBase64Url(data.slice(PREFIX.length)));
  } catch {
    return { error: "That code couldn't be read. Try scanning it again." };
  }
  const u = typeof raw.u === 'string' ? raw.u : '';
  if (!LOGIN.test(u)) return { error: "That code doesn't contain a GitHub username." };
  const o = typeof raw.o === 'string' && ORCID.test(raw.o) ? raw.o : '';
  const tok = typeof raw.tok === 'string' && TOKEN.test(raw.tok) ? raw.tok : null;
  return { settings: { exploreShare: 0.2, username: u, orcid: o, keywords: words(raw.k), topics: words(raw.t) }, token: tok };
}
