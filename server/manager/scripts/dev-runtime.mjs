import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { pipeline } from 'node:stream/promises';
import { Readable, Transform } from 'node:stream';
import { createWriteStream } from 'node:fs';

export const managerRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const repoRoot = path.resolve(managerRoot, '../..');
export const devRoot = path.join(managerRoot, '.dev');
export const pythonRelative = platform => platform === 'win32' ? 'knu/.knu-runtime/python.exe' : 'knu/.knu-runtime/bin/python';
const binary = (name, platform) => platform === 'win32' ? `${name}.exe` : name;
export const fingerprint = text => createHash('sha256').update(text).digest('hex');
// Seed tools independently of the app version: a version-bump PR must not
// require its own not-yet-published release. Live source/dependencies stay current.
const macRuntimeSeedVersion = '0.2.3';

// Only used with api.github.com, never passed to archive download hosts.
export function githubHeaders() {
  const token = process.env.GH_TOKEN || process.env.GITHUB_TOKEN;
  return { Accept: 'application/vnd.github+json', 'User-Agent': 'knu-native-dev',
    ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

export async function validateRuntime(root, platform = process.platform, arch = process.arch) {
  const manifest = JSON.parse(await fs.readFile(path.join(root, 'runtime-manifest.json'), 'utf8'));
  if (manifest.schemaVersion !== 1 || manifest.platform !== platform || manifest.arch !== arch || manifest.python !== '3.12') {
    throw new Error(`Runtime OS/CPU/Python mismatch: need ${platform}-${arch}, Python 3.12`);
  }
  for (const relative of [pythonRelative(platform), ...['postgres/bin/postgres', 'postgres/bin/initdb',
    'postgres/bin/createdb', 'postgres/bin/psql', 'postgres/bin/pg_dump', 'redis/bin/redis-server',
    'java/bin/java', 'node/bin/node'].map(value => binary(value, platform)),
    'knu/server/api/requirements.txt', 'knu/server/api/third_party/hwp2hwpx/build/hwp2hwpx-patched.jar']) {
    if (!(await fs.stat(path.join(root, relative))).isFile()) throw new Error(`Runtime file missing: ${relative}`);
  }
  const vector = platform === 'win32' ? ['lib/vector.dll', 'lib/postgresql/vector.dll']
    : platform === 'darwin' ? ['lib/vector.dylib', 'lib/postgresql/vector.dylib'] : ['lib/vector.so', 'lib/postgresql/vector.so'];
  for (const alternatives of [vector, ['share/extension/vector.control', 'share/postgresql/extension/vector.control']]) {
    if (!(await Promise.all(alternatives.map(relative => exists(path.join(root, 'postgres', relative))))).some(Boolean)) {
      throw new Error(`Runtime pgvector missing: ${alternatives.join(' or ')}`);
    }
  }
  return manifest;
}

export async function exists(file) {
  try { await fs.access(file); return true; } catch (error) { if (error.code === 'ENOENT') return false; throw error; }
}

export function run(command, args, { cwd = repoRoot, env = process.env, capture = false, windowsVerbatimArguments = false } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env, windowsVerbatimArguments, stdio: capture ? ['ignore', 'pipe', 'pipe'] : 'inherit' });
    let output = '', errorOutput = '';
    if (capture) {
      child.stdout.on('data', bytes => output += bytes);
      child.stderr.on('data', bytes => errorOutput += bytes);
    }
    child.on('error', reject);
    child.on('exit', code => code === 0 ? resolve(output.trim()) : reject(new Error(`${path.basename(command)} exited with ${code}: ${errorOutput.slice(-2000)}`)));
  });
}

