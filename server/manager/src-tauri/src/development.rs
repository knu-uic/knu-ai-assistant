//! Packaged tools, live repository source, and private development data.
use serde::Deserialize;
use std::{
    fs,
    path::{Path, PathBuf},
};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DevelopmentRuntime {
    pub schema_version: u32,
    pub platform: String,
    pub arch: String,
    pub runtime_root: PathBuf,
    pub python_path: PathBuf,
    pub browser_root: Option<PathBuf>,
    pub requirements_text: String,
}

pub fn platform() -> &'static str {
    if cfg!(target_os = "windows") {
        "win32"
    } else if cfg!(target_os = "macos") {
        "darwin"
    } else {
        "linux"
    }
}

pub fn architecture() -> &'static str {
    if cfg!(target_arch = "aarch64") {
        "arm64"
    } else {
        "x64"
    }
}

pub fn load(repo: &Path) -> Result<Option<DevelopmentRuntime>, String> {
    let file = repo.join("server/manager/.dev/runtime.json");
    let raw = match fs::read(&file) {
        Ok(raw) => raw,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(format!("개발 실행 환경 설정을 읽지 못했습니다: {error}")),
    };
    let config: DevelopmentRuntime = serde_json::from_slice(&raw)
        .map_err(|error| format!("개발 실행 환경 설정이 잘못되었습니다: {error}"))?;
    validate(&config, repo, platform(), architecture())?;
    Ok(Some(config))
}

pub fn validate(
    config: &DevelopmentRuntime,
    repo: &Path,
    platform: &str,
    arch: &str,
) -> Result<(), String> {
    let repair = "server/manager에서 npm run setup:dev를 다시 실행하세요.";
    if config.schema_version != 1 || config.platform != platform || config.arch != arch {
        return Err(format!(
            "개발 실행 환경의 운영체제/CPU 또는 설정 버전이 다릅니다. {repair}"
        ));
    }
    if !config.runtime_root.is_absolute()
        || !config.python_path.is_absolute()
        || !config.python_path.is_file()
        || config.browser_root.as_ref().is_some_and(|path| !path.is_absolute() || !path.is_dir())
    {
        return Err(format!("개발용 실행 도구를 찾지 못했습니다. {repair}"));
    }
    let requirements = fs::read_to_string(repo.join("server/api/requirements.txt"))
        .map_err(|error| format!("Python 의존성 목록을 읽지 못했습니다: {error}"))?;
    if requirements != config.requirements_text {
        return Err(format!("Python 의존성이 변경되었습니다. {repair}"));
    }
    Ok(())
}

pub fn data_root(repo: &Path) -> PathBuf {
    repo.join("server/manager/.dev/data")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn development_data_is_in_the_repository_not_application_support() {
        assert_eq!(
            data_root(Path::new("/repo")),
            PathBuf::from("/repo/server/manager/.dev/data")
        );
    }

    #[test]
    fn rejects_another_operating_system_before_using_its_runtime() {
        let config = DevelopmentRuntime {
            schema_version: 1,
            platform: "darwin".into(),
            arch: "arm64".into(),
            runtime_root: PathBuf::from("/runtime"),
            python_path: PathBuf::from("/runtime/python"),
            browser_root: None,
            requirements_text: String::new(),
        };
        assert!(validate(&config, Path::new("/repo"), "win32", "x64")
            .unwrap_err()
            .contains("운영체제/CPU"));
    }

    #[test]
    fn missing_setup_is_explicitly_reported_to_the_caller() {
        let missing =
            std::env::temp_dir().join(format!("knu-dev-missing-{}", rand::random::<u64>()));
        assert!(load(&missing).unwrap().is_none());
    }

    #[test]
    fn changed_dependencies_require_setup_again() {
        let repo = std::env::temp_dir().join(format!("knu-dev-validation-{}", rand::random::<u64>()));
        fs::create_dir_all(repo.join("server/api")).unwrap();
        fs::write(repo.join("server/api/requirements.txt"), "fastapi==0.2\n").unwrap();
        let python = repo.join("portable-python");
        fs::write(&python, "test fixture, never executed").unwrap();
        let mut config = DevelopmentRuntime {
            schema_version: 1,
            platform: platform().into(),
            arch: architecture().into(),
            runtime_root: repo.clone(),
            python_path: python,
            browser_root: None,
            requirements_text: "fastapi==0.1\n".into(),
        };
        let error = validate(&config, &repo, platform(), architecture()).unwrap_err();
        assert!(error.contains("Python 의존성이 변경"));
        config.requirements_text = "fastapi==0.2\n".into();
        assert!(validate(&config, &repo, platform(), architecture()).is_ok());
        fs::remove_file(&config.python_path).unwrap();
        assert!(validate(&config, &repo, platform(), architecture())
            .unwrap_err().contains("실행 도구"));
        fs::remove_dir_all(repo).unwrap();
    }
}
