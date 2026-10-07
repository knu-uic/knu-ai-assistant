import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fingerprint, validateRuntime, pythonRelative, downloadChecked } from './dev-runtime.mjs';
import { applyUnifiedPatch } from './prepare-hwp-converter.mjs';
import { windowsArchives } from './build-windows-runtime.mjs';

async function fixture(platform, arch) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'knu-dev-test-'));
  const suffix = platform === 'win32' ? '.exe' : '';
  const paths = [pythonRelative(platform), ...['postgres/bin/postgres', 'postgres/bin/initdb', 'postgres/bin/createdb',
    'postgres/bin/psql', 'postgres/bin/pg_dump', 'redis/bin/redis-server', 'java/bin/java', 'node/bin/node'].map(x => x + suffix),
  'knu/server/api/requirements.txt', 'knu/server/api/third_party/hwp2hwpx/build/hwp2hwpx-patched.jar',
  `postgres/lib/vector.${platform === 'win32' ? 'dll' : platform === 'darwin' ? 'dylib' : 'so'}`,
  'postgres/share/extension/vector.control'];
  for (const relative of paths) {
    await fs.mkdir(path.dirname(path.join(root, relative)), { recursive: true });
    await fs.writeFile(path.join(root, relative), 'fixture');
  }
  await fs.writeFile(path.join(root, 'runtime-manifest.json'), JSON.stringify({ schemaVersion: 1, platform, arch, python: '3.12' }));
  return root;
}

for (const [platform, arch] of [['darwin', 'arm64'], ['win32', 'x64']]) {
  test(`validates ${platform} native layout without relying on a host Python`, async () => {
    const root = await fixture(platform, arch);
    try {
      assert.equal((await validateRuntime(root, platform, arch)).python, '3.12');
      await fs.rm(path.join(root, pythonRelative(platform)));
      await assert.rejects(validateRuntime(root, platform, arch), /ENOENT/);
    } finally { await fs.rm(root, { recursive: true, force: true }); }
  });
}

test('refuses a runtime for another OS/CPU', async () => {
  const root = await fixture('darwin', 'arm64');
  try { await assert.rejects(validateRuntime(root, 'win32', 'x64'), /mismatch/); }
  finally { await fs.rm(root, { recursive: true, force: true }); }
});

test('every Windows download is HTTPS and pinned to a SHA256', () => {
  for (const asset of Object.values(windowsArchives)) {
    assert.match(asset.url, /^https:\/\//);
    assert.match(asset.sha256, /^[a-f0-9]{64}$/);
  }
});

test('dependency fingerprint changes for dependencies, not live source files', () => {
  assert.equal(fingerprint('fastapi==1\n'), fingerprint('fastapi==1\n'));
  assert.notEqual(fingerprint('fastapi==1\n'), fingerprint('fastapi==2\n'));
});

test('HWP patch applies on Windows CRLF and refuses mismatched upstream code', () => {
  const patch = '--- a\n+++ b\n@@ -1,2 +1,3 @@\n first\n-old\n+new\n+extra\n';
  assert.equal(applyUnifiedPatch('first\r\nold\r\n', patch), 'first\nnew\nextra\n');
  assert.throws(() => applyUnifiedPatch('first\nchanged\n', patch), /context mismatch/);
});

test('download rejects insecure input before fetching or creating a file', async () => {
  await assert.rejects(downloadChecked('http://example.invalid/a', '/never-written', 'a'.repeat(64)), /HTTPS/);
});

test('verified downloads stream to disk and discard checksum failures', async () => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'knu-download-test-'));
  const bytes = 'native-runtime-fixture';
  const fetchFixture = async () => new Response(bytes);
  try {
    const archive = path.join(temporary, 'runtime.zip');
    await downloadChecked('https://example.invalid/runtime.zip', archive, fingerprint(bytes), fetchFixture);
    assert.equal(await fs.readFile(archive, 'utf8'), bytes);
    const invalid = path.join(temporary, 'invalid.zip');
    await assert.rejects(downloadChecked('https://example.invalid/runtime.zip', invalid, '0'.repeat(64), fetchFixture), /SHA-256 mismatch/);
    await assert.rejects(fs.access(invalid), { code: 'ENOENT' });
  } finally { await fs.rm(temporary, { recursive: true, force: true }); }
});
