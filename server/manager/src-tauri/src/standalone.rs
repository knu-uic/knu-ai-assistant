use base64::{engine::general_purpose::URL_SAFE, Engine as _};
use rand::{distributions::Alphanumeric, Rng, RngCore};
use serde::{Deserialize, Serialize};
use std::{
    collections::VecDeque,
    env, fs,
    io::{BufRead, BufReader},
    net::{SocketAddr, TcpListener, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Output, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::Duration,
};

// Keep this distinct from Codmes Server's managed PostgreSQL port (55432) so
// both desktop managers can run on the same Mac.
pub const DEFAULT_API_PORT: u16 = 8000;
pub const DEFAULT_POSTGRES_PORT: u16 = 55433;
pub const DEFAULT_REDIS_PORT: u16 = 56379;

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
pub struct RuntimePorts {
    pub api: u16,
    pub postgres: u16,
    pub redis: u16,
}

impl Default for RuntimePorts {
    fn default() -> Self {
        Self {
            api: DEFAULT_API_PORT,
            postgres: DEFAULT_POSTGRES_PORT,
            redis: DEFAULT_REDIS_PORT,
        }
    }
}

#[derive(Deserialize, Serialize)]
struct RuntimeSecrets {
    postgres_password: String,
    auth_jwt_secret: String,
    portal_sync_enc_key: String,
    mcp_auth_token: String,
}

pub struct EmbeddedProcesses {
    pub postgres: Option<Child>,
    pub redis: Option<Child>,
}

impl EmbeddedProcesses {
    pub fn empty() -> Self {
        Self {
            postgres: None,
            redis: None,
        }
    }
}

pub struct StandaloneRuntime {
    runtime_root: PathBuf,
    data_root: PathBuf,
    postgres: PathBuf,
    initdb: PathBuf,
    createdb: PathBuf,
    psql: PathBuf,
    redis: PathBuf,
    secrets: RuntimeSecrets,
    ports: Mutex<RuntimePorts>,
}

impl StandaloneRuntime {
    pub fn discover(runtime_root: PathBuf, data_root: PathBuf) -> Result<Self, String> {
        let postgres = runtime_root
            .join("postgres/bin")
            .join(executable("postgres"));
        if !postgres.is_file() {
            return Err(format!(
                "독립 실행 PostgreSQL이 없습니다: {}",
                postgres.display()
            ));
        }
        let runtime = Self {
            initdb: runtime_root.join("postgres/bin").join(executable("initdb")),
            createdb: runtime_root
                .join("postgres/bin")
                .join(executable("createdb")),
            psql: runtime_root.join("postgres/bin").join(executable("psql")),
            redis: runtime_root
                .join("redis/bin")
                .join(executable("redis-server")),
            postgres,
            secrets: load_or_create_secrets(&data_root)?,
            ports: Mutex::new(load_ports(&data_root)?),
            runtime_root,
            data_root,
        };
        for binary in [
            &runtime.initdb,
            &runtime.createdb,
            &runtime.psql,
            &runtime.redis,
        ] {
            if !binary.is_file() {
                return Err(format!(
                    "독립 실행 런타임 파일이 없습니다: {}",
                    binary.display()
                ));
            }
        }
        Ok(runtime)
    }

    pub fn data_root(&self) -> &Path {
        &self.data_root
    }

    pub fn ports(&self) -> RuntimePorts {
        self.ports.lock().map(|ports| *ports).unwrap_or_default()
    }

    fn prepare_ports(&self, logs: &Arc<Mutex<VecDeque<String>>>) -> Result<RuntimePorts, String> {
        let current = self.ports();
        let selected = RuntimePorts {
            api: current.api,
            postgres: select_available_port(current.postgres, 55433, 55449, "PostgreSQL")?,
            redis: select_available_port(current.redis, 56379, 56399, "Redis")?,
        };
        if selected.api != current.api
            || selected.postgres != current.postgres
            || selected.redis != current.redis
        {
            save_ports(&self.data_root, selected)?;
            if let Ok(mut ports) = self.ports.lock() {
                *ports = selected;
            }
            push_log(
                logs,
                format!(
                    "[manager] 포트 충돌 자동 조정: PostgreSQL {}→{}, Redis {}→{}",
                    current.postgres, selected.postgres, current.redis, selected.redis
                ),
            );
        }
        Ok(selected)
    }

    pub fn prepare_api_port(&self, logs: &Arc<Mutex<VecDeque<String>>>) -> Result<u16, String> {
        let current = self.ports();
        let selected = select_available_port(current.api, 8000, 8019, "KNU API")?;
        if selected != current.api {
            let updated = RuntimePorts {
                api: selected,
                ..current
            };
            save_ports(&self.data_root, updated)?;
            if let Ok(mut ports) = self.ports.lock() {
                *ports = updated;
            }
            push_log(
                logs,
                format!(
                    "[manager] 포트 충돌 자동 조정: API {}→{}",
                    current.api, selected
                ),
            );
        }
        Ok(selected)
    }

    pub fn configure_command(&self, command: &mut Command) {
        let postgres_password = &self.secrets.postgres_password;
        let ports = self.ports();
        command
            // Python must not add cache files to the sealed macOS app bundle.
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .env(
                "KNU_CONTEXT_NODE",
                self.runtime_root.join("node/bin").join(executable("node")),
            )
            .env("RUNTIME_ENV", "local")
            .env(
                "DATABASE_URL",
                format!(
                    "postgresql://knu:{postgres_password}@127.0.0.1:{}/knu",
                    ports.postgres
                ),
            )
            .env("DB_HOST", "127.0.0.1")
            .env("DB_PORT", ports.postgres.to_string())
            .env("DB_NAME", "knu")
            .env("DB_USER", "knu")
            .env("DB_PASSWORD", postgres_password)
            // PostgreSQL CLI tools (psql/createdb) do not read DB_PASSWORD.
            // Pass their standard password variable for the first-run database
            // existence check and creation over the SCRAM-protected TCP socket.
            .env("PGPASSWORD", postgres_password)
            .env("REDIS_URL", format!("redis://127.0.0.1:{}", ports.redis))
            .env("AUTH_JWT_SECRET", &self.secrets.auth_jwt_secret)
            .env("PORTAL_SYNC_ENC_KEY", &self.secrets.portal_sync_enc_key)
            .env("MCP_AUTH_TOKEN", &self.secrets.mcp_auth_token)
            .env("EMBEDDING_DIM", env_or("EMBEDDING_DIM", "1024"))
            .env("EMBEDDING_PROVIDER", env_or("EMBEDDING_PROVIDER", "local"))
            .env(
                "EMBEDDING_MODEL",
                env_or("EMBEDDING_MODEL", "bge-m3:latest"),
            )
            .env("RERANKER_ENABLED", env_or("RERANKER_ENABLED", "true"))
            .env("RERANKER_PROVIDER", "local")
            .env(
                "RERANKER_MODEL",
                env_or("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
            )
            .env("RERANKER_MAX_LENGTH", env_or("RERANKER_MAX_LENGTH", "512"))
            .env("HF_HOME", self.data_root.join("models/huggingface"))
            .env("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            .env(
                "OPENAI_COMPAT_BASE_URL",
                env_or("OPENAI_COMPAT_BASE_URL", "http://127.0.0.1:11434/v1"),
            )
            .env("VLM_PROVIDER", env_or("VLM_PROVIDER", "ollama"))
            .env("LLM_MODEL", env_or("LLM_MODEL", "gemma4:12b-mlx"))
            .env(
                "DOCUMENT_IMAGE_ANALYSIS_ENABLED",
                env_or("DOCUMENT_IMAGE_ANALYSIS_ENABLED", "true"),
            )
            .env(
                "NOTICE_POLL_ENABLED",
                env_or("NOTICE_POLL_ENABLED", "false"),
            )
            .env("DOCUMENT_ASSETS_ROOT", self.data_root.join("assets"))
            .env(
                "HWP2HWPX_JAR",
                self.runtime_root
                    .join("knu/server/api/third_party/hwp2hwpx/build/hwp2hwpx-patched.jar"),
            )
            .env("HWP_ASSETS_ROOT", self.data_root.join("assets"))
            .env(
                "KNU_CODEX_AUTH_PATH",
                self.data_root.join("config/codex-auth.json"),
            )
            .env(
                "PLAYWRIGHT_BROWSERS_PATH",
                self.runtime_root.join("knu/.playwright"),
            )
            .env(
                "PADDLE_PDX_CACHE_HOME",
                self.runtime_root.join("knu/.paddlex"),
            )
            .env("PADDLE_PDX_MODEL_SOURCE", "BOS")
            .env("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True");

        let mut path_entries = vec![
            self.runtime_root.join("postgres/bin"),
            self.runtime_root.join("redis/bin"),
        ];
        let poppler = self.runtime_root.join("poppler/bin");
        if poppler.is_dir() {
            path_entries.push(poppler);
        }
        let java_home = self.runtime_root.join("java");
        if java_home.is_dir() {
            command.env("JAVA_HOME", &java_home);
            path_entries.push(java_home.join("bin"));
        }
        if let Some(existing) = env::var_os("PATH") {
            path_entries.extend(env::split_paths(&existing));
        }
        if let Ok(value) = env::join_paths(path_entries) {
            command.env("PATH", value);
        }

        let postgres_lib = self.runtime_root.join("postgres/lib");
        #[cfg(target_os = "macos")]
        command.env(
            "DYLD_LIBRARY_PATH",
            prepend_library_path(&postgres_lib, "DYLD_LIBRARY_PATH"),
        );
        #[cfg(all(unix, not(target_os = "macos")))]
        command.env(
            "LD_LIBRARY_PATH",
            prepend_library_path(&postgres_lib, "LD_LIBRARY_PATH"),
        );
    }

    pub fn start(&self, logs: &Arc<Mutex<VecDeque<String>>>) -> Result<EmbeddedProcesses, String> {
        self.prepare_ports(logs)?;
        fs::create_dir_all(self.data_root.join("assets")).map_err(|e| e.to_string())?;
        fs::create_dir_all(self.data_root.join("logs")).map_err(|e| e.to_string())?;
        fs::create_dir_all(self.data_root.join("postgres-socket")).map_err(|e| e.to_string())?;
        let mut processes = EmbeddedProcesses::empty();
        processes.postgres = Some(self.start_postgres(logs)?);
        if let Err(error) = self.ensure_database(logs) {
            stop_child(&mut processes.postgres);
            return Err(error);
        }
        match self.start_redis(logs) {
            Ok(child) => processes.redis = Some(child),
            Err(error) => {
                stop_child(&mut processes.postgres);
                return Err(error);
            }
        }
        Ok(processes)
    }

    fn start_postgres(&self, logs: &Arc<Mutex<VecDeque<String>>>) -> Result<Child, String> {
        let port = self.ports().postgres;
        let data = self.data_root.join("postgres");
        if !data.join("PG_VERSION").is_file() {
            fs::create_dir_all(&data).map_err(|e| e.to_string())?;
            let password_file = self.data_root.join("config/.postgres-password.init");
            fs::write(
                &password_file,
                format!("{}\n", self.secrets.postgres_password),
            )
            .map_err(|e| e.to_string())?;
            set_private_permissions(&password_file)?;
            let mut command = Command::new(&self.initdb);
            self.configure_command(&mut command);
            let output = command
                .args([
                    "-D",
                    &data.to_string_lossy(),
                    "-U",
                    "knu",
                    "--pwfile",
                    &password_file.to_string_lossy(),
                    "--auth-host=scram-sha-256",
                    "--auth-local=trust",
                    "--encoding=UTF8",
                    "--locale=C",
                ])
                .output()
                .map_err(|e| format!("PostgreSQL 초기화를 실행하지 못했습니다: {e}"))?;
            let _ = fs::remove_file(&password_file);
            log_output(logs, "postgres-init", &output);
            if !output.status.success() {
                return Err("내장 PostgreSQL 데이터 디렉터리 초기화에 실패했습니다.".into());
            }
        }
        ensure_port_free(port, "PostgreSQL")?;
        let mut command = Command::new(&self.postgres);
        self.configure_command(&mut command);
        command.args([
            "-D",
            &data.to_string_lossy(),
            "-h",
            "127.0.0.1",
            "-p",
            &port.to_string(),
        ]);
        // All Manager connections use loopback TCP. Disable unused Unix
        // sockets so long repository/temp paths cannot prevent startup.
        #[cfg(not(target_os = "windows"))]
        command.args(["-c", "unix_socket_directories="]);
        let mut child = command
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("내장 PostgreSQL을 시작하지 못했습니다: {e}"))?;
        pipe_output(&mut child, "postgres", logs.clone());
        if let Err(error) = wait_for_port(&mut child, port, "PostgreSQL", Duration::from_secs(15)) {
            stop_child(&mut Some(child));
            return Err(error);
        }
        Ok(child)
    }

    fn ensure_database(&self, logs: &Arc<Mutex<VecDeque<String>>>) -> Result<(), String> {
        let port = self.ports().postgres;
        let mut check = Command::new(&self.psql);
        self.configure_command(&mut check);
        let output = check
            .args([
                "-h",
                "127.0.0.1",
                "-p",
                &port.to_string(),
                "-U",
                "knu",
                "-d",
                "postgres",
                "-tAc",
                "SELECT 1 FROM pg_database WHERE datname='knu'",
            ])
            .output()
            .map_err(|e| format!("내장 PostgreSQL을 확인하지 못했습니다: {e}"))?;
        log_output(logs, "postgres-check", &output);
        if !output.status.success() {
            return Err("내장 PostgreSQL 연결 확인에 실패했습니다.".into());
        }
        if String::from_utf8_lossy(&output.stdout).trim() == "1" {
            return Ok(());
        }
        let mut create = Command::new(&self.createdb);
        self.configure_command(&mut create);
        let output = create
            .args([
                "-h",
                "127.0.0.1",
                "-p",
                &port.to_string(),
                "-U",
                "knu",
                "knu",
            ])
            .output()
            .map_err(|e| format!("KNU 데이터베이스를 만들지 못했습니다: {e}"))?;
        log_output(logs, "postgres-create", &output);
        output
            .status
            .success()
            .then_some(())
            .ok_or_else(|| "KNU 데이터베이스 생성에 실패했습니다.".into())
    }

    fn start_redis(&self, logs: &Arc<Mutex<VecDeque<String>>>) -> Result<Child, String> {
        let port = self.ports().redis;
        ensure_port_free(port, "Redis")?;
        let data = self.data_root.join("redis");
        let redis_directory = if cfg!(target_os = "windows") {
            ".".to_string()
        } else {
            data.to_string_lossy().into_owned()
        };
        fs::create_dir_all(&data).map_err(|e| e.to_string())?;
        let mut command = Command::new(&self.redis);
        self.configure_command(&mut command);
        let mut child = command
            // Relative paths also work with the Windows Cygwin Redis port;
            // Windows drive paths passed to --dir do not.
            .current_dir(&data)
            .args([
                "--bind",
                "127.0.0.1",
                "--port",
                &port.to_string(),
                "--dir",
                &redis_directory,
                "--appendonly",
                "yes",
                "--protected-mode",
                "yes",
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("내장 Redis를 시작하지 못했습니다: {e}"))?;
        pipe_output(&mut child, "redis", logs.clone());
        if let Err(error) = wait_for_port(&mut child, port, "Redis", Duration::from_secs(10)) {
            stop_child(&mut Some(child));
            return Err(error);
        }
        Ok(child)
    }
}

fn load_or_create_secrets(data_root: &Path) -> Result<RuntimeSecrets, String> {
    let config = data_root.join("config");
    fs::create_dir_all(&config).map_err(|e| e.to_string())?;
    let path = config.join("runtime-secrets.json");
    if let Ok(raw) = fs::read_to_string(&path) {
        return serde_json::from_str(&raw)
            .map_err(|e| format!("런타임 보안 설정을 읽지 못했습니다: {e}"));
    }
    let mut fernet = [0_u8; 32];
    rand::thread_rng().fill_bytes(&mut fernet);
    let secrets = RuntimeSecrets {
        postgres_password: random_string(48),
        auth_jwt_secret: random_string(64),
        portal_sync_enc_key: URL_SAFE.encode(fernet),
        mcp_auth_token: random_string(64),
    };
    let temporary = config.join(".runtime-secrets.json.tmp");
    fs::write(
        &temporary,
        serde_json::to_vec_pretty(&secrets).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    set_private_permissions(&temporary)?;
    fs::rename(&temporary, &path).map_err(|e| e.to_string())?;
    Ok(secrets)
}

fn ports_path(data_root: &Path) -> PathBuf {
    data_root.join("config/runtime-ports.json")
}

fn load_ports(data_root: &Path) -> Result<RuntimePorts, String> {
    let path = ports_path(data_root);
    match fs::read(&path) {
        Ok(raw) => serde_json::from_slice(&raw)
            .map_err(|error| format!("런타임 포트 설정을 읽지 못했습니다: {error}")),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(RuntimePorts::default()),
        Err(error) => Err(format!("런타임 포트 설정을 읽지 못했습니다: {error}")),
    }
}

fn save_ports(data_root: &Path, ports: RuntimePorts) -> Result<(), String> {
    let path = ports_path(data_root);
    let config = path
        .parent()
        .ok_or_else(|| "런타임 설정 경로가 올바르지 않습니다.".to_string())?;
    fs::create_dir_all(config).map_err(|error| error.to_string())?;
    let temporary = config.join(".runtime-ports.json.tmp");
    fs::write(
        &temporary,
        serde_json::to_vec_pretty(&ports).map_err(|error| error.to_string())?,
    )
    .map_err(|error| error.to_string())?;
    set_private_permissions(&temporary)?;
    fs::rename(&temporary, &path).map_err(|error| error.to_string())?;
    Ok(())
}

fn select_available_port(preferred: u16, start: u16, end: u16, name: &str) -> Result<u16, String> {
    if port_is_free(preferred) {
        return Ok(preferred);
    }
    (start..=end)
        .find(|port| *port != preferred && port_is_free(*port))
        .ok_or_else(|| format!("{name}에 사용할 빈 포트를 {start}–{end} 범위에서 찾지 못했습니다."))
}

fn port_is_free(port: u16) -> bool {
    TcpListener::bind(("127.0.0.1", port)).is_ok()
}

fn random_string(length: usize) -> String {
    rand::thread_rng()
        .sample_iter(&Alphanumeric)
        .take(length)
        .map(char::from)
        .collect()
}

fn executable(name: &str) -> String {
    if cfg!(target_os = "windows") {
        format!("{name}.exe")
    } else {
        name.to_string()
    }
}

fn env_or(name: &str, default: &str) -> String {
    env::var(name).unwrap_or_else(|_| default.to_string())
}

fn ensure_port_free(port: u16, name: &str) -> Result<(), String> {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    if TcpStream::connect_timeout(&address, Duration::from_millis(150)).is_ok() {
        Err(format!(
            "{port}번 포트를 다른 프로세스가 사용 중이라 내장 {name}을 시작할 수 없습니다."
        ))
    } else {
        Ok(())
    }
}

fn wait_for_port(
    child: &mut Child,
    port: u16,
    name: &str,
    timeout: Duration,
) -> Result<(), String> {
    let attempts = timeout.as_millis() / 100;
    for _ in 0..attempts {
        if let Ok(Some(status)) = child.try_wait() {
            return Err(format!("내장 {name}이 시작 중 종료되었습니다 ({status})."));
        }
        let address = SocketAddr::from(([127, 0, 0, 1], port));
        if TcpStream::connect_timeout(&address, Duration::from_millis(100)).is_ok() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(100));
    }
    Err(format!("내장 {name}이 제한 시간 안에 준비되지 않았습니다."))
}

fn pipe_output(child: &mut Child, name: &'static str, logs: Arc<Mutex<VecDeque<String>>>) {
    if let Some(output) = child.stdout.take() {
        let logs = logs.clone();
        thread::spawn(move || {
            for line in BufReader::new(output).lines().map_while(Result::ok) {
                push_log(&logs, format!("[{name}] {line}"));
            }
        });
    }
    if let Some(output) = child.stderr.take() {
        thread::spawn(move || {
            for line in BufReader::new(output).lines().map_while(Result::ok) {
                push_log(&logs, format!("[{name}] {line}"));
            }
        });
    }
}

fn push_log(logs: &Arc<Mutex<VecDeque<String>>>, line: String) {
    if let Ok(mut values) = logs.lock() {
        if values.len() >= 1200 {
            values.pop_front();
        }
        values.push_back(line);
    }
}

fn log_output(logs: &Arc<Mutex<VecDeque<String>>>, name: &str, output: &Output) {
    for line in String::from_utf8_lossy(&output.stdout).lines() {
        push_log(logs, format!("[{name}] {line}"));
    }
    for line in String::from_utf8_lossy(&output.stderr).lines() {
        push_log(logs, format!("[{name}] {line}"));
    }
}

pub fn stop_child(child: &mut Option<Child>) {
    if let Some(mut process) = child.take() {
        #[cfg(unix)]
        unsafe {
            libc::kill(process.id() as i32, libc::SIGTERM);
        }
        #[cfg(not(unix))]
        let _ = process.kill();
        for _ in 0..30 {
            if matches!(process.try_wait(), Ok(Some(_))) {
                return;
            }
            thread::sleep(Duration::from_millis(100));
        }
        let _ = process.kill();
        let _ = process.wait();
    }
}

#[cfg(unix)]
fn set_private_permissions(path: &Path) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(path, fs::Permissions::from_mode(0o600)).map_err(|e| e.to_string())
}

#[cfg(not(unix))]
fn set_private_permissions(_path: &Path) -> Result<(), String> {
    Ok(())
}

#[cfg(unix)]
fn prepend_library_path(directory: &Path, variable: &str) -> std::ffi::OsString {
    let mut entries = vec![directory.to_path_buf()];
    if let Some(existing) = env::var_os(variable) {
        entries.extend(env::split_paths(&existing));
    }
    env::join_paths(entries).unwrap_or_else(|_| directory.as_os_str().to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn packaged_python_does_not_write_into_the_signed_bundle() {
        let runtime = StandaloneRuntime {
            runtime_root: PathBuf::from("/runtime"),
            data_root: PathBuf::from("/data"),
            postgres: PathBuf::from("postgres"),
            initdb: PathBuf::from("initdb"),
            createdb: PathBuf::from("createdb"),
            psql: PathBuf::from("psql"),
            redis: PathBuf::from("redis"),
            secrets: RuntimeSecrets {
                postgres_password: "test-only".into(),
                auth_jwt_secret: "test-only".into(),
                portal_sync_enc_key: "test-only".into(),
                mcp_auth_token: "test-only".into(),
            },
            ports: Mutex::new(RuntimePorts::default()),
        };
        let mut command = Command::new("python");
        runtime.configure_command(&mut command);
        assert!(command.get_envs().any(|(name, value)| {
            name == "PYTHONDONTWRITEBYTECODE" && value == Some(std::ffi::OsStr::new("1"))
        }));
    }

    #[test]
    fn generated_fernet_key_has_expected_shape() {
        let mut bytes = [0_u8; 32];
        rand::thread_rng().fill_bytes(&mut bytes);
        let key = URL_SAFE.encode(bytes);
        assert_eq!(key.len(), 44);
        assert!(key.ends_with('='));
    }

    #[test]
    fn selects_an_alternate_port_when_the_preferred_port_is_busy() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let occupied = listener.local_addr().unwrap().port();
        let range_start = if occupied < 65530 {
            occupied
        } else {
            occupied - 5
        };
        let range_end = range_start + 5;
        let selected = select_available_port(occupied, range_start, range_end, "test").unwrap();
        assert_ne!(selected, occupied);
        assert!((range_start..=range_end).contains(&selected));
    }
}
