// Where the dashboard's schema comes from. Pure logic, no fetch: joist.js
// decides which way in applies and hands the result here.
//
// Two ways in, and Joist's own dashboard still uses the first:
//
//   - fetch the JSON endpoint, then readPayload() the response
//   - embed the payload in the page, then inlinePayload() it and readPayload()
//     the result, with no request at all
//
// The second is for a host rendering the diagram in a page of its own (an
// admin view, a custom template) with `django_joist.payload()` already in
// hand, which would otherwise make an HTTP request to its own site for data
// it is holding. Structure only: this reads what the server chose to send and
// never asks for more.

/**
 * The element a host embeds the payload in, inside the app container:
 *
 *   {{ payload|json_script:"joist-payload" }}
 *
 * Django's `json_script` filter is the contract rather than a bespoke
 * attribute because it already escapes `<`, `>` and `&`, so a table name or a
 * column default containing `</script>` cannot end the block early, and
 * `type="application/json"` is never executed, so it stays safe under a
 * strict CSP.
 */
export const EMBEDDED_PAYLOAD_SELECTOR = 'script#joist-payload[type="application/json"]';

/**
 * The API envelope as the dashboard's state slice.
 *
 * Deliberately tolerant. The envelope has grown optional keys over releases
 * (`diff`, `doctor`, `cache_unavailable`, `diff_unavailable`), and a payload
 * that predates one of them, or one a host built by hand, must degrade to a
 * working diagram rather than a crash in the loader: a blank diagram is a
 * state the dashboard renders, a thrown TypeError leaves the page on its
 * loading banner.
 *
 * @param {unknown} payload the parsed JSON envelope
 * @returns {{tables: object[], fallback: boolean, generatedAt: string|null, diff: object|null, doctor: object|null, cacheUnavailable: boolean, diffUnavailable: boolean}}
 */
export function readPayload(payload) {
  const envelope = isPlainObject(payload) ? payload : {};

  return {
    tables: Array.isArray(envelope.tables) ? envelope.tables : [],
    fallback: Boolean(envelope.fallback),
    generatedAt: envelope.generated_at ?? null,
    diff: envelope.diff ?? null,
    doctor: envelope.doctor ?? null,
    // Strictly true, never merely truthy: both flags report that something is
    // broken, so a stray "false" string in a hand-built payload must not tell
    // someone their cache store is down.
    cacheUnavailable: envelope.cache_unavailable === true,
    diffUnavailable: envelope.diff_unavailable === true,
  };
}

/**
 * The payload embedded in the page, if the host embedded one.
 *
 * @param {{querySelector: (selector: string) => {textContent: string}|null}|null|undefined} container the app element
 * @returns {object|null} the parsed payload, or null when the page embeds none
 * @throws {Error} when a payload is embedded but is not a JSON object
 */
export function inlinePayload(container) {
  const node = container?.querySelector(EMBEDDED_PAYLOAD_SELECTOR);
  if (!node) return null;

  let parsed;
  try {
    parsed = JSON.parse(node.textContent ?? '');
  } catch {
    parsed = undefined;
  }

  // Loud, on purpose. Falling back to a fetch would send a host that embedded
  // a payload to an endpoint it may not have mounted, and then report that
  // 404 instead of the authoring mistake that caused it.
  if (!isPlainObject(parsed)) {
    throw new Error('The embedded Joist payload could not be parsed as a JSON object.');
  }
  return parsed;
}

function isPlainObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
