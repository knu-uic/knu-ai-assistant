use rand::{distributions::Alphanumeric, Rng};
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
    time::{Duration, Instant},
};
use tauri::{AppHandle, Manager};

use crate::standalone::{stop_child as stop_embedded_child, EmbeddedProcesses, StandaloneRuntime};

const MAX_LOGS: usize = 1200;
const DEVELOPMENT_API_PORT: u16 = 8000;

struct Processes {
    api: Option<Child>,
    worker: Option<Child>,
    postgres: Option<Child>,
    redis: Option<Child>,
}

#[derive(Deserialize, Serialize, Default)]
struct ManagedProcessIds {
    api: Option<u32>,
    worker: Option<u32>,
    postgres: Option<u32>,
    redis: Option<u32>,
}

impl ManagedProcessIds {
    fn from_processes(processes: &Processes) -> Self {
        Self {
            api: processes.api.as_ref().map(Child::id),
            worker: processes.worker.as_ref().map(Child::id),
            postgres: processes.postgres.as_ref().map(Child::id),
            redis: processes.redis.as_ref().map(Child::id),
        }
    }

    fn is_empty(&self) -> bool {
        self.api.is_none()
            && self.worker.is_none()
            && self.postgres.is_none()
            && self.redis.is_none()
    }
}

pub struct ManagerState {
    processes: Mutex<Processes>,
    logs: Arc<Mutex<VecDeque<String>>>,
    admin_token: String,
    root: PathBuf,
    python: PathBuf,
    preferences_path: PathBuf,
    runtime_settings_path: PathBuf,
    data_root: PathBuf,
    standalone: Option<StandaloneRuntime>,
    standalone_error: Option<String>,
    native_development: bool,
    show_dock_icon: Mutex<bool>,
    transfer_active: Mutex<bool>,
}

#[derive(Deserialize, Serialize, Default)]
#[serde(rename_all = "camelCase")]
struct ManagerPreferences {
    show_dock_icon: bool,
}

#[derive(Serialize)]
pub struct RuntimeStatus {
    running: bool,
    api_running: bool,
    worker_running: bool,
    url: String,
    admin_token: String,
    server_root: String,
    python_path: String,
    logs: Vec<String>,
    show_dock_icon: bool,
    deployment_mode: String,
    data_root: String,
    database_running: bool,
    redis_running: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NoticeTransferResult {
    path: String,
    #[serde(default)]
    safety_backup: Option<String>,
    notices: u64,
    assets: u64,
    chunks: u64,
    datasets: u64,
}

fn find_repo_root() -> PathBuf {
    if let Ok(value) = env::var("KNU_SERVER_ROOT") {
        return PathBuf::from(value);
    }
    let current = env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    repo_root_from(&current).unwrap_or(current)
}

fn repo_root_from(start: &Path) -> Option<PathBuf> {
    start
        .ancestors()
        .find(|path| path.join("server/api/api/main.py").is_file())
        .map(Path::to_path_buf)
}

fn python_for(root: &Path, packaged: bool) -> PathBuf {
    if let Ok(value) = env::var("KNU_PYTHON_PATH") {
        return PathBuf::from(value);
    }
    #[cfg(target_os = "windows")]
    let candidate = root.join(if packaged {
        ".knu-runtime/python.exe"
    } else {
        ".venv/Scripts/python.exe"
    });
    #[cfg(not(target_os = "windows"))]
    let candidate = root.join(if packaged {
        ".knu-runtime/bin/python"
    } else {
        ".venv/bin/python"
    });
    if candidate.exists() {
        candidate
    } else {
        PathBuf::from("python3")
    }
}

fn push_log(logs: &Arc<Mutex<VecDeque<String>>>, line: String) {
    if let Ok(mut values) = logs.lock() {
        if values.len() >= MAX_LOGS {
            values.pop_front();
        }
        values.push_back(line);
    }
}

fn pipe_output(child: &mut Child, name: &'static str, logs: Arc<Mutex<VecDeque<String>>>) {
    if let Some(output) = child.stdout.take() {
        let logs = logs.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(output).lines().map_while(Result::ok) {
                push_log(&logs, format!("[{name}] {line}"));
            }
        });
    }
    if let Some(output) = child.stderr.take() {
        std::thread::spawn(move || {
            for line in BufReader::new(output).lines().map_while(Result::ok) {
                push_log(&logs, format!("[{name}] {line}"));
            }
        });
    }
}

