import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { run } from './dev-runtime.mjs';

// Apply our checked-in text patch without requiring a Unix patch/bash command.
export function applyUnifiedPatch(source, patch) {
  let lines = source.replace(/\r\n/g, '\n').split('\n');
  const changes = patch.replace(/\r\n/g, '\n').split('\n');
  let offset = 0;
  for (let index = 0; index < changes.length; index++) {
    const header = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(changes[index]);
    if (!header) continue;
    const oldLines = [], newLines = [];
    for (index++; index < changes.length && !changes[index].startsWith('@@'); index++) {
      const line = changes[index];
      if (line.startsWith(' ')) { oldLines.push(line.slice(1)); newLines.push(line.slice(1)); }
      else if (line.startsWith('-')) oldLines.push(line.slice(1));
      else if (line.startsWith('+')) newLines.push(line.slice(1));
      else if (line !== '') throw new Error('Unsupported patch line');
    }
    index--;
    const start = Number(header[1]) - 1 + offset;
    if (lines.slice(start, start + oldLines.length).join('\n') !== oldLines.join('\n')) throw new Error('HWP converter patch context mismatch');
    lines.splice(start, oldLines.length, ...newLines);
    offset += newLines.length - oldLines.length;
  }
  return lines.join('\n');
}

export async function prepareHwpConverter({ python, uv, javaHome, apiRoot, destination }) {
  const temporary = await fs.mkdtemp(path.join(path.dirname(destination), '.hwp-build-'));
  try {
    const packageRoot = path.join(temporary, 'package');
    await run(uv, ['pip', 'install', '--python', python, '--target', packageRoot, 'hwp2hwpx==1.0.1']);
    const revision = 'edc05278506b663d5bdd98050a51f54b7ff5e0bc';
    const response = await fetch(`https://api.github.com/repos/neolord0/hwp2hwpx/contents/src/main/java/kr/dogfoot/hwp2hwpx/ForContentHPFFile.java?ref=${revision}`,
      { headers: { 'User-Agent': 'knu-runtime-builder', Accept: 'application/vnd.github+json' }, signal: AbortSignal.timeout(30_000) });
    if (!response.ok) throw new Error(`HWP source download failed: ${response.status}`);
    const body = await response.json();
    if (body.encoding !== 'base64') throw new Error('Invalid HWP source response');
    const source = Buffer.from(body.content, 'base64').toString('utf8');
    const patch = await fs.readFile(path.join(apiRoot, 'third_party/hwp2hwpx/null-extension.patch'), 'utf8');
    const javaFile = path.join(temporary, 'ForContentHPFFile.java');
    await fs.writeFile(javaFile, applyUnifiedPatch(source, patch));
    const classes = path.join(temporary, 'classes');
    await fs.mkdir(classes);
    const jar = path.join(packageRoot, 'hwp2hwpx/jars/hwp2hwpx.jar');
    const suffix = process.platform === 'win32' ? '.exe' : '';
    await run(path.join(javaHome, `bin/javac${suffix}`), ['-encoding', 'UTF-8', '-cp', jar, '-d', classes, javaFile]);
    await fs.copyFile(jar, destination);
    await run(path.join(javaHome, `bin/jar${suffix}`), ['uf', destination, '-C', classes, 'kr/dogfoot/hwp2hwpx/ForContentHPFFile.class']);
  } finally { await fs.rm(temporary, { recursive: true, force: true }); }
}
