// Project-local Windows x64 runtimes. No Windows service or global DB install.
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { devRoot, managerRoot, run, downloadChecked, extract, exists, githubHeaders } from './dev-runtime.mjs';

export const windowsArchives = {
  postgres: { url: 'https://get.enterprisedb.com/postgresql/postgresql-16.15-1-windows-x64-binaries.zip',
    // Vendor-confirmed: EnterpriseDB/edb-installers issue 696.
    sha256: '25e6fcdfb8caec38691bf461125e7564508760666f7b8e5dc6a5f0818f58f81e' },
  redis: { url: 'https://github.com/redis-windows/redis-windows/releases/download/7.2.15/Redis-7.2.15-Windows-x64-cygwin.zip',
    sha256: '093768b005af04d149b6c624706af56a92af3146bf49fdc8e63a7fbe99fc0604' },
  node: { url: 'https://nodejs.org/dist/v22.23.1/node-v22.23.1-win-x64.zip',
    sha256: '7df0bc9375723f4a86b3aa1b7cc73342423d9677a8df4538aca31a049e309c29' },
  java: { url: 'https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/OpenJDK21U-jdk_x64_windows_hotspot_21.0.12.1_1.zip',
    sha256: 'f9d6e191ab098c0d416e7d588a24420a8621cd2f4720dab2459b8b7b2d2d8b4e' },
};

async function githubFile(repository, revision, relative) {
  const response = await fetch(`https://api.github.com/repos/${repository}/contents/${relative}?ref=${revision}`,
    { headers: githubHeaders(), signal: AbortSignal.timeout(30_000) });
  if (!response.ok) throw new Error(`Cannot preserve upstream license: ${repository}/${relative}`);
  const body = await response.json();
  if (body.encoding !== 'base64') throw new Error('Unexpected upstream file encoding');
  return Buffer.from(body.content, 'base64');
}

async function msvcEnvironment() {
  try { await run('nmake.exe', ['/?'], { capture: true }); return process.env; } catch {}
  const programFiles = process.env['ProgramFiles(x86)'];
  if (!programFiles) throw new Error('Microsoft C++ Build Tools x64 are required');
  const vswhere = path.join(programFiles, 'Microsoft Visual Studio/Installer/vswhere.exe');
  const installation = await run(vswhere, ['-latest', '-products', '*', '-requires',
    'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'], { capture: true });
  if (!installation) throw new Error('Install Microsoft C++ Build Tools with Desktop development with C++');
  const batch = path.join(installation, 'Common7/Tools/VsDevCmd.bat');
  // cmd /s /c owns quoting; Node's extra argument escaping would turn this
  // quoted local batch path into a spurious network path.
  const output = await run('cmd.exe', ['/d', '/s', '/c', `""${batch}" -arch=x64 -host_arch=x64 >nul && set"`],
    { capture: true, windowsVerbatimArguments: true });
  const env = { ...process.env };
  for (const line of output.split(/\r?\n/)) {
    const delimiter = line.indexOf('=');
    if (delimiter > 0) {
      const name = line.slice(0, delimiter);
      for (const existing of Object.keys(env)) if (existing.toLowerCase() === name.toLowerCase()) delete env[existing];
      env[name] = line.slice(delimiter + 1);
    }
  }
  return env;
}