impl ManagerState {
    pub fn new(app: &AppHandle) -> Self {
        let repo = find_repo_root();
        let development = if cfg!(debug_assertions)
            && env::var_os("KNU_EMBEDDED_RUNTIME_ROOT").is_none()
            && env::var("KNU_LEGACY_DEV").as_deref() != Ok("1")
        {
            crate::development::load(&repo).and_then(|config| config
                .map(Some)
                .ok_or_else(|| "독립 개발 환경이 준비되지 않았습니다. server/manager에서 npm run setup:dev를 실행하세요.".to_string()))
        } else {
            Ok(None)
        };
        let development_error = development.as_ref().err().cloned();
        let development = development.ok().flatten();
        // Invalid setup must not silently use system Python/production settings.
        let native_development = development.is_some() || development_error.is_some();
        let configured_runtime = env::var("KNU_EMBEDDED_RUNTIME_ROOT")
            .ok()
            .map(PathBuf::from);
        let packaged_runtime = if !cfg!(debug_assertions) {
            app.path()
                .resource_dir()
                .ok()
                .map(|path| path.join("runtime"))
        } else {
            None
        };
        let runtime_root = development
            .as_ref()
            .map(|config| config.runtime_root.clone())
            .or(configured_runtime)
            .or(packaged_runtime);
        let packaged = runtime_root.is_some();
        let root = if native_development {
            repo.clone()
        } else {
            runtime_root
                .as_ref()
                .map(|path| path.join("knu"))
                .unwrap_or(repo.clone())
        };
        let python = development
            .as_ref()
            .map(|config| config.python_path.clone())
            .unwrap_or_else(|| python_for(&root, packaged));
        let data_root = if native_development {
            crate::development::data_root(&repo)
        } else {
            env::var("KNU_DATA_ROOT")
                .map(PathBuf::from)
                .unwrap_or_else(|_| {
                    app.path()
                        .app_data_dir()
                        .unwrap_or_else(|_| root.join(".knu-server-manager/data"))
                })
        };
        let preferences_path = if native_development {
            data_root.join("config/manager.json")
        } else {
            app.path()
                .app_config_dir()
                .unwrap_or_else(|_| data_root.join("config"))
                .join("manager.json")
        };
        let preferences = fs::read_to_string(&preferences_path)
            .ok()
            .and_then(|value| serde_json::from_str::<ManagerPreferences>(&value).ok())
            .unwrap_or_default();
        let runtime_settings_path = preferences_path
            .parent()
            .unwrap_or(&root)
            .join("runtime-settings.json");
        // 이전 개발 버전이 소스 아래 JSON을 새 앱 영구 설정으로 한 번만 이전한다.
        if !native_development && !runtime_settings_path.exists() {
            let legacy_path = root.join("server/api/data/server-manager.json");
            if legacy_path.exists() {
                if let Some(parent) = runtime_settings_path.parent() {
                    let _ = fs::create_dir_all(parent);
                }
                let _ = fs::copy(legacy_path, &runtime_settings_path);
            }
        }
        let (standalone, standalone_error) = if let Some(error) = development_error {
            (None, Some(error))
        } else if let Some(runtime_root) = runtime_root {
            match StandaloneRuntime::discover(runtime_root, data_root.clone()) {
                Ok(runtime) => (Some(runtime), None),
                Err(error) => (None, Some(error)),
            }
        } else {
            (None, None)
        };
        let logs = Arc::new(Mutex::new(VecDeque::new()));
        recover_orphaned_processes(&data_root, &logs);
        Self {
            processes: Mutex::new(Processes {
                api: None,
                worker: None,
                postgres: None,
                redis: None,
            }),
            logs,
            admin_token: env::var("KNU_ADMIN_TOKEN").unwrap_or_else(|_| {
                rand::thread_rng()
                    .sample_iter(&Alphanumeric)
                    .take(48)
                    .map(char::from)
                    .collect()
            }),
            python,
            root,
            preferences_path,
            runtime_settings_path,
            data_root,
            standalone,
            standalone_error,
            native_development,
            show_dock_icon: Mutex::new(preferences.show_dock_icon),
            transfer_active: Mutex::new(false),
        }
    }

    fn set_show_dock_icon(&self, show: bool) -> Result<(), String> {
        if let Some(parent) = self.preferences_path.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        fs::write(
            &self.preferences_path,
            serde_json::to_vec_pretty(&ManagerPreferences {
                show_dock_icon: show,
            })
            .map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())?;
        *self
            .show_dock_icon
            .lock()
            .map_err(|_| "preference lock failed")? = show;
        Ok(())
    }

    pub fn show_dock_icon(&self) -> bool {
        self.show_dock_icon
            .lock()
            .map(|value| *value)
            .unwrap_or(false)
    }

