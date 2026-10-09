/** Expo Go's URL extraction decodes query values before parsing them again.
 * A numeric UTC offset's + becomes a space in that second pass. Emit the
 * interoperable UTC millisecond form, with no + and no microsecond extension.
 * Keep credentials unchanged and never return them to logs.
 */
function pairingLink(pair, metro, now = Date.now()) {
  if (typeof pair.expiresAt !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(pair.expiresAt)) throw new Error('Invalid pairing expiry.');
  const expiry = Date.parse(pair.expiresAt);
  if (!Number.isFinite(expiry) || expiry <= now) throw new Error('Pairing has expired or has an invalid expiry.');
  if (typeof pair.accessToken !== 'string' || !/^[A-Za-z0-9_-]{32,512}$/.test(pair.accessToken) || typeof pair.identity !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(pair.identity)) throw new Error('Invalid pairing credentials.');
  const base = new URL(metro), endpoint = new URL(pair.endpoint);
  if (base.protocol !== 'exp:' || base.username || base.password || base.search || base.hash || base.hostname !== endpoint.hostname) throw new Error('Metro must be on the paired Mac.');
  base.pathname = '/--/connect';
  for (const key of ['endpoint', 'identity', 'accessToken']) base.searchParams.set(key, pair[key]);
  base.searchParams.set('expiresAt', new Date(expiry).toISOString());
  return base.toString();
}
module.exports = {pairingLink};
