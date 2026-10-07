import fs from 'node:fs/promises';
import path from 'node:path';
import { devRoot, repoRoot, run } from './dev-runtime.mjs';

const { pythonPath } = JSON.parse(await fs.readFile(path.join(devRoot, 'runtime.json'), 'utf8'));
await run(pythonPath, ['-B', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_process_lock.py', '-v'],
  { cwd: path.join(repoRoot, 'server/api') });