    fn persist_process_ids(&self, processes: &Processes) {
        let path = managed_process_path(&self.data_root);
        let ids = ManagedProcessIds::from_processes(processes);
        if ids.is_empty() {
            let _ = fs::remove_file(path);
            return;
        }
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        let temporary = path.with_extension("json.tmp");
        if let Ok(value) = serde_json::to_vec_pretty(&ids) {
            if fs::write(&temporary, value).is_ok() {
                let _ = fs::rename(temporary, path);
            }
        }
    }
}

impl Drop for ManagerState {
    fn drop(&mut self) {
        if let Ok(mut processes) = self.processes.lock() {
            stop_child(&mut processes.worker);
            stop_child(&mut processes.api);
            stop_embedded_child(&mut processes.redis);
            stop_embedded_child(&mut processes.postgres);
            self.persist_process_ids(&processes);
        }
    }
}

fn managed_process_path(data_root: &Path) -> PathBuf {
    data_root.join("config/managed-processes.json")
}

fn recover_orphaned_processes(data_root: &Path, logs: &Arc<Mutex<VecDeque<String>>>) {
    let path = managed_process_path(data_root);
    let Ok(raw) = fs::read(&path) else {
        return;
    };
    let Ok(ids) = serde_json::from_slice::<ManagedProcessIds>(&raw) else {
        push_log(
            logs,
            "[manager] ignored an unreadable managed process record".into(),
        );
        return;
    };
    let mut recovered = 0;
    for (role, pid) in [
        ("worker", ids.worker),
        ("api", ids.api),
        ("redis", ids.redis),
        ("postgres", ids.postgres),
    ] {
        if let Some(pid) = pid {
            if terminate_orphaned_process(pid, role, data_root) {
                recovered += 1;
            }
        }
    }
    let _ = fs::remove_file(path);
    if recovered > 0 {
        push_log(
            logs,
            format!("[manager] stopped {recovered} orphaned managed processes"),
        );
    }
}

#[cfg(unix)]
fn terminate_orphaned_process(pid: u32, role: &str, data_root: &Path) -> bool {
    let output = Command::new("ps")
        .args(["-p", &pid.to_string(), "-o", "command="])
        .output();
    let Ok(output) = output else {
        return false;
    };
    let command = String::from_utf8_lossy(&output.stdout);
    if !managed_command_matches(role, &command, data_root) {
        return false;
    }
    unsafe {
        libc::kill(pid as i32, libc::SIGTERM);
    }
    for _ in 0..30 {
        let running = unsafe { libc::kill(pid as i32, 0) == 0 };
        if !running {
            return true;
        }
        thread::sleep(Duration::from_millis(100));
    }
    unsafe {
        libc::kill(pid as i32, libc::SIGKILL);
    }
    true
}

#[cfg(not(unix))]
fn terminate_orphaned_process(_pid: u32, _role: &str, _data_root: &Path) -> bool {
    false
}

fn managed_command_matches(role: &str, command: &str, data_root: &Path) -> bool {
    match role {
        "worker" => command.contains("arq") && command.contains("workers.arq_worker"),
        "api" => command.contains("uvicorn") && command.contains("api.main:app"),
        "redis" => {
            command.contains("redis-server")
                && command.contains(&data_root.join("redis").to_string_lossy().to_string())
        }
        "postgres" => {
            command.contains("postgres")
                && command.contains(&data_root.join("postgres").to_string_lossy().to_string())
        }
        _ => false,
    }
}

fn cleanup_interrupted_crawl(state: &ManagerState) {
    let api_root = state.root.join("server/api");
    let mut command = Command::new(&state.python);
    if let Some(runtime) = &state.standalone {
        runtime.configure_command(&mut command);
    }
    command
        .args([
            "-c",
            "from workers.crawl_control import cleanup_interrupted_crawl; print(cleanup_interrupted_crawl())",
        ])
        .current_dir(api_root)
        .env("KNU_MANAGER_SETTINGS_PATH", &state.runtime_settings_path)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    match output_with_timeout(&mut command, Duration::from_secs(5)) {
        Ok(output) if output.status.success() => push_log(
            &state.logs,
            format!(
                "[manager] recovered interrupted crawl and cleared {} transient entries",
                String::from_utf8_lossy(&output.stdout).trim()
            ),
        ),
        Ok(output) => push_log(
            &state.logs,
            format!(
                "[manager] crawl state cleanup failed: {}",
                String::from_utf8_lossy(&output.stderr).trim()
            ),
        ),
        Err(error) => push_log(
            &state.logs,
            format!("[manager] crawl state cleanup skipped: {error}"),
        ),
    }
}