export async function buildWindowsRuntime() {
  if (process.platform !== 'win32' || process.arch !== 'x64') throw new Error('Windows native runtime builder currently requires Windows x64');
  const destination = path.join(managerRoot, 'native-runtime/win32-x64');
  const marker = path.join(destination, 'native-manifest.json');
  const manifest = { schemaVersion: 1, platform: 'win32', arch: 'x64', archives: windowsArchives,
    pgvectorRevision: '8ee86c96f0fd72390f890aa8a336fda6d3ab4c6c' };
  if (await exists(marker)) {
    if ((await fs.readFile(marker, 'utf8')).trim() === JSON.stringify(manifest)) return destination;
    throw new Error('Windows runtime inputs changed; move the old native-runtime/win32-x64 aside first (no automatic deletion)');
  }
  if (await exists(destination)) throw new Error('Incomplete Windows runtime exists; move it aside before retrying');
  const env = await msvcEnvironment();
  await fs.mkdir(devRoot, { recursive: true });
  const temporary = await fs.mkdtemp(path.join(devRoot, '.windows-build-'));
  try {
    for (const [name, asset] of Object.entries(windowsArchives)) {
      console.log(`[setup] Preparing Windows ${name}`);
      const archive = path.join(temporary, `${name}.zip`);
      await downloadChecked(asset.url, archive, asset.sha256);
      await extract(archive, path.join(temporary, `unpacked-${name}`));
    }
    const staged = path.join(temporary, 'native');
    await fs.mkdir(staged);
    await fs.rename(path.join(temporary, 'unpacked-postgres/pgsql'), path.join(staged, 'postgres'));
    await fs.mkdir(path.join(staged, 'redis'));
    await fs.rename(path.join(temporary, 'unpacked-redis/Redis-7.2.15-Windows-x64-cygwin'), path.join(staged, 'redis/bin'));
    await fs.mkdir(path.join(staged, 'node'));
    await fs.rename(path.join(temporary, 'unpacked-node/node-v22.23.1-win-x64'), path.join(staged, 'node/bin'));
    await fs.copyFile(path.join(staged, 'node/bin/LICENSE'), path.join(staged, 'node/LICENSE'));
    const javaDirectory = (await fs.readdir(path.join(temporary, 'unpacked-java'), { withFileTypes: true })).find(entry => entry.isDirectory());
    if (!javaDirectory) throw new Error('JDK archive has no root directory');
    await fs.rename(path.join(temporary, 'unpacked-java', javaDirectory.name), path.join(staged, 'java'));
    const vectorSource = path.join(temporary, 'pgvector');
    await run('git', ['init', vectorSource]);
    await run('git', ['-C', vectorSource, 'remote', 'add', 'origin', 'https://github.com/pgvector/pgvector.git']);
    await run('git', ['-C', vectorSource, 'fetch', '--depth', '1', 'origin', manifest.pgvectorRevision]);
    await run('git', ['-C', vectorSource, 'checkout', '--detach', 'FETCH_HEAD']);
    const revision = await run('git', ['-C', vectorSource, 'rev-parse', 'HEAD'], { capture: true });
    if (revision !== manifest.pgvectorRevision) throw new Error('pgvector revision mismatch');
    const buildEnv = { ...env, PGROOT: path.join(staged, 'postgres') };
    await run('nmake.exe', ['/F', 'Makefile.win'], { cwd: vectorSource, env: buildEnv });
    await run('nmake.exe', ['/F', 'Makefile.win', 'install'], { cwd: vectorSource, env: buildEnv });
    await fs.mkdir(path.join(staged, 'licenses'));
    await fs.copyFile(path.join(vectorSource, 'LICENSE'), path.join(staged, 'licenses/pgvector-LICENSE'));
    const redisLicenses = path.join(staged, 'redis/licenses');
    await fs.mkdir(redisLicenses);
    await fs.writeFile(path.join(redisLicenses, 'redis-COPYING'), await githubFile('redis/redis', '7.2.15', 'COPYING'));
    await fs.writeFile(path.join(redisLicenses, 'windows-port-LICENSE'), await githubFile('redis-windows/redis-windows', '84b0e0ab923d5d4cdbd4f9f48def99a5fa9ee2ff', 'LICENSE'));
    await fs.writeFile(path.join(redisLicenses, 'PROVENANCE.txt'),
      'Community Redis 7.2.15 Windows Cygwin port, not an official Redis Windows distribution.\n'
      + 'Binary archive: ' + windowsArchives.redis.url + '\nSHA256: ' + windowsArchives.redis.sha256 + '\n'
      + 'Bundled Cygwin/crypto/compression DLLs have their own licenses.\n'
      + 'Upstream build/source: https://github.com/redis-windows/redis-windows/tree/84b0e0ab923d5d4cdbd4f9f48def99a5fa9ee2ff\n'
      + 'Cygwin licensing/source: https://cygwin.com/licensing.html https://cygwin.com/install.html\n'
      + 'This preparation is for local development; review complete DLL notices/source obligations before public Windows redistribution.\n');
    await run(path.join(staged, 'postgres/bin/postgres.exe'), ['--version']);
    await run(path.join(staged, 'redis/bin/redis-server.exe'), ['--version']);
    await run(path.join(staged, 'node/bin/node.exe'), ['--version']);
    await fs.writeFile(path.join(staged, 'native-manifest.json'), JSON.stringify(manifest));
    await fs.mkdir(path.dirname(destination), { recursive: true });
    await fs.rename(staged, destination);
    return destination;
  } finally { await fs.rm(temporary, { recursive: true, force: true }); }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  buildWindowsRuntime().catch(error => { console.error(error.message); process.exitCode = 1; });
}
