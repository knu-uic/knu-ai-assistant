import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const managerRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = path.resolve(managerRoot, "../..");
const stageRoot = path.join(managerRoot, "runtime");
const appRoot = path.join(stageRoot, "knu");
const pythonBuildRoot = path.join(stageRoot, ".python-build");
const browserRoot = path.join(appRoot, ".playwright");
const uv = process.env.KNU_MANAGER_UV || (process.platform === "win32" ? "uv.exe" : "uv");

for (const variable of ["KNU_POSTGRES_RUNTIME", "KNU_REDIS_RUNTIME", "KNU_JAVA_RUNTIME"]) {
  if (!process.env[variable]) throw new Error(`${variable} is required for a standalone release.`);
}
if (!(process.env.KNU_BUILD_JAVA_HOME || process.env.JAVA_HOME)) {
  throw new Error("KNU_BUILD_JAVA_HOME or JAVA_HOME must point to a JDK 21 installation.");
}
await validateRuntimeInput("postgres", "KNU_POSTGRES_RUNTIME", postgresChecks());
await validateRuntimeInput("redis", "KNU_REDIS_RUNTIME", [binary("bin/redis-server")]);
await validateRuntimeInput("java", "KNU_JAVA_RUNTIME", [binary("bin/java")]);

await fs.rm(stageRoot, { recursive: true, force: true });
await fs.mkdir(appRoot, { recursive: true });

await fs.cp(path.join(repoRoot, "services"), path.join(appRoot, "services"), {
  recursive: true,
  filter(source) {
    const relative = path.relative(repoRoot, source).split(path.sep).join("/");
    return !(
      relative.includes("/__pycache__") ||
      relative.includes("/.pytest_cache") ||
      relative.startsWith("services/api/data") ||
      relative.endsWith("/.env")
    );
  },
});

const packagedPython = await stagePortablePython();
await stageNativeRuntime("postgres", "KNU_POSTGRES_RUNTIME", postgresChecks());
await stageNativeRuntime("redis", "KNU_REDIS_RUNTIME", [binary("bin/redis-server")]);
await stageNativeRuntime("java", "KNU_JAVA_RUNTIME", [binary("bin/java")]);
await stageOptionalRuntime("poppler", "KNU_POPPLER_RUNTIME");
await stageHwpConverter(packagedPython);

await fs.writeFile(
  path.join(stageRoot, "runtime-manifest.json"),
  `${JSON.stringify({
    schemaVersion: 1,
    platform: process.platform,
    arch: process.arch,
    python: "3.12",
    required: ["python", "postgresql-16", "pgvector", "redis", "paddleocr-tables"],
    optional: ["poppler"],
  }, null, 2)}\n`,
);

console.log(`[knu-manager] staged standalone runtime at ${stageRoot}`);

async function stagePortablePython() {
  const uvEnv = {
    ...process.env,
    UV_PYTHON_INSTALL_DIR: pythonBuildRoot,
    PLAYWRIGHT_BROWSERS_PATH: browserRoot,
  };
  await run(uv, ["python", "install", "3.12", "--install-dir", pythonBuildRoot, "--force"], repoRoot, uvEnv);
  const python = (await capture(uv, ["python", "find", "3.12", "--managed-python"], repoRoot, uvEnv)).trim();
  if (!path.isAbsolute(python)) throw new Error(`uv returned a non-absolute Python path: ${python}`);
  await run(uv, [
    "pip", "install", "--python", python, "--system", "--break-system-packages",
    "--requirements", path.join(repoRoot, "services/api/requirements.txt"),
  ], repoRoot, uvEnv);
  await run(python, ["-m", "playwright", "install", "chromium"], repoRoot, uvEnv);

  const distribution = process.platform === "win32"
    ? path.dirname(python)
    : path.dirname(path.dirname(python));
  const portable = path.join(appRoot, ".knu-runtime");
  await fs.cp(distribution, portable, { recursive: true, dereference: true });
  const packagedPython = process.platform === "win32"
    ? path.join(portable, "python.exe")
    : path.join(portable, "bin/python");
  if (process.platform !== "win32") await fs.chmod(packagedPython, 0o755);
  await run(packagedPython, [
    "-c",
    "import arq, fastapi, opendataloader_pdf, paddleocr, pgvector, playwright, psycopg, pymupdf, uvicorn; print('KNU Python runtime ready')",
  ], appRoot, { ...process.env, PLAYWRIGHT_BROWSERS_PATH: browserRoot });
  await run(packagedPython, [
    "-c",
    "from paddleocr import PaddleOCR, TableStructureRecognition; PaddleOCR(lang='korean', use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False); TableStructureRecognition(model_name='SLANet_plus'); print('KNU PDF table models ready')",
  ], appRoot, {
    ...process.env,
    PADDLE_PDX_CACHE_HOME: path.join(appRoot, ".paddlex"),
    PADDLE_PDX_MODEL_SOURCE: "BOS",
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK: "True",
  });
  await fs.rm(pythonBuildRoot, { recursive: true, force: true });
  return packagedPython;
}