export async function downloadChecked(url, destination, sha256, fetchImpl = fetch) {
  if (!/^https:\/\//.test(url) || !/^[0-9a-f]{64}$/.test(sha256)) throw new Error('A HTTPS URL and SHA-256 are required');
  const response = await fetchImpl(url, { signal: AbortSignal.timeout(900_000) });
  if (!response.ok) throw new Error(`Download failed (${response.status}): ${url}`);
  const hash = createHash('sha256');
  let downloaded = 0, lastReport = Date.now();
  const hashing = new Transform({ transform(chunk, encoding, callback) {
    hash.update(chunk);
    downloaded += chunk.length;
    if (Date.now() - lastReport >= 30_000) {
      console.log(`[setup] Download ${path.basename(destination)}: ${Math.round(downloaded / 1024 / 1024)} MiB`);
      lastReport = Date.now();
    }
    callback(null, chunk);
  } });
  await pipeline(Readable.fromWeb(response.body), hashing, createWriteStream(destination, { flags: 'wx', mode: 0o600 }));
  if (hash.digest('hex') !== sha256) {
    await fs.rm(destination);
    throw new Error('Downloaded archive SHA-256 mismatch; nothing will be executed');
  }
}

export async function githubAsset(repository, tag, name) {
  const response = await fetch(`https://api.github.com/repos/${repository}/releases/tags/${encodeURIComponent(tag)}`,
    { headers: githubHeaders(), signal: AbortSignal.timeout(30_000) });
  if (!response.ok) throw new Error(`Cannot read release ${repository}/${tag}: HTTP ${response.status}`);
  const release = await response.json();
  const asset = release.assets.find(asset => asset.name === name);
  if (!asset?.digest?.startsWith('sha256:') || !asset.browser_download_url.startsWith(`https://github.com/${repository}/releases/download/`)) {
    throw new Error(`No checksum-verified asset ${name} in ${tag}`);
  }
  return { url: asset.browser_download_url, sha256: asset.digest.slice(7) };
}

export async function extract(archive, destination) {
  await fs.mkdir(destination, { recursive: true });
  if (archive.endsWith('.zip')) {
    if (process.platform === 'win32') {
      // Prefer Windows' built-in archive extractor for large runtime ZIPs;
      // PostgreSQL contains 21,000+ files. Retain the older PowerShell fallback.
      let hasTar = false;
      try { await run('tar.exe', ['--version'], { capture: true }); hasTar = true; } catch {}
      if (hasTar) {
        await run('tar.exe', ['-xf', archive, '-C', destination]);
        return;
      }
      // Read paths from environment, not interpolated PowerShell source.
      await run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
        'Expand-Archive -LiteralPath $env:KNU_ARCHIVE -DestinationPath $env:KNU_EXTRACT -Force'],
      { env: { ...process.env, KNU_ARCHIVE: archive, KNU_EXTRACT: destination } });
    } else await run('unzip', ['-q', archive, '-d', destination]);
  } else await run('tar', ['-xzf', archive, '-C', destination]);
}

export async function ensureUv() {
  const tools = path.join(devRoot, 'tools');
  const executable = path.join(tools, binary('uv', process.platform));
  if (await exists(executable)) return executable;
  const targets = { 'darwin-arm64': 'aarch64-apple-darwin', 'darwin-x64': 'x86_64-apple-darwin',
    'win32-x64': 'x86_64-pc-windows-msvc', 'linux-x64': 'x86_64-unknown-linux-gnu', 'linux-arm64': 'aarch64-unknown-linux-gnu' };
  const target = targets[`${process.platform}-${process.arch}`];
  if (!target) throw new Error('No portable uv for this OS/CPU');
  await fs.mkdir(tools, { recursive: true });
  const temporary = await fs.mkdtemp(path.join(tools, '.uv-'));
  try {
    const name = `uv-${target}${process.platform === 'win32' ? '.zip' : '.tar.gz'}`;
    const asset = await githubAsset('astral-sh/uv', '0.12.23', name);
    const archive = path.join(temporary, name);
    await downloadChecked(asset.url, archive, asset.sha256);
    const unpacked = path.join(temporary, 'unpacked');
    await extract(archive, unpacked);
    const nested = path.join(unpacked, `uv-${target}`, binary('uv', process.platform));
    await fs.copyFile(await exists(nested) ? nested : path.join(unpacked, binary('uv', process.platform)), executable);
    if (process.platform !== 'win32') await fs.chmod(executable, 0o755);
    return executable;
  } finally { await fs.rm(temporary, { recursive: true, force: true }); }
}

