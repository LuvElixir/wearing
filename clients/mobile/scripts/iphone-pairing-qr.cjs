// Render locally. The pairing URL contains a short-lived credential; never log it
// or send it to an external QR service.
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {pairingLink} = require('./pairing-link.cjs');
const cli = path.dirname(require.resolve('expo/node_modules/@expo/cli/package.json'));
const {toQR} = require(require.resolve('toqr', {paths: [cli]}));
const [pairingFile, output, metro] = process.argv.slice(2);
if (!pairingFile || !output || !metro) throw new Error('Usage: node scripts/iphone-pairing-qr.cjs <private pairing file> <output.pbm> <exp://LAN:8081>');
// iOS Expo Go 57 requires the same Expo account on the phone and the CLI.
// A healthy Metro endpoint alone does not prove that a phone can launch it.
const login = spawnSync(process.execPath, [require.resolve('expo/bin/cli'), 'whoami'], {encoding: 'utf8', timeout: 20000});
if (login.error || login.status !== 0 || !login.stdout.trim() || /not logged in/i.test(login.stdout)) {
  throw new Error('Sign in first: ./node_modules/.bin/expo login --browser. Use the same free Expo account on the iPhone.');
}
const pair = JSON.parse(fs.readFileSync(pairingFile, 'utf8'));
const data = toQR(pairingLink(pair, metro)), size = Math.sqrt(data.byteLength);
const margin = 4, width = size + margin * 2;
const rows = Array.from({length: width}, (_, y) => Array.from({length: width}, (_, x) =>
  x >= margin && x < size + margin && y >= margin && y < size + margin
    ? data[(y-margin)*size+x-margin] : 0).join(' '));
fs.writeFileSync(output, `P1\n${width} ${width}\n${rows.join('\n')}\n`, {mode: 0o600});
console.log('Local pairing QR saved. Expires: ' + pair.expiresAt);