async function stageHwpConverter(python) {
  const javaHome = process.env.KNU_BUILD_JAVA_HOME || process.env.JAVA_HOME;
  if (!javaHome) throw new Error("KNU_BUILD_JAVA_HOME or JAVA_HOME must point to a JDK 21 installation.");
  const output = path.join(appRoot, "services/api/third_party/hwp2hwpx/build/hwp2hwpx-patched.jar");
  await run("bash", [path.join(repoRoot, "services/api/third_party/hwp2hwpx/build-local.sh")], repoRoot, {
    ...process.env,
    PYTHON_BIN: python,
    JAVA_HOME: javaHome,
    HWP2HWPX_OUTPUT_JAR: output,
  });
}

async function stageNativeRuntime(name, envName, checks) {
  const absolute = path.resolve(process.env[envName]);
  await validateRuntimeInput(name, envName, checks);
  await fs.cp(absolute, path.join(stageRoot, name), { recursive: true, dereference: true });
}

async function validateRuntimeInput(name, envName, checks) {
  const source = process.env[envName];
  if (!source) throw new Error(`${envName} is required for the ${name} runtime.`);
  const absolute = path.resolve(source);
  for (const check of checks) {
    const candidates = Array.isArray(check) ? check : [check];
    let found = false;
    for (const candidate of candidates) {
      try {
        await fs.access(path.join(absolute, candidate));
        found = true;
        break;
      } catch {}
    }
    if (!found) throw new Error(`${envName} is incomplete; missing one of: ${candidates.join(", ")}`);
  }
}

async function stageOptionalRuntime(name, envName) {
  const source = process.env[envName];
  if (source) await fs.cp(path.resolve(source), path.join(stageRoot, name), { recursive: true, dereference: true });
}

function postgresChecks() {
  const library = process.platform === "win32"
    ? ["lib/vector.dll", "lib/postgresql/vector.dll"]
    : process.platform === "darwin"
      ? ["lib/postgresql/vector.dylib", "lib/vector.dylib"]
      : ["lib/postgresql/vector.so", "lib/vector.so"];
  return [
    binary("bin/postgres"),
    binary("bin/initdb"),
    binary("bin/createdb"),
    binary("bin/psql"),
    ["share/postgresql/extension/vector.control", "share/extension/vector.control"],
    library,
  ];
}

function binary(value) {
  return process.platform === "win32" ? `${value}.exe` : value;
}

function run(command, args, cwd, env = process.env) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env, stdio: "inherit" });
    child.on("error", reject);
    child.on("exit", code => code === 0 ? resolve() : reject(new Error(`${command} exited with ${code}`)));
  });
}

function capture(command, args, cwd, env = process.env) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env, stdio: ["ignore", "pipe", "inherit"] });
    let output = "";
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", chunk => { output += chunk; });
    child.on("error", reject);
    child.on("exit", code => code === 0 ? resolve(output) : reject(new Error(`${command} exited with ${code}`)));
  });
}
