import fs from "node:fs/promises";
import path from "node:path";

export async function copyPortableNode(sourceRoot, destination) {
  // Official Node archives use relative npm/corepack links. fs.cp's default
  // rewrites those to the temporary extraction path, which is later removed.
  await fs.cp(sourceRoot, destination, { recursive: true, verbatimSymlinks: true });
}

export async function copyApiSource(repoRoot, appRoot) {
  const sourceRoot = path.join(repoRoot, "server/api");
  // Never copy all of server/: it contains this manager's staging directory.
  await fs.access(path.join(sourceRoot, "api/main.py"));
  await fs.cp(sourceRoot, path.join(appRoot, "server/api"), {
    recursive: true,
    filter(source) {
      const parts = path.relative(sourceRoot, source).split(path.sep);
      return !parts.some(part => ["__pycache__", ".pytest_cache", ".secrets", ".env"].includes(part))
        && parts[0] !== "data";
    },
  });
}