fn output_with_timeout(command: &mut Command, timeout: Duration) -> Result<Output, String> {
    let mut child = command.spawn().map_err(|error| error.to_string())?;
    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => return child.wait_with_output().map_err(|error| error.to_string()),
            Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(50)),
            Ok(None) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!(
                    "{}초 안에 완료되지 않아 중단했습니다.",
                    timeout.as_secs()
                ));
            }
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error.to_string());
            }
        }
    }
}

fn child_running(child: &mut Option<Child>) -> bool {
    match child {
        Some(process) => match process.try_wait() {
            Ok(None) => true,
            _ => {
                *child = None;
                false
            }
        },
        None => false,
    }
}

fn api_is_listening(port: u16) -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&address, Duration::from_millis(150)).is_ok()
}

fn wait_for_api(child: &mut Child, port: u16) -> Result<(), String> {
    // Fresh portable environments need time for their first heavy imports.
    // Poll readiness instead of sleeping for the whole startup allowance.
    let deadline = Instant::now() + Duration::from_secs(60);
    while Instant::now() < deadline {
        if let Ok(Some(status)) = child.try_wait() {
            return Err(format!(
                "KNU API가 시작 중 종료되었습니다 ({status}). 서버 로그를 확인하세요."
            ));
        }
        if api_is_listening(port) {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(100));
    }
    Err("KNU API가 60초 안에 준비되지 않았습니다. 서버 로그를 확인하세요.".into())
}

#[tauri::command]
pub fn runtime_status(state: tauri::State<ManagerState>) -> RuntimeStatus {
    let api_port = state
        .standalone
        .as_ref()
        .map(|runtime| runtime.ports().api)
        .unwrap_or(DEVELOPMENT_API_PORT);
    let (api_running, worker_running, database_running, redis_running) =
        if let Ok(mut p) = state.processes.lock() {
            (
                child_running(&mut p.api),
                child_running(&mut p.worker),
                child_running(&mut p.postgres),
                child_running(&mut p.redis),
            )
        } else {
            (false, false, false, false)
        };
    RuntimeStatus {
        running: api_running
            && worker_running
            && (state.standalone.is_none() || (database_running && redis_running)),
        api_running,
        worker_running,
        url: format!("http://127.0.0.1:{api_port}"),
        admin_token: state.admin_token.clone(),
        server_root: state.root.display().to_string(),
        python_path: state.python.display().to_string(),
        logs: state
            .logs
            .lock()
            .map(|v| v.iter().cloned().collect())
            .unwrap_or_default(),
        show_dock_icon: state.show_dock_icon(),
        deployment_mode: if state.native_development {
            "native-development".into()
        } else if state.standalone.is_some() || state.standalone_error.is_some() {
            "standalone".into()
        } else {
            "development".into()
        },
        data_root: state.data_root.display().to_string(),
        database_running,
        redis_running,
    }
}

pub fn apply_dock_policy(app: &AppHandle, show: bool) {
    #[cfg(target_os = "macos")]
    {
        let policy = if show {
            tauri::ActivationPolicy::Regular
        } else {
            tauri::ActivationPolicy::Accessory
        };
        let _ = app.set_activation_policy(policy);
    }
    #[cfg(not(target_os = "macos"))]
    let _ = (app, show);
}

#[tauri::command]
pub fn set_show_dock_icon(
    app: AppHandle,
    state: tauri::State<ManagerState>,
    show: bool,
) -> Result<(), String> {
    state.set_show_dock_icon(show)?;
    apply_dock_policy(&app, show);
    Ok(())
}

fn spawn_python(state: &ManagerState, args: &[&str], name: &'static str) -> Result<Child, String> {
    let api_root = state.root.join("server/api");
    if !api_root.join("api/main.py").exists() {
        return Err(format!(
            "KNU server source not found: {}",
            api_root.display()
        ));
    }
    let mut command = Command::new(&state.python);
    if let Some(runtime) = &state.standalone {
        runtime.configure_command(&mut command);
    }
    let mut child = command
        .args(args)
        .current_dir(api_root)
        .env("KNU_ADMIN_TOKEN", &state.admin_token)
        .env("KNU_MANAGER_SETTINGS_PATH", &state.runtime_settings_path)
        // 설치형 WebView와 `tauri dev`의 Vite origin을 모두 허용한다.
        // 개발 origin이 빠지면 API가 정상이어도 WebView에서
        // `TypeError: Load failed`로만 보인다.
        .env(
            "WEB_CORS_ORIGINS",
            "tauri://localhost,http://tauri.localhost,http://localhost:1421,http://127.0.0.1:1421",
        )
        .env("PYTHONUNBUFFERED", "1")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("{name} start failed: {e}"))?;
    pipe_output(&mut child, name, state.logs.clone());
    Ok(child)
}

