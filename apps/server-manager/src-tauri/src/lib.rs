mod manager;

use manager::{
    apply_dock_policy, clear_logs, open_auth_url, open_external_url, runtime_status,
    set_show_dock_icon, start_managed_server, start_server, stop_server,
    ManagerState,
};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, RunEvent, WindowEvent,
};

fn show_manager(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

#[cfg(target_os = "macos")]
fn distance_to_segment(px: f32, py: f32, ax: f32, ay: f32, bx: f32, by: f32) -> f32 {
    let dx = bx - ax;
    let dy = by - ay;
    let length_squared = dx * dx + dy * dy;
    let t = (((px - ax) * dx + (py - ay) * dy) / length_squared).clamp(0.0, 1.0);
    ((px - (ax + t * dx)).powi(2) + (py - (ay + t * dy)).powi(2)).sqrt()
}

#[cfg(target_os = "macos")]
fn menu_bar_template_icon(letter: char) -> tauri::image::Image<'static> {
    const SIZE: u32 = 32;
    const SAMPLES: u32 = 4;
    let mut rgba = Vec::with_capacity((SIZE * SIZE * 4) as usize);
    for y in 0..SIZE {
        for x in 0..SIZE {
            let mut covered = 0;
            for sy in 0..SAMPLES {
                for sx in 0..SAMPLES {
                    let px = ((x * SAMPLES + sx) as f32 + 0.5) / (SIZE * SAMPLES) as f32 * 2.0 - 1.0;
                    let py = ((y * SAMPLES + sy) as f32 + 0.5) / (SIZE * SAMPLES) as f32 * 2.0 - 1.0;
                    let filled = match letter {
                        'C' => {
                            let radius = (px * px + py * py).sqrt();
                            (0.47..=0.82).contains(&radius) && !(px > 0.16 && py.abs() < 0.57)
                        }
                        'K' => {
                            (-0.58..=-0.38).contains(&px) && py.abs() <= 0.82
                                || distance_to_segment(px, py, -0.40, 0.02, 0.55, -0.80) <= 0.12
                                || distance_to_segment(px, py, -0.40, -0.02, 0.55, 0.80) <= 0.12
                        }
                        _ => false,
                    };
                    covered += u32::from(filled);
                }
            }
            rgba.extend_from_slice(&[255, 255, 255, (covered * 255 / (SAMPLES * SAMPLES)) as u8]);
        }
    }
    tauri::image::Image::new_owned(rgba, SIZE, SIZE)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .setup(|app| {
            let state = ManagerState::new(&app.handle());
            let show_dock_icon = state.show_dock_icon();
            app.manage(state);
            apply_dock_policy(&app.handle(), show_dock_icon);

            let open = MenuItem::with_id(app, "open", "KNU Server Manager 열기", true, None::<&str>)?;
            let start = MenuItem::with_id(app, "start", "서버 실행", true, None::<&str>)?;
            let stop = MenuItem::with_id(app, "stop", "서버 종료", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "KNU Server Manager 완전히 종료", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &start, &stop, &quit])?;
            let mut tray = TrayIconBuilder::new()
                .tooltip("KNU Server Manager")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => show_manager(app),
                    "start" => { let _ = start_managed_server(app.state::<ManagerState>().inner()); }
                    "stop" => { let _ = stop_server(app.state::<ManagerState>()); }
                    "quit" => { let _ = stop_server(app.state::<ManagerState>()); app.exit(0); }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
                        show_manager(tray.app_handle());
                    }
                });
            if let Some(icon) = app.default_window_icon() { tray = tray.icon(icon.clone()); }
            #[cfg(target_os = "macos")]
            { tray = tray.icon(menu_bar_template_icon('K')).icon_as_template(true); }
            tray.build(app)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            runtime_status,
            start_server,
            stop_server,
            clear_logs,
            open_auth_url,
            open_external_url,
            set_show_dock_icon
        ])
        .build(tauri::generate_context!())
        .expect("failed to build KNU Server Manager");

    app.run(|app, event| match event {
        RunEvent::WindowEvent { label, event: WindowEvent::CloseRequested { api, .. }, .. } if label == "main" => {
            api.prevent_close();
            if let Some(window) = app.get_webview_window("main") { let _ = window.hide(); }
        }
        RunEvent::ExitRequested { .. } | RunEvent::Exit => {
            let _ = stop_server(app.state::<ManagerState>());
        }
        _ => {}
    });
}

#[cfg(all(test, target_os = "macos"))]
mod tests {
    use super::menu_bar_template_icon;

    #[test]
    fn menu_bar_icon_has_a_transparent_background() {
        let icon = menu_bar_template_icon('K');
        assert_eq!(icon.width(), 32);
        assert_eq!(icon.height(), 32);
        assert_eq!(icon.rgba()[3], 0);
        assert!(icon.rgba().chunks_exact(4).any(|pixel| pixel[3] > 0));
    }
}
