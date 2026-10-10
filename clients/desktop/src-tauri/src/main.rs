#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod endpoint;

use endpoint::Connection;
use serde::Serialize;
use std::{
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Mutex,
    },
};
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem, Submenu},
    tray::TrayIconBuilder,
    webview::{NewWindowResponse, PageLoadEvent},
    AppHandle, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

struct DesktopState {
    connection: Mutex<Connection>,
    path: PathBuf,
    warning: Option<String>,
    shortcut_ready: AtomicBool,
    connecting: AtomicBool,
    pending_capture: AtomicBool,
    popup_sequence: AtomicU64,
}

fn caller(window: &WebviewWindow) -> Result<(), String> {
    if endpoint::native_caller(
        window.label(),
        &window.url().map_err(|_| "连接页暂时没有打开。")?,
    ) {
        Ok(())
    } else {
        Err("请从桌面客户端的连接设置操作。".into())
    }
}

#[derive(Serialize)]
struct ConnectionInfo {
    url: String,
    auto_connect: bool,
    warning: Option<String>,
    shortcut_ready: bool,
    shortcut_label: &'static str,
}

#[tauri::command]
fn connection_info(window: WebviewWindow, app: AppHandle) -> Result<ConnectionInfo, String> {
    caller(&window)?;
    let state = app.state::<DesktopState>();
    let url = state
        .connection
        .lock()
        .map_err(|_| "连接设置暂时不可用。")?
        .url
        .clone();
    Ok(ConnectionInfo {
        url,
        auto_connect: window.label() == "main" && state.warning.is_none(),
        warning: state.warning.clone(),
        shortcut_ready: state.shortcut_ready.load(Ordering::Relaxed),
        shortcut_label: if cfg!(target_os = "macos") {
            "⌘ ⇧ 空格"
        } else {
            "Ctrl + Shift + 空格"
        },
    })
}

#[tauri::command]
async fn connect_server(
    window: WebviewWindow,
    app: AppHandle,
    value: String,
    persist: bool,
) -> Result<(), String> {
    caller(&window)?;
    let url = endpoint::server_url(&value)?;
    let state = app.state::<DesktopState>();
    if state.connecting.swap(true, Ordering::SeqCst) {
        return Err("已经在连接，请稍等一下。".into());
    }
    let probe_url = url.clone();
    let result = tauri::async_runtime::spawn_blocking(move || endpoint::verify(&probe_url))
        .await
        .map_err(|_| "连接暂时没有完成。".to_owned())
        .and_then(|r| r);
    if let Err(error) = result {
        state.connecting.store(false, Ordering::SeqCst);
        return Err(error);
    }
    let connection = Connection {
        url: url.to_string(),
    };
    if persist {
        if let Err(error) = endpoint::save(&state.path, &connection) {
            state.connecting.store(false, Ordering::SeqCst);
            return Err(error);
        }
    }
    *state
        .connection
        .lock()
        .map_err(|_| "连接设置暂时不可用。")? = connection;
    state.connecting.store(false, Ordering::SeqCst);
    let main = app
        .get_webview_window("main")
        .ok_or("Pajio 窗口暂时没有打开。")?;
    main.navigate(url)
        .map_err(|_| "连接已找到，但页面暂时没有打开。")?;
    let _ = main.show();
    let _ = main.set_focus();
    if window.label() == "connection" {
        let _ = window.close();
    }
    Ok(())
}

fn service_origin(app: &AppHandle, url: &url::Url) -> bool {
    app.state::<DesktopState>()
        .connection
        .lock()
        .ok()
        .and_then(|connection| endpoint::server_url(&connection.url).ok())
        .is_some_and(|server| server.origin() == url.origin())
}

/// 官方 IdP 登录导航：仅当当前连接的是正式服务时，允许固定主机/realm 的 OIDC 导航。
fn official_login_origin(app: &AppHandle, url: &url::Url) -> bool {
    app.state::<DesktopState>()
        .connection
        .lock()
        .ok()
        .is_some_and(|connection| endpoint::login_navigation_allowed(&connection, url))
}

fn focus_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn quick_capture(app: &AppHandle) {
    focus_main(app);
    if let Some(window) = app.get_webview_window("main") {
        if window
            .url()
            .ok()
            .is_some_and(|url| service_origin(app, &url))
        {
            // Static intent only. The web application owns the record, identity and draft.
            let _ = window.eval("window.dispatchEvent(new Event('wearing:quick-capture'))");
        } else {
            app.state::<DesktopState>()
                .pending_capture
                .store(true, Ordering::Relaxed);
        }
    }
}

fn connection_panel(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("connection") {
        let _ = window.show();
        let _ = window.set_focus();
        return;
    }
    let _ = WebviewWindowBuilder::new(app, "connection", WebviewUrl::App("index.html".into()))
        .title("连接 Pajio")
        .inner_size(480.0, 740.0)
        .min_inner_size(360.0, 620.0)
        .resizable(true)
        .on_navigation(endpoint::bundled_origin)
        .build();
}

fn menu_action(app: &AppHandle, id: &str) {
    match id {
        "show" => focus_main(app),
        "capture" => quick_capture(app),
        "connection" => connection_panel(app),
        "quit-client" => app.exit(0),
        _ => (),
    }
}