fn migrate_database(state: &ManagerState) -> Result<(), String> {
    let api_root = state.root.join("server/api");
    let mut command = Command::new(&state.python);
    if let Some(runtime) = &state.standalone {
        runtime.configure_command(&mut command);
    }
    let output = command
        .args(["-c", "from db.schema import init_db; init_db()"])
        .current_dir(api_root)
        .env("KNU_MANAGER_SETTINGS_PATH", &state.runtime_settings_path)
        .output()
        .map_err(|error| format!("database migration could not start: {error}"))?;
    for line in String::from_utf8_lossy(&output.stdout).lines() {
        push_log(&state.logs, format!("[migration] {line}"));
    }
    if !output.status.success() {
        let detail = String::from_utf8_lossy(&output.stderr);
        return Err(format!(
            "PostgreSQL migration failed. Check database settings.\n{detail}"
        ));
    }
    Ok(())
}

fn notice_transfer_path(state: &ManagerState) -> PathBuf {
    state.root.join("server/api/tools/notice_transfer.py")
}

fn run_notice_transfer(
    state: &ManagerState,
    mode: &str,
    path: &Path,
) -> Result<NoticeTransferResult, String> {
    let script = notice_transfer_path(state);
    if !script.is_file() {
        return Err(format!(
            "공지 데이터 전송 도구를 찾을 수 없습니다: {}",
            script.display()
        ));
    }
    let api_root = state.root.join("server/api");
    let mut command = Command::new(&state.python);
    if let Some(runtime) = &state.standalone {
        runtime.configure_command(&mut command);
    }
    let output = command
        .arg(script)
        .arg(mode)
        .arg(path)
        .current_dir(api_root)
        .env("KNU_MANAGER_SETTINGS_PATH", &state.runtime_settings_path)
        .output()
        .map_err(|error| format!("공지 데이터 {mode} 작업을 시작하지 못했습니다: {error}"))?;
    for line in String::from_utf8_lossy(&output.stderr).lines() {
        push_log(&state.logs, format!("[notice-{mode}] {line}"));
    }
    if !output.status.success() {
        let detail = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if detail.is_empty() {
            format!("공지 데이터 {mode} 작업에 실패했습니다.")
        } else {
            format!("공지 데이터 {mode} 작업에 실패했습니다.\n{detail}")
        });
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    let payload = stdout
        .lines()
        .rev()
        .find(|line| !line.trim().is_empty())
        .ok_or_else(|| "공지 데이터 전송 결과가 비어 있습니다.".to_string())?;
    serde_json::from_str(payload)
        .map_err(|error| format!("공지 데이터 전송 결과를 읽지 못했습니다: {error}"))
}

fn transfer_notices(
    state: &ManagerState,
    mode: &str,
    path: &Path,
) -> Result<NoticeTransferResult, String> {
    {
        let mut active = state
            .transfer_active
            .lock()
            .map_err(|_| "공지 데이터 작업 상태를 확인하지 못했습니다.")?;
        if *active {
            return Err("이미 공지 데이터 가져오기 또는 내보내기가 진행 중입니다.".into());
        }
        *active = true;
    }

    let operation = (|| {
        let should_restart = {
            let mut processes = state
                .processes
                .lock()
                .map_err(|_| "process state lock failed")?;
            let api_running = child_running(&mut processes.api);
            let worker_running = child_running(&mut processes.worker);
            let database_running = child_running(&mut processes.postgres);
            if !api_running || (state.standalone.is_some() && !database_running) {
                return Err("서버를 먼저 실행한 뒤 공지 데이터를 전송하세요.".into());
            }
            stop_child(&mut processes.worker);
            if mode == "import" {
                stop_child(&mut processes.api);
            }
            state.persist_process_ids(&processes);
            api_running || worker_running
        };

        let result = run_notice_transfer(state, mode, path);
        let restart = if should_restart {
            start_managed_server(state)
        } else {
            Ok(())
        };
        match (result, restart) {
            (Ok(value), Ok(())) => Ok(value),
            (Err(error), Ok(())) => Err(error),
            (Ok(_), Err(restart_error)) => Err(format!(
                "공지 데이터 작업은 완료됐지만 서버를 다시 시작하지 못했습니다: {restart_error}"
            )),
            (Err(error), Err(restart_error)) => Err(format!(
                "{error}\n서버도 다시 시작하지 못했습니다: {restart_error}"
            )),
        }
    })();

    if let Ok(mut active) = state.transfer_active.lock() {
        *active = false;
    }
    operation
}

