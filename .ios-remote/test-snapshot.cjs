const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const { spawnSync } = require('node:child_process');
const { createSnapshot, gatherFiles } = require('./create-snapshot.cjs');
const python = process.platform === 'win32' ? path.resolve(__dirname, '../backend/.venv/Scripts/python.exe') : 'python3';
const verifier = path.join(__dirname, 'verify-snapshot.py');
function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'trotter-snapshot-test-'));
  const write = (name, content) => { const file = path.join(root, name); fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, content); };
  write('mobile-v2/package-lock.json', '{"lockfileVersion":3}'); write('mobile-v2/app.json', '{"expo":{"name":"Trotter"}}');
  write('mobile-v2/package.json', '{"name":"trotter"}'); write('mobile-v2/src/a.ts', 'export const value = 1;');
  write('mobile-v2/assets/icon.png', 'image-fixture'); write('mobile-v2/native-ios/Share.swift', 'import Foundation');
  write('mobile-v2/plugins/share.js', 'module.exports = x => x;');
  return { root, write, out: path.join(root, '.ios-remote/artifacts'), cleanup() {
    assert.equal(path.dirname(root), fs.realpathSync(os.tmpdir())); assert(path.basename(root).startsWith('trotter-snapshot-test-'));
    fs.rmSync(root, { recursive: true, force: true });
  } };
}
test('snapshot includes uncommitted native sources but excludes credentials, generated trees and caches', () => {
  const f = fixture(); try {
    for (const name of ['.env', '.env.production', 'credentials.json', 'android/secrets.properties', 'ios/Info.plist', 'node_modules/example/index.js',
      'src/.env', 'assets/AuthKey_ABC.p8', 'src/key.pem', 'scripts/build/run.log', 'assets/photo-candidates/large.jpg']) f.write(`mobile-v2/${name}`, 'excluded-secret');
    const files = gatherFiles(f.root);
    assert(files.includes('mobile-v2/native-ios/Share.swift')); assert(files.includes('mobile-v2/src/a.ts'));
    assert.equal(files.length, 7); assert(!files.some(name => name.includes('node_modules') || name.includes('android')));
  } finally { f.cleanup(); }
});
test('content identity is stable and changes with source bytes', () => {
  const f = fixture(); try {
    const first = createSnapshot({ repoRoot: f.root, outDir: f.out });
    const second = createSnapshot({ repoRoot: f.root, outDir: f.out }); assert.equal(first.contentId, second.contentId);
    f.write('mobile-v2/src/a.ts', 'export const value = 2;');
    const third = createSnapshot({ repoRoot: f.root, outDir: f.out }); assert.notEqual(first.contentId, third.contentId);
    assert.match(third.archiveSha256, /^[a-f0-9]{64}$/);
  } finally { f.cleanup(); }
});
test('Mac verifier materializes only the exact manifest and refuses an existing destination', () => {
  const f = fixture(); try {
    const snap = createSnapshot({ repoRoot: f.root, outDir: f.out }), destination = path.join(f.root, 'verified');
    const result = spawnSync(python, [verifier, snap.archivePath, destination, snap.contentId], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr); assert.equal(fs.readFileSync(path.join(destination, 'mobile-v2/src/a.ts'), 'utf8'), 'export const value = 1;');
    const again = spawnSync(python, [verifier, snap.archivePath, destination, snap.contentId], { encoding: 'utf8' });
    assert.notEqual(again.status, 0); assert.match(again.stderr, /already exists/);
  } finally { f.cleanup(); }
});
test('snapshot verifier rejects wrong manifest identity before producing any source directory', () => {
  const f = fixture(); try {
    const snap = createSnapshot({ repoRoot: f.root, outDir: f.out }), destination = path.join(f.root, 'rejected');
    const result = spawnSync(python, [verifier, snap.archivePath, destination, '0'.repeat(64)], { encoding: 'utf8' });
    assert.notEqual(result.status, 0); assert(!fs.existsSync(destination));
  } finally { f.cleanup(); }
});
test('snapshot verifier rejects linked and traversing archive entries', () => {
  const f = fixture(); try {
    for (const kind of ['traversal', 'symlink']) {
      const archive = path.join(f.root, `${kind}.tar.gz`), destination = path.join(f.root, kind);
      const source = "import io,tarfile,sys\nwith tarfile.open(sys.argv[1],'w:gz') as t:\n m=tarfile.TarInfo('../escape' if sys.argv[2]=='traversal' else 'mobile-v2/link')\n if sys.argv[2]=='symlink': m.type=tarfile.SYMTYPE; m.linkname='/etc/passwd'\n t.addfile(m)\n";
      assert.equal(spawnSync(python, ['-c', source, archive, kind]).status, 0);
      assert.notEqual(spawnSync(python, [verifier, archive, destination, '0'.repeat(64)]).status, 0);
      assert(!fs.existsSync(destination));
    }
  } finally { f.cleanup(); }
});

test('snapshot verifier rejects Mac filename aliases before extraction', () => {
  const f = fixture(); try {
    const archive = path.join(f.root, 'aliases.tar.gz'), destination = path.join(f.root, 'aliases');
    const source = "import tarfile,sys\nwith tarfile.open(sys.argv[1],'w:gz') as t:\n for name in ['mobile-v2/src/A.ts','mobile-v2/src/a.ts']: t.addfile(tarfile.TarInfo(name))\n";
    assert.equal(spawnSync(python, ['-c', source, archive]).status, 0);
    const result = spawnSync(python, [verifier, archive, destination, '0'.repeat(64)], { encoding: 'utf8' });
    assert.notEqual(result.status, 0); assert.match(result.stderr, /Conflicting names/); assert(!fs.existsSync(destination));
  } finally { f.cleanup(); }
});
