use base64::{engine::general_purpose::URL_SAFE, Engine as _};
use rand::{distributions::Alphanumeric, Rng, RngCore};
use serde::{Deserialize, Serialize};
use std::{
    collections::VecDeque,
    env, fs,
    io::{BufRead, BufReader},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Output, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::Duration,
};

// Keep this distinct from Codmes Server's managed PostgreSQL port (55432) so
// both desktop managers can run on the same Mac.
pub const POSTGRES_PORT: u16 = 55433;
pub const REDIS_PORT: u16 = 56379;

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

    pub fn configure_command(&self, command: &mut Command) {
        let postgres_password = &self.secrets.postgres_password;
        command
            .env("RUNTIME_ENV", "local")
            .env(
                "DATABASE_URL",
                format!("postgresql://knu:{postgres_password}@127.0.0.1:{POSTGRES_PORT}/knu"),
            )
            .env("DB_HOST", "127.0.0.1")
            .env("DB_PORT", POSTGRES_PORT.to_string())
            .env("DB_NAME", "knu")
            .env("DB_USER", "knu")
            .env("DB_PASSWORD", postgres_password)
            // PostgreSQL CLI tools (psql/createdb) do not read DB_PASSWORD.
            // Pass their standard password variable for the first-run database
            // existence check and creation over the SCRAM-protected TCP socket.
            .env("PGPASSWORD", postgres_password)
            .env("REDIS_URL", format!("redis://127.0.0.1:{REDIS_PORT}"))
            .env("AUTH_JWT_SECRET", &self.secrets.auth_jwt_secret)
            .env("PORTAL_SYNC_ENC_KEY", &self.secrets.portal_sync_enc_key)
            .env("MCP_AUTH_TOKEN", &self.secrets.mcp_auth_token)
            .env("EMBEDDING_DIM", env_or("EMBEDDING_DIM", "1024"))
            .env("EMBEDDING_PROVIDER", env_or("EMBEDDING_PROVIDER", "local"))
            .env(
                "EMBEDDING_MODEL",
                env_or("EMBEDDING_MODEL", "bge-m3:latest"),
            )
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
            .env("MAIL_PROVIDER", env_or("MAIL_PROVIDER", "console"))
            .env(
                "NOTICE_POLL_ENABLED",
                env_or("NOTICE_POLL_ENABLED", "false"),
            )
            .env("DOCUMENT_ASSETS_ROOT", self.data_root.join("assets"))
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
        ensure_port_free(POSTGRES_PORT, "PostgreSQL")?;
        let mut command = Command::new(&self.postgres);
        self.configure_command(&mut command);
        let mut child = command
            .args([
                "-D",
                &data.to_string_lossy(),
                "-h",
                "127.0.0.1",
                "-p",
                &POSTGRES_PORT.to_string(),
                "-k",
                &self.data_root.join("postgres-socket").to_string_lossy(),
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("내장 PostgreSQL을 시작하지 못했습니다: {e}"))?;
        pipe_output(&mut child, "postgres", logs.clone());
        wait_for_port(
            &mut child,
            POSTGRES_PORT,
            "PostgreSQL",
            Duration::from_secs(15),
        )?;
        Ok(child)
    }

    fn ensure_database(&self, logs: &Arc<Mutex<VecDeque<String>>>) -> Result<(), String> {
        let mut check = Command::new(&self.psql);
        self.configure_command(&mut check);
        let output = check
            .args([
                "-h",
                "127.0.0.1",
                "-p",
                &POSTGRES_PORT.to_string(),
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
                &POSTGRES_PORT.to_string(),
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
        ensure_port_free(REDIS_PORT, "Redis")?;
        let data = self.data_root.join("redis");
        fs::create_dir_all(&data).map_err(|e| e.to_string())?;
        let mut command = Command::new(&self.redis);
        self.configure_command(&mut command);
        let mut child = command
            .args([
                "--bind",
                "127.0.0.1",
                "--port",
                &REDIS_PORT.to_string(),
                "--dir",
                &data.to_string_lossy(),
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
        wait_for_port(&mut child, REDIS_PORT, "Redis", Duration::from_secs(10))?;
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
    fn generated_fernet_key_has_expected_shape() {
        let mut bytes = [0_u8; 32];
        rand::thread_rng().fill_bytes(&mut bytes);
        let key = URL_SAFE.encode(bytes);
        assert_eq!(key.len(), 44);
        assert!(key.ends_with('='));
    }
}