#[tauri::command]
pub fn export_notice_data(
    state: tauri::State<ManagerState>,
) -> Result<Option<NoticeTransferResult>, String> {
    let Some(mut path) = rfd::FileDialog::new()
        .add_filter("KNU 공지 데이터", &["knudata"])
        .set_file_name("KNU-Notices.knudata")
        .save_file()
    else {
        return Ok(None);
    };
    if path.extension().and_then(|value| value.to_str()) != Some("knudata") {
        path.set_extension("knudata");
    }
    transfer_notices(state.inner(), "export", &path).map(Some)
}

#[tauri::command]
pub fn import_notice_data(
    state: tauri::State<ManagerState>,
) -> Result<Option<NoticeTransferResult>, String> {
    let Some(path) = rfd::FileDialog::new()
        .add_filter("KNU 공지 데이터", &["knudata"])
        .pick_file()
    else {
        return Ok(None);
    };
    transfer_notices(state.inner(), "import", &path).map(Some)
}

#[tauri::command]
pub fn start_server(state: tauri::State<ManagerState>) -> Result<(), String> {
    start_managed_server(state.inner())
}

pub(crate) fn start_managed_server(state: &ManagerState) -> Result<(), String> {
    if state.native_development {
        let config = crate::development::load(&state.root)?
            .ok_or("개발 실행 환경 설정이 없어졌습니다. npm run setup:dev를 실행하세요.")?;
        if config.python_path != state.python {
            return Err(
                "개발 실행 도구가 변경되었습니다. Manager 개발 앱을 다시 실행하세요.".into(),
            );
        }
    }
    let mut p = state
        .processes
        .lock()
        .map_err(|_| "process state lock failed")?;
    if !state.python.exists() && state.python.components().count() > 1 {
        return Err(format!(
            "Python runtime not found: {}",
            state.python.display()
        ));
    }
    if let Some(error) = &state.standalone_error {
        return Err(format!("독립 실행 런타임이 올바르지 않습니다: {error}"));
    }
    if let Some(runtime) = &state.standalone {
        if !child_running(&mut p.postgres) || !child_running(&mut p.redis) {
            stop_embedded_child(&mut p.redis);
            stop_embedded_child(&mut p.postgres);
            let EmbeddedProcesses { postgres, redis } = runtime.start(&state.logs)?;
            p.postgres = postgres;
            p.redis = redis;
            state.persist_process_ids(&p);
            push_log(
                &state.logs,
                format!(
                    "[manager] standalone data root: {}",
                    runtime.data_root().display()
                ),
            );
        }
    }
    if let Err(error) = migrate_database(state) {
        if state.standalone.is_some() {
            stop_embedded_child(&mut p.redis);
            stop_embedded_child(&mut p.postgres);
            state.persist_process_ids(&p);
        }
        return Err(error);
    }
    if !child_running(&mut p.api) {
        let api_port = if let Some(runtime) = &state.standalone {
            runtime.prepare_api_port(&state.logs)?
        } else {
            DEVELOPMENT_API_PORT
        };
        if api_is_listening(api_port) {
            if state.standalone.is_some() {
                stop_embedded_child(&mut p.redis);
                stop_embedded_child(&mut p.postgres);
                state.persist_process_ids(&p);
            }
            return Err(format!(
                "{api_port}번 포트에서 다른 서비스가 이미 실행 중입니다."
            ));
        }
        let api_port_string = api_port.to_string();
        #[allow(unused_mut)] // Only Windows appends its compatible event loop.
        let mut api_args = vec![
            "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", &api_port_string,
        ];
        // Psycopg needs add_reader(), while the Node context bridge needs
        // subprocess pipes. Windows' default Proactor/Selector loops each lack
        // one of these; Winloop supports both without changing the engine.
        #[cfg(target_os = "windows")]
        api_args.extend(["--loop", "winloop:new_event_loop"]);
        let api = spawn_python(
            state,
            &api_args,
            "api",
        )?;
        p.api = Some(api);
        state.persist_process_ids(&p);
        let api_ready = p
            .api
            .as_mut()
            .ok_or_else(|| "KNU API process was not recorded".to_string())
            .and_then(|child| wait_for_api(child, api_port));
        if let Err(error) = api_ready {
            stop_child(&mut p.api);
            if state.standalone.is_some() {
                stop_embedded_child(&mut p.redis);
                stop_embedded_child(&mut p.postgres);
            }
            state.persist_process_ids(&p);
            return Err(error);
        }
    }
    if !child_running(&mut p.worker) {
        // Redis is persistent, so a manager crash can leave ARQ's in-progress
        // marker and the crawl lock behind. No manager-owned worker is alive at
        // this point; clear only that transient job state before replacement.
        cleanup_interrupted_crawl(state);
        match spawn_python(
            state,
            &["-m", "arq", "workers.arq_worker.WorkerSettings"],
            "worker",
        ) {
            Ok(child) => {
                p.worker = Some(child);
                state.persist_process_ids(&p);
            }
            Err(error) => {
                if let Some(mut api) = p.api.take() {
                    let _ = api.kill();
                }
                if state.standalone.is_some() {
                    stop_embedded_child(&mut p.redis);
                    stop_embedded_child(&mut p.postgres);
                }
                state.persist_process_ids(&p);
                return Err(error);
            }
        }
    }
    push_log(
        &state.logs,
        "[manager] API and crawler worker started".into(),
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    /// Explicit opt-in: only a fresh temporary DB is touched. This exercises
    /// the same Manager start/stop functions used by the desktop UI.
    #[test]
    #[ignore = "requires npm run setup:dev and a matching native runtime"]
    fn native_development_smoke_with_fresh_data_and_live_source() {
        let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let root = manifest.ancestors().nth(3).unwrap().to_path_buf();
        let config = crate::development::load(&root)
            .unwrap()
            .expect("Run npm run setup:dev first");
        let data = env::temp_dir().join(format!("knu-native-smoke-{}", rand::random::<u64>()));
        fs::create_dir_all(&data).unwrap();
        let state = ManagerState {
            processes: Mutex::new(Processes {
                api: None,
                worker: None,
                postgres: None,
                redis: None,
            }),
            logs: Arc::new(Mutex::new(VecDeque::new())),
            admin_token: "native-smoke-test-only".into(),
            root: root.clone(),
            python: config.python_path,
            preferences_path: data.join("config/manager.json"),
            runtime_settings_path: data.join("config/runtime-settings.json"),
            standalone: Some(
                StandaloneRuntime::discover(config.runtime_root, data.clone()).unwrap(),
            ),
            data_root: data.clone(),
            standalone_error: None,
            native_development: true,
            show_dock_icon: Mutex::new(false),
            transfer_active: Mutex::new(false),
        };
        // No automatic crawling, models or user credentials are needed.
        fs::write(
            &state.runtime_settings_path,
            r#"{"auto_crawl_enabled":false}"#,
        )
        .unwrap();
        let result = (|| -> Result<(), String> {
            start_managed_server(&state)?;
            let runtime = state.standalone.as_ref().unwrap();
            let port = runtime.ports().api;
            let mut command = Command::new(&state.python);
            runtime.configure_command(&mut command);
            let probe = command.current_dir(root.join("server/api"))
                .args(["-B", "-c", &format!(
                    r#"import asyncio, json, os, pathlib, sys, time, urllib.request
import api.main
import psycopg
import redis
from db.schema import DB_URL
from api.context_engine import estimate_request
assert pathlib.Path(api.main.__file__).resolve() == pathlib.Path('api/main.py').resolve()
assert '.venv' not in sys.executable
base = 'http://127.0.0.1:{port}'
health = json.load(urllib.request.urlopen(base + '/api/health', timeout=10))
print('Health:', health)
request = urllib.request.Request(base + '/api/admin/status', headers={{'Authorization': 'Bearer native-smoke-test-only'}})
status = json.load(urllib.request.urlopen(request, timeout=15))
assert status['status'] == 'ok'
assert status['notice_count'] == status['account_count'] == status['review_count'] == 0
print('ASYNC_DATABASE_QUERY_OK')
with psycopg.connect(DB_URL) as connection:
    assert connection.execute('SELECT count(*) FROM schema_migrations').fetchone()[0] >= 19
    assert connection.execute('SELECT count(*) FROM users').fetchone()[0] == 0
    assert connection.execute('SELECT count(*) FROM content').fetchone()[0] == 0
loop_factory = asyncio.new_event_loop
if sys.platform == 'win32':
    import winloop
    loop_factory = winloop.new_event_loop
with asyncio.Runner(loop_factory=loop_factory) as runner:
    estimate = runner.run(estimate_request([{{'role': 'user', 'content': '테스트'}}], 'mock', 8000))
assert estimate['tokens'] > 0 and estimate['budget']['inputBudget'] > 0
print('ASYNC_NODE_CONTEXT_ENGINE_OK')
client = redis.Redis.from_url(os.environ['REDIS_URL'], socket_timeout=5)
deadline = time.monotonic() + 30
while not client.get('arq:queue:health-check') and time.monotonic() < deadline:
    time.sleep(0.1)
assert client.get('arq:queue:health-check'), 'Worker health check was not ready'
print('LIVE_SOURCE_AND_FRESH_DATABASE_AND_WORKER_OK')
"#
                )]).output().map_err(|error| error.to_string())?;
            if !probe.status.success() {
                return Err(String::from_utf8_lossy(&probe.stderr).into_owned());
            }
            println!("{}", String::from_utf8_lossy(&probe.stdout));
            Ok(())
        })();
        let stop = shutdown_managed_server(&state);
        if let Err(error) = &result {
            eprintln!("Smoke failure: {error}");
            for line in state.logs.lock().unwrap().iter() {
                eprintln!("{line}");
            }
        }
        assert!(stop.is_ok());
        // Temporary smoke DB only; never the installed app or .dev/data DB.
        fs::remove_dir_all(&data).unwrap();
        result.unwrap();
    }

    #[test]
    fn locates_client_server_repository_from_manager_and_mobile() {
        let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
        let root = manifest.ancestors().nth(3).unwrap().to_path_buf();
        assert_eq!(repo_root_from(&manifest), Some(root.clone()));
        assert_eq!(repo_root_from(&root.join("client/mobile")), Some(root));
    }

    #[test]
    fn does_not_accept_a_directory_without_the_api_entry() {
        let unrelated = env::temp_dir().join(format!("knu-missing-root-{}", rand::random::<u64>()));
        assert_eq!(repo_root_from(&unrelated), None);
    }

    #[test]
    fn detects_a_listening_tcp_socket() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        assert!(TcpStream::connect_timeout(&address, Duration::from_millis(100)).is_ok());
    }

    #[test]
    fn orphan_recovery_only_matches_manager_owned_commands() {
        let data_root = PathBuf::from("/tmp/KNU Server Manager data");
        assert!(managed_command_matches(
            "postgres",
            &format!("postgres -D {} -p 55433", data_root.join("postgres").display()),
            &data_root,
        ));
        assert!(managed_command_matches(
            "worker",
            "python -m arq workers.arq_worker.WorkerSettings",
            &data_root,
        ));
        assert!(!managed_command_matches(
            "postgres",
            "/opt/postgres -D /tmp/unrelated -p 55433",
            &data_root,
        ));
        assert!(!managed_command_matches(
            "api",
            "python -m uvicorn another.main:app --port 8000",
            &data_root,
        ));
    }
}

