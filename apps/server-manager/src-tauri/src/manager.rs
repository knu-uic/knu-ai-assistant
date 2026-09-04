use rand::{distributions::Alphanumeric, Rng};
use serde::{Deserialize, Serialize};
use std::{
    collections::VecDeque,
    env,
    fs,
    io::{BufRead, BufReader},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::Duration,
};
use tauri::{AppHandle, Manager};

const MAX_LOGS: usize = 1200;
const API_ADDRESS: &str = "127.0.0.1:8000";

struct Processes {
    api: Option<Child>,
    worker: Option<Child>,
}

pub struct ManagerState {
    processes: Mutex<Processes>,
    logs: Arc<Mutex<VecDeque<String>>>,
    admin_token: String,
    root: PathBuf,
    python: PathBuf,
    preferences_path: PathBuf,
    runtime_settings_path: PathBuf,
    show_dock_icon: Mutex<bool>,
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
}

fn find_repo_root() -> PathBuf {
    if let Ok(value) = env::var("KNU_SERVER_ROOT") {
        return PathBuf::from(value);
    }
    let mut path = env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    loop {
        if path.join("services/api/api/main.py").exists() {
            return path;
        }
        if !path.pop() {
            break;
        }
    }
    env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

fn python_for(root: &Path) -> PathBuf {
    if let Ok(value) = env::var("KNU_PYTHON_PATH") {
        return PathBuf::from(value);
    }
    #[cfg(target_os = "windows")]
    let candidate = root.join(".venv/Scripts/python.exe");
    #[cfg(not(target_os = "windows"))]
    let candidate = root.join(".venv/bin/python");
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
        let root = find_repo_root();
        let preferences_path = app
            .path()
            .app_config_dir()
            .unwrap_or_else(|_| root.join(".knu-server-manager"))
            .join("manager.json");
        let preferences = fs::read_to_string(&preferences_path)
            .ok()
            .and_then(|value| serde_json::from_str::<ManagerPreferences>(&value).ok())
            .unwrap_or_default();
        let runtime_settings_path = preferences_path
            .parent()
            .unwrap_or(&root)
            .join("runtime-settings.json");
        // 이전 개발 버전이 소스 아래 JSON을 새 앱 영구 설정으로 한 번만 이전한다.
        if !runtime_settings_path.exists() {
            let legacy_path = root.join("services/api/data/server-manager.json");
            if legacy_path.exists() {
                if let Some(parent) = runtime_settings_path.parent() {
                    let _ = fs::create_dir_all(parent);
                }
                let _ = fs::copy(legacy_path, &runtime_settings_path);
            }
        }
        Self {
            processes: Mutex::new(Processes {
                api: None,
                worker: None,
            }),
            logs: Arc::new(Mutex::new(VecDeque::new())),
            admin_token: env::var("KNU_ADMIN_TOKEN").unwrap_or_else(|_| {
                rand::thread_rng()
                    .sample_iter(&Alphanumeric)
                    .take(48)
                    .map(char::from)
                    .collect()
            }),
            python: python_for(&root),
            root,
            preferences_path,
            runtime_settings_path,
            show_dock_icon: Mutex::new(preferences.show_dock_icon),
        }
    }

    fn set_show_dock_icon(&self, show: bool) -> Result<(), String> {
        if let Some(parent) = self.preferences_path.parent() {
            fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        fs::write(
            &self.preferences_path,
            serde_json::to_vec_pretty(&ManagerPreferences { show_dock_icon: show })
                .map_err(|error| error.to_string())?,
        )
        .map_err(|error| error.to_string())?;
        *self.show_dock_icon.lock().map_err(|_| "preference lock failed")? = show;
        Ok(())
    }

    pub fn show_dock_icon(&self) -> bool {
        self.show_dock_icon.lock().map(|value| *value).unwrap_or(false)
    }
}

impl Drop for ManagerState {
    fn drop(&mut self) {
        if let Ok(mut processes) = self.processes.lock() {
            stop_child(&mut processes.worker);
            stop_child(&mut processes.api);
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

fn api_is_listening() -> bool {
    API_ADDRESS
        .parse::<SocketAddr>()
        .ok()
        .and_then(|address| TcpStream::connect_timeout(&address, Duration::from_millis(150)).ok())
        .is_some()
}

fn wait_for_api(child: &mut Child) -> Result<(), String> {
    for _ in 0..80 {
        if let Ok(Some(status)) = child.try_wait() {
            return Err(format!(
                "KNU API가 시작 중 종료되었습니다 ({status}). 서버 로그를 확인하세요."
            ));
        }
        if api_is_listening() {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(100));
    }
    Err("KNU API가 8초 안에 준비되지 않았습니다. 서버 로그를 확인하세요.".into())
}

#[tauri::command]
pub fn runtime_status(state: tauri::State<ManagerState>) -> RuntimeStatus {
    let (api_running, worker_running) = if let Ok(mut p) = state.processes.lock() {
        (child_running(&mut p.api), child_running(&mut p.worker))
    } else {
        (false, false)
    };
    RuntimeStatus {
        running: api_running && worker_running,
        api_running,
        worker_running,
        url: "http://127.0.0.1:8000".into(),
        admin_token: state.admin_token.clone(),
        server_root: state.root.display().to_string(),
        python_path: state.python.display().to_string(),
        logs: state
            .logs
            .lock()
            .map(|v| v.iter().cloned().collect())
            .unwrap_or_default(),
        show_dock_icon: state.show_dock_icon(),
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
    let api_root = state.root.join("services/api");
    if !api_root.join("api/main.py").exists() {
        return Err(format!(
            "KNU server source not found: {}",
            api_root.display()
        ));
    }
    let mut child = Command::new(&state.python)
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
    let api_root = state.root.join("services/api");
    let output = Command::new(&state.python)
        .args(["-m", "db.migrate"])
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

#[tauri::command]
pub fn start_server(state: tauri::State<ManagerState>) -> Result<(), String> {
    start_managed_server(state.inner())
}

pub(crate) fn start_managed_server(state: &ManagerState) -> Result<(), String> {
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
    migrate_database(&state)?;
    if !child_running(&mut p.api) {
        if api_is_listening() {
            return Err("8000번 포트에서 다른 KNU API가 이미 실행 중입니다. 이전 KNU Server Manager를 종료한 뒤 다시 시도하세요.".into());
        }
        let mut api = spawn_python(
            &state,
            &[
                "-m",
                "uvicorn",
                "api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            "api",
        )?;
        if let Err(error) = wait_for_api(&mut api) {
            let _ = api.kill();
            let _ = api.wait();
            return Err(error);
        }
        p.api = Some(api);
    }
    if !child_running(&mut p.worker) {
        match spawn_python(
            &state,
            &["-m", "arq", "workers.arq_worker.WorkerSettings"],
            "worker",
        ) {
            Ok(child) => p.worker = Some(child),
            Err(error) => {
                if let Some(mut api) = p.api.take() {
                    let _ = api.kill();
                }
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

    #[test]
    fn detects_a_listening_tcp_socket() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        assert!(TcpStream::connect_timeout(&address, Duration::from_millis(100)).is_ok());
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
    let mut p = state
        .processes
        .lock()
        .map_err(|_| "process state lock failed")?;
    stop_child(&mut p.worker);
    stop_child(&mut p.api);
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