async function downloadMacRuntime(version) {
  if (process.arch !== 'arm64') throw new Error('Intel Mac release runtime is not published; supply --runtime with a matching staged runtime');
  const destination = path.join(devRoot, 'runtimes', `${version}-darwin-arm64`);
  if (await exists(destination)) { await validateRuntime(destination); return destination; }
  const asset = await githubAsset('knu-uic/knu-ai-assistant', `knu-server-v${version}`, `KNU.Server.Manager_${version}_macOS-arm64_unsigned.dmg`);
  await fs.mkdir(path.dirname(destination), { recursive: true });
  const temporary = await fs.mkdtemp(path.join(path.dirname(destination), '.download-'));
  const mount = path.join(temporary, 'mount');
  let mounted = false;
  try {
    const archive = path.join(temporary, 'manager.dmg');
    console.log('[setup] Downloading verified release runtime (large download, first setup only)');
    await downloadChecked(asset.url, archive, asset.sha256);
    await fs.mkdir(mount);
    await run('hdiutil', ['attach', '-readonly', '-nobrowse', '-mountpoint', mount, archive], { capture: true });
    mounted = true;
    const source = path.join(mount, 'KNU Server Manager.app/Contents/Resources/runtime');
    await validateRuntime(source);
    const staged = path.join(temporary, 'runtime');
    await fs.cp(source, staged, { recursive: true, verbatimSymlinks: true });
    await fs.rename(staged, destination);
    return destination;
  } finally {
    if (mounted) await run('hdiutil', ['detach', mount], { capture: true });
    await fs.rm(temporary, { recursive: true, force: true });
  }
}

async function preparePython(runtimeRoot, requirements) {
  const packaged = path.join(runtimeRoot, pythonRelative(process.platform));
  const bundledRequirements = await fs.readFile(path.join(runtimeRoot, 'knu/server/api/requirements.txt'), 'utf8');
  if (requirements === bundledRequirements) return packaged;
  // Never pip-install into a signed .app or a shared release runtime.
  const destination = path.join(devRoot, 'python', fingerprint(requirements));
  const marker = path.join(destination, 'ready.json');
  if (await exists(marker)) {
    const { python } = JSON.parse(await fs.readFile(marker, 'utf8'));
    if (await exists(python)) return python;
  }
  const uv = await ensureUv();
  await fs.mkdir(destination, { recursive: true });
  const env = { ...process.env, UV_PYTHON_INSTALL_DIR: destination, PYTHONDONTWRITEBYTECODE: '1' };
  const pythonVersion = await run(packaged, ['-B', '-c', 'import sys; print(sys.version.split()[0])'], { capture: true });
  await run(uv, ['python', 'install', pythonVersion, '--install-dir', destination], { env });
  const python = await run(uv, ['python', 'find', pythonVersion, '--managed-python'], { env, capture: true });
  await run(uv, ['pip', 'install', '--python', python, '--system', '--break-system-packages',
    '--requirements', path.join(repoRoot, 'server/api/requirements.txt')], { env });
  await fs.writeFile(marker, JSON.stringify({ python }), { mode: 0o600 });
  return python;
}

async function checkTools() {
  if (Number(process.versions.node.split('.')[0]) < 22) throw new Error('Node.js 22+ is required');
  try { await run('cargo', ['--version'], { capture: true }); }
  catch { throw new Error('Rust/Cargo is missing. Install Rust: https://rustup.rs/'); }
  if (process.platform === 'darwin') {
    try { await run('xcrun', ['--find', 'clang'], { capture: true }); }
    catch { throw new Error('Apple build tools are missing. Run xcode-select --install'); }
  }
}

