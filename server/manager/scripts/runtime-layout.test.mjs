import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { copyApiSource, copyPortableNode } from "./runtime-layout.mjs";

test("portable Node symlinks survive removal of the extraction directory", async () => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), "knu-node-links-"));
  try {
    const source = path.join(temporary, "extracted-node");
    const destination = path.join(temporary, "portable-node");
    await fs.mkdir(path.join(source, "bin"), { recursive: true });
    await fs.mkdir(path.join(source, "lib/node_modules/npm/bin"), { recursive: true });
    await fs.writeFile(path.join(source, "bin/node"), "test binary");
    await fs.writeFile(path.join(source, "lib/node_modules/npm/bin/npm-cli.js"), "// npm");
    await fs.symlink("../lib/node_modules/npm/bin/npm-cli.js", path.join(source, "bin/npm"));
    await copyPortableNode(source, destination);
    await fs.rm(source, { recursive: true });
    assert.equal(await fs.readlink(path.join(destination, "bin/npm")), "../lib/node_modules/npm/bin/npm-cli.js");
    assert.equal(await fs.readFile(path.join(destination, "bin/npm"), "utf8"), "// npm");
    assert.equal(await fs.readFile(path.join(destination, "bin/node"), "utf8"), "test binary");
  } finally {
    await fs.rm(temporary, { recursive: true, force: true });
  }
});

test("stage only server/api, preserving code but excluding credentials, data and the manager", async () => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), "knu-layout-test-"));
  try {
    const repoRoot = path.join(temporary, "repo");
    // Intentionally stage inside the manager, as the real build does.
    const appRoot = path.join(repoRoot, "server/manager/runtime/knu");
    const files = {
      "server/api/api/main.py": "# API entry",
      "server/api/database.py": "# legitimate source, not the data directory",
      "server/api/third_party/codmes-context-engine/bridge.mjs": "// bridge",
      "server/api/.env.example": "# public configuration template",
      "server/api/.env": "TEST_SECRET=not-a-real-secret",
      "server/api/data/private.json": "{}",
      "server/api/.secrets/private.json": "{}",
      "server/api/api/__pycache__/main.pyc": "cache",
      "server/api/.pytest_cache/state": "cache",
      "server/manager/package.json": "{}",
      "client/web/package.json": "{}",
    };
    for (const [relative, text] of Object.entries(files)) {
      const destination = path.join(repoRoot, relative);
      await fs.mkdir(path.dirname(destination), { recursive: true });
      await fs.writeFile(destination, text);
    }
    await fs.mkdir(appRoot, { recursive: true });
    await copyApiSource(repoRoot, appRoot);
    for (const relative of ["api/main.py", "database.py", "third_party/codmes-context-engine/bridge.mjs", ".env.example"]) {
      assert.equal(await fs.readFile(path.join(appRoot, "server/api", relative), "utf8"), files[`server/api/${relative}`]);
    }
    for (const relative of ["server/manager", "client", "server/api/.env", "server/api/data", "server/api/.secrets", "server/api/api/__pycache__", "server/api/.pytest_cache"]) {
      await assert.rejects(fs.access(path.join(appRoot, relative)), { code: "ENOENT" });
    }
    assert.equal(await fs.readFile(path.join(repoRoot, "server/api/.env"), "utf8"), files["server/api/.env"]);
  } finally {
    await fs.rm(temporary, { recursive: true, force: true });
  }
});

test("an invalid repository does not create a partial API bundle", async () => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), "knu-layout-missing-"));
  try {
    const appRoot = path.join(temporary, "stage");
    await assert.rejects(copyApiSource(temporary, appRoot), { code: "ENOENT" });
    await assert.rejects(fs.access(appRoot), { code: "ENOENT" });
  } finally {
    await fs.rm(temporary, { recursive: true, force: true });
  }
});
