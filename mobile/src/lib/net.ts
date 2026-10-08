// fetch with a time limit. A phone's network can stall a request forever (a
// captive portal, a blocked host); without a limit one stalled call left whole
// screens empty with no error.
export async function fetchT(url: string, init: RequestInit = {}, ms = 20000): Promise<Response> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  try {
    return await fetch(url, { ...init, signal: ctl.signal });
  } catch {
    if (ctl.signal.aborted) throw new Error(`${new URL(url).hostname} didn't answer in ${ms / 1000} s. Check your connection.`);
    throw new Error(`Couldn't reach ${new URL(url).hostname}. Check your connection.`);
  } finally {
    clearTimeout(timer);
  }
}