fn install_menu(app: &AppHandle) -> tauri::Result<()> {
    let show = MenuItem::with_id(app, "show", "打开 Pajio", true, None::<&str>)?;
    let capture = MenuItem::with_id(
        app,
        "capture",
        "记一下",
        true,
        Some("CmdOrCtrl+Shift+Space"),
    )?;
    let settings = MenuItem::with_id(app, "connection", "连接设置…", true, Some("CmdOrCtrl+,"))?;
    let quit = MenuItem::with_id(app, "quit-client", "退出桌面端", true, Some("CmdOrCtrl+Q"))?;
    let sep = PredefinedMenuItem::separator(app)?;
    let product = Submenu::with_items(
        app,
        "Pajio",
        true,
        &[&show, &capture, &sep, &settings, &sep, &quit],
    )?;
    let edit = Submenu::with_items(
        app,
        "编辑",
        true,
        &[
            &PredefinedMenuItem::undo(app, None)?,
            &PredefinedMenuItem::redo(app, None)?,
            &sep,
            &PredefinedMenuItem::cut(app, None)?,
            &PredefinedMenuItem::copy(app, None)?,
            &PredefinedMenuItem::paste(app, None)?,
            &PredefinedMenuItem::select_all(app, None)?,
        ],
    )?;
    let window_menu = Submenu::with_items(
        app,
        "窗口",
        true,
        &[
            &PredefinedMenuItem::minimize(app, None)?,
            &PredefinedMenuItem::close_window(app, Some("收起窗口"))?,
        ],
    )?;
    app.set_menu(Menu::with_items(app, &[&product, &edit, &window_menu])?)?;
    let tray_menu = Menu::with_items(app, &[&show, &capture, &settings, &sep, &quit])?;
    TrayIconBuilder::with_id("wearing-presence")
        .tooltip("Pajio — 随时记一下")
        .icon(tauri::image::Image::from_bytes(include_bytes!(
            "../icons/tray.png"
        ))?)
        .icon_as_template(true)
        .menu(&tray_menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| menu_action(app, event.id.as_ref()))
        .build(app)?;
    Ok(())
}

fn build_main(app: &AppHandle) -> tauri::Result<()> {
    let nav_app = app.clone();
    let popup_app = app.clone();
    let load_app = app.clone();
    let main = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("Pajio")
        .inner_size(1180.0, 820.0)
        .min_inner_size(760.0, 600.0)
                .on_navigation(move |url| {
            endpoint::bundled_origin(url)
                || service_origin(&nav_app, url)
                || official_login_origin(&nav_app, url)
        })
        .on_page_load(move |window, payload| {
            if payload.event() == PageLoadEvent::Finished
                && service_origin(&load_app, payload.url())
                && load_app
                    .state::<DesktopState>()
                    .pending_capture
                    .swap(false, Ordering::Relaxed)
            {
                let _ = window.eval("window.dispatchEvent(new Event('wearing:quick-capture'))");
            }
        })
        .on_new_window(move |url, features| {
            if !service_origin(&popup_app, &url) {
                return NewWindowResponse::Deny;
            }
            let sequence = popup_app
                .state::<DesktopState>()
                .popup_sequence
                .fetch_add(1, Ordering::Relaxed);
            let origin = url.origin();
            match WebviewWindowBuilder::new(
                &popup_app,
                format!("original-{sequence}"),
                WebviewUrl::External("about:blank".parse().unwrap()),
            )
            .window_features(features)
            .title("Pajio · 原件")
            .inner_size(800.0, 680.0)
            .on_navigation(move |target| target.origin() == origin)
            .build()
            {
                Ok(window) => NewWindowResponse::Create { window },
                Err(_) => NewWindowResponse::Deny,
            }
        })
        .build()?;
    let close_window = main.clone();
    main.on_window_event(move |event| {
        if let tauri::WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            let _ = close_window.eval("window.dispatchEvent(new Event('wearing:window-hidden'))");
            let _ = close_window.hide();
        }
    });
    Ok(())
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            focus_main(app)
        }))
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _, event| {
                    if event.state == ShortcutState::Pressed {
                        quick_capture(app);
                    }
                })
                .build(),
        )
        .invoke_handler(tauri::generate_handler![connection_info, connect_server])
        .on_menu_event(|app, event| menu_action(app, event.id.as_ref()))
        .setup(|app| {
            let path = app.path().app_config_dir()?.join("connection.json");
            let (connection, warning) = match endpoint::load(&path) {
                Ok(value) => (value, None),
                Err(error) => (
                    Connection::default(),
                    Some(format!("{error} 原设置已保留，可以重新连接。")),
                ),
            };
            app.manage(DesktopState {
                connection: Mutex::new(connection),
                path,
                warning,
                shortcut_ready: AtomicBool::new(false),
                connecting: AtomicBool::new(false),
                pending_capture: AtomicBool::new(false),
                popup_sequence: AtomicU64::new(0),
            });
            let shortcut = if cfg!(target_os = "macos") {
                "Command+Shift+Space"
            } else {
                "Control+Shift+Space"
            };
            let ready = app.global_shortcut().register(shortcut).is_ok();
            app.state::<DesktopState>()
                .shortcut_ready
                .store(ready, Ordering::Relaxed);
            install_menu(app.handle())?;
            build_main(app.handle())?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Pajio desktop could not start");
    app.run(|app, event| {
        #[cfg(target_os = "macos")]
        if let tauri::RunEvent::Reopen { .. } = event {
            focus_main(app);
        }
        #[cfg(not(target_os = "macos"))]
        let _ = (app, event);
    });
}