fn stop_child(child: &mut Option<Child>) {
    if let Some(mut process) = child.take() {
        let _ = process.kill();
        let _ = process.wait();
    }
}

#[tauri::command]
pub fn stop_server(state: tauri::State<ManagerState>) -> Result<(), String> {
    stop_managed_server(state.inner(), true)
}

pub(crate) fn shutdown_managed_server(state: &ManagerState) -> Result<(), String> {
    stop_managed_server(state, false)
}

fn stop_managed_server(state: &ManagerState, cleanup_crawl: bool) -> Result<(), String> {
    let mut p = state
        .processes
        .lock()
        .map_err(|_| "process state lock failed")?;
    let had_managed_process = child_running(&mut p.worker)
        || child_running(&mut p.api)
        || child_running(&mut p.redis)
        || child_running(&mut p.postgres);
    stop_child(&mut p.worker);
    if cleanup_crawl && had_managed_process {
        cleanup_interrupted_crawl(state);
    }
    stop_child(&mut p.api);
    stop_embedded_child(&mut p.redis);
    stop_embedded_child(&mut p.postgres);
    state.persist_process_ids(&p);
    push_log(&state.logs, "[manager] server stopped".into());
    Ok(())
}

#[tauri::command]
pub fn clear_logs(state: tauri::State<ManagerState>) {
    if let Ok(mut logs) = state.logs.lock() {
        logs.clear();
    }
}

#[tauri::command]
pub fn open_auth_url(url: String) -> Result<(), String> {
    if url != "https://auth.openai.com/codex/device" {
        return Err("허용되지 않은 인증 주소입니다.".into());
    }
    open_web_url(&url)
}

#[tauri::command]
pub fn open_external_url(url: String) -> Result<(), String> {
    if !(url.starts_with("https://") || url.starts_with("http://"))
        || url.contains(['\r', '\n'])
        || url.len() > 4096
    {
        return Err("허용되지 않은 외부 주소입니다.".into());
    }
    open_web_url(&url)
}

fn open_web_url(url: &str) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    let status = Command::new("open").arg(url).status();
    #[cfg(target_os = "windows")]
    let status = Command::new("explorer.exe").arg(url).status();
    #[cfg(target_os = "linux")]
    let status = Command::new("xdg-open").arg(url).status();
    status
        .map_err(|error| format!("외부 창을 열지 못했습니다: {error}"))?
        .success()
        .then_some(())
        .ok_or_else(|| "외부 창을 열지 못했습니다.".into())
}