export async function setup(args = process.argv.slice(2)) {
  await checkTools();
  await fs.mkdir(devRoot, { recursive: true, mode: 0o700 });
  const runtimeIndex = args.indexOf('--runtime');
  if (runtimeIndex >= 0 && !args[runtimeIndex + 1]) throw new Error('--runtime requires a directory');
  let runtimeRoot;
  if (runtimeIndex >= 0) {
    runtimeRoot = path.resolve(args[runtimeIndex + 1]);
    await validateRuntime(runtimeRoot);
  } else {
    let previous;
    try { previous = JSON.parse(await fs.readFile(path.join(devRoot, 'runtime.json'), 'utf8')).runtimeRoot; }
    catch (error) { if (error.code !== 'ENOENT' && !(error instanceof SyntaxError)) throw error; }
    const candidates = [previous, path.join(managerRoot, 'runtime'), process.platform === 'darwin'
      ? '/Applications/KNU Server Manager.app/Contents/Resources/runtime' : undefined].filter(Boolean);
    for (const candidate of candidates) {
      try { await validateRuntime(candidate); runtimeRoot = candidate; break; }
      catch (error) { if (await exists(candidate)) console.log(`[setup] Skipping ${candidate}: ${error.message}`); }
    }
    if (!runtimeRoot) {
      if (process.platform === 'darwin') {
        runtimeRoot = await downloadMacRuntime(macRuntimeSeedVersion);
      } else if (process.platform === 'win32' && process.arch === 'x64') {
        runtimeRoot = await prepareWindowsRuntime();
      } else throw new Error('No matching native runtime. Prepare a release runtime and pass --runtime PATH');
    }
  }
  const requirements = await fs.readFile(path.join(repoRoot, 'server/api/requirements.txt'), 'utf8');
  const nodeVersion = await run(path.join(runtimeRoot, binary('node/bin/node', process.platform)), ['--version'], { capture: true });
  if (!/^v\d+\./.test(nodeVersion) || Number(nodeVersion.slice(1).split('.')[0]) < 22) {
    throw new Error('The runtime must include Node.js 22+ for the conversation context engine');
  }
  const pythonPath = await preparePython(runtimeRoot, requirements);
  const pythonVersion = await run(pythonPath, ['-B', '-c', 'import sys; assert sys.version_info[:2] == (3,12); import importlib.metadata as m; [m.version(x) for x in ["fastapi","psycopg","arq","playwright"]]; print(sys.version.split()[0])'], { capture: true });
  console.log(`[setup] Portable Python ${pythonVersion}; host Python/DB/Redis are not used`);
  const hasPip = await run(pythonPath, ['-B', '-c', 'import importlib.util; print(bool(importlib.util.find_spec("pip")))'], { capture: true });
  if (hasPip === 'True') await run(pythonPath, ['-B', '-m', 'pip', 'check']);
  else await run(await ensureUv(), ['pip', 'check', '--python', pythonPath]);
  if (!args.includes('--skip-npm')) {
    const lock = await fs.readFile(path.join(managerRoot, 'package-lock.json'), 'utf8');
    const marker = path.join(devRoot, 'npm-lock.sha256');
    const installed = await exists(path.join(managerRoot, 'node_modules/@tauri-apps/cli/tauri.js'));
    const oldHash = await fs.readFile(marker, 'utf8').catch(() => '');
    if (!installed || oldHash !== fingerprint(lock)) {
      if (!process.env.npm_execpath) throw new Error('Run via npm run setup:dev so npm can install dependencies');
      await run(process.execPath, [process.env.npm_execpath, 'ci'], { cwd: managerRoot });
      await fs.writeFile(marker, fingerprint(lock));
    }
  }
  const config = { schemaVersion: 1, platform: process.platform, arch: process.arch, runtimeRoot: await fs.realpath(runtimeRoot),
    pythonPath: await fs.realpath(pythonPath), requirementsText: requirements };
  const temporary = path.join(devRoot, `runtime-${process.pid}.json.tmp`);
  await fs.writeFile(temporary, `${JSON.stringify(config, null, 2)}\n`, { mode: 0o600 });
  await fs.rename(temporary, path.join(devRoot, 'runtime.json'));
  console.log('[setup] Ready. Run npm run tauri dev and click server start.');
  console.log(`[setup] Live source: ${path.join(repoRoot, 'server/api')}`);
  console.log(`[setup] Isolated development data: ${path.join(devRoot, 'data')}`);
  console.log('[setup] Existing app/data/settings were not changed. No server has been started.');
}

async function prepareWindowsRuntime() {
  await run(process.execPath, [path.join(managerRoot, 'scripts/build-windows-runtime.mjs')], { cwd: managerRoot });
  const native = path.join(managerRoot, 'native-runtime/win32-x64');
  const uv = await ensureUv();
  const env = { ...process.env, KNU_MANAGER_UV: uv, KNU_BUILD_JAVA_HOME: path.join(native, 'java'),
    KNU_POSTGRES_RUNTIME: path.join(native, 'postgres'), KNU_REDIS_RUNTIME: path.join(native, 'redis'),
    KNU_JAVA_RUNTIME: path.join(native, 'java'), KNU_NODE_RUNTIME: path.join(native, 'node') };
  await run(process.execPath, [path.join(managerRoot, 'scripts/stage-runtime.mjs')], { env });
  const runtimeRoot = path.join(managerRoot, 'runtime');
  await validateRuntime(runtimeRoot);
  return runtimeRoot;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  setup().catch(error => { console.error(`[setup] ${error.message}`); process.exitCode = 1; });
}
