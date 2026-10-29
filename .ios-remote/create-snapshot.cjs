const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');

const FILES = ['package.json', 'package-lock.json', 'app.json', 'app.config.js', 'App.tsx',
  'babel.config.js', 'tsconfig.json', 'metro.config.js', 'eas.json'];
const DIRECTORIES = ['src', 'assets', 'plugins', 'native-ios', 'scripts'];
const blocked = name => /^(?:\.env(?:\..*)?|\.git|\.cache|node_modules|Pods|build|dist|\.expo|\.DS_Store|credentials(?:\..*)?)$/i.test(name)
  || /\.(?:p8|pem|p12|pfx|key|jks|keystore|mobileprovision|log|dump|sqlite3?)$/i.test(name);
const hash = data => crypto.createHash('sha256').update(data).digest('hex');

function gatherFiles(repoRoot) {
  const app = path.join(repoRoot, 'mobile-v2'), files = [];
  function visit(relative) {
    const parts = relative.split('/');
    if (parts.some(blocked) || relative === 'assets/photo-candidates' || relative.startsWith('assets/photo-candidates/')) return;
    const absolute = path.join(app, ...parts);
    const stat = fs.lstatSync(absolute);
    if (stat.isSymbolicLink()) throw new Error(`Snapshot refuses symlinks: mobile-v2/${relative}`);
    if (stat.isDirectory()) {
      for (const name of fs.readdirSync(absolute).sort()) visit(`${relative}/${name}`);
    } else if (stat.isFile()) {
      if (stat.size > 150 * 1024 * 1024) throw new Error(`Unexpectedly large source file: mobile-v2/${relative}`);
      files.push(`mobile-v2/${relative}`);
    } else throw new Error(`Snapshot refuses special files: mobile-v2/${relative}`);
  }
  for (const file of FILES) if (fs.existsSync(path.join(app, file))) visit(file);
  for (const folder of DIRECTORIES) if (fs.existsSync(path.join(app, folder))) visit(folder);
  if (!files.includes('mobile-v2/package-lock.json') || !files.includes('mobile-v2/app.json')) throw new Error('A locked Trotter app checkout is required.');
  return files.sort();
}

function createSnapshot({ repoRoot = path.resolve(__dirname, '..'), outDir = path.join(__dirname, 'artifacts', 'snapshots') } = {}) {
  repoRoot = fs.realpathSync(repoRoot); outDir = path.resolve(outDir);
  fs.mkdirSync(outDir, { recursive: true });
  const staging = fs.mkdtempSync(path.join(outDir, 'staging-'));
  try {
    const files = [];
    for (const relative of gatherFiles(repoRoot)) {
      const source = path.join(repoRoot, ...relative.split('/'));
      const destination = path.join(staging, ...relative.split('/'));
      // Hash the copied bytes, not a mutable worktree file read at a different time.
      const bytes = fs.readFileSync(source);
      fs.mkdirSync(path.dirname(destination), { recursive: true });
      fs.writeFileSync(destination, bytes);
      files.push({ path: relative, size: bytes.length, sha256: hash(bytes) });
    }
    const identity = { schemaVersion: 1, files };
    const contentId = hash(JSON.stringify(identity));
    const manifest = { ...identity, contentId };
    fs.writeFileSync(path.join(staging, 'source-manifest.json'), JSON.stringify(manifest, null, 2));
    const archivePath = path.join(outDir, `${contentId}.tar.gz`);
    const temporaryArchive = path.join(outDir, `${contentId}.${crypto.randomUUID()}.tar.gz`);
    const result = spawnSync('tar', ['-czf', temporaryArchive, '-C', staging, '.'], { encoding: 'utf8' });
    if (result.error || result.status !== 0) throw new Error(`Snapshot tar failed: ${result.error?.message || result.stderr}`);
    // Replacing an existing identical content snapshot does not change its identity.
    fs.renameSync(temporaryArchive, archivePath);
    return { contentId, archivePath, archiveSha256: hash(fs.readFileSync(archivePath)),
      fileCount: files.length, sourceBytes: files.reduce((sum, file) => sum + file.size, 0) };
  } finally {
    const resolved = path.resolve(staging);
    if (path.dirname(resolved) !== outDir || !path.basename(resolved).startsWith('staging-')) throw new Error('Unsafe snapshot cleanup path.');
    fs.rmSync(resolved, { recursive: true, force: true });
  }
}
module.exports = { createSnapshot, gatherFiles };
if (require.main === module) {
  try { process.stdout.write(`${JSON.stringify(createSnapshot())}\n`); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
