fn main() {
    if std::env::var("PROFILE").as_deref() == Ok("release") {
        let manager_root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .expect("src-tauri must be inside the manager directory");
        let runtime = manager_root.join("runtime");
        let executable = |name: &str| {
            if cfg!(target_os = "windows") {
                format!("{name}.exe")
            } else {
                name.to_string()
            }
        };
        let python = if cfg!(target_os = "windows") {
            runtime.join("knu/.knu-runtime/python.exe")
        } else {
            runtime.join("knu/.knu-runtime/bin/python")
        };
        let required = [
            python,
            runtime.join("postgres/bin").join(executable("postgres")),
            runtime.join("redis/bin").join(executable("redis-server")),
            runtime.join("java/bin").join(executable("java")),
            runtime.join("runtime-manifest.json"),
        ];
        for path in required {
            if !path.is_file() {
                panic!(
                    "standalone runtime is incomplete (missing {}). Run `npm run bundle` instead of invoking `tauri build` directly",
                    path.display()
                );
            }
        }
    }
    tauri_build::build()
}
