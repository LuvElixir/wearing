use serde::{Deserialize, Serialize};
use std::{
    fs,
    io::{Read, Write},
    path::Path,
    time::Duration,
};
use url::Url;

pub const DEFAULT_SERVER: &str = "https://pajio.luckyloading.com/";
pub const LOCAL_SERVER: &str = "http://127.0.0.1:8765/";
// 正式服务的固定登录边界：只有这个服务地址允许“未登录 401 引导”，只有这个 IdP
// 主机的 /realms/pajio/ 前缀允许在主窗口导航。除此之外不放宽任何 HTTPS/重定向。
pub const OFFICIAL_IDP_HOST: &str = "id.pajio.luckyloading.com";
pub const OFFICIAL_IDP_REALM_PREFIX: &str = "/realms/pajio/";

#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Connection {
    pub url: String,
}

impl Default for Connection {
    fn default() -> Self {
        Self {
            url: DEFAULT_SERVER.into(),
        }
    }
}

pub fn development_endpoints_enabled() -> bool {
    cfg!(all(debug_assertions, feature = "development-endpoints"))
}

pub fn development_connection(value: &str) -> Result<Connection, String> {
    if !development_endpoints_enabled() {
        return Err("自定义连接仅限开发构建。请使用官方登录入口。".into());
    }
    connection_for_mode(value, true)
}

/// A release build never accepts a custom endpoint, including one saved by an older build.
pub fn connection_for_mode(value: &str, development: bool) -> Result<Connection, String> {
    let url = server_url(value)?;
    if !development && !official_origin(&url) {
        return Err("请使用 Pajio 的官方登录入口。".into());
    }
    Ok(Connection {
        url: url.to_string(),
    })
}

/// Callers select an intent, never a URL, code, credential, or redirect destination.
pub fn account_entry(intent: &str) -> Result<Url, String> {
    let path = match intent {
        "join" => "join",
        "login" => "auth/login",
        "continue" => "",
        _ => return Err("请选择邀请码入口或已有账号登录。".into()),
    };
    Url::parse(DEFAULT_SERVER)
        .unwrap()
        .join(path)
        .map_err(|_| "登录入口暂时不可用。".into())
}

pub struct StartupConnection {
    pub connection: Connection,
    pub warning: Option<String>,
    pub auto_connect: bool,
}

pub fn startup(path: &Path, development: bool) -> StartupConnection {
    let existed = path.exists();
    match load(path) {
        Ok(saved) => match connection_for_mode(&saved.url, development) {
            Ok(connection) => StartupConnection {
                connection,
                warning: None,
                auto_connect: existed,
            },
            Err(_) => {
                // No request is sent to the old origin. Only the URL setting is migrated;
                // browser cookies remain origin-scoped and are never copied or forwarded.
                let connection = Connection::default();
                let warning = if save(path, &connection).is_ok() {
                    "Pajio 已统一使用官方入口，请重新登录。旧服务上的记录没有迁移。"
                } else {
                    "Pajio 已统一使用官方入口。旧连接设置无法更新，原文件已保留；请重新登录。"
                };
                StartupConnection {
                    connection,
                    warning: Some(warning.into()),
                    auto_connect: false,
                }
            }
        },
        Err(error) => StartupConnection {
            connection: Connection::default(),
            warning: Some(format!("{error} 原设置已保留，请从官方入口登录。")),
            auto_connect: false,
        },
    }
}

pub fn server_url(value: &str) -> Result<Url, String> {
    let url = Url::parse(value.trim()).map_err(|_| "请填写完整的 Pajio 地址。")?;
    let loopback = matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "[::1]"));
    if url.host_str().is_none()
        || !(url.scheme() == "https" || (url.scheme() == "http" && loopback))
    {
        return Err("本机连接使用 localhost；远程地址需要 HTTPS。".into());
    }
    if !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || url.path() != "/"
    {
        return Err("请填写 Pajio 首页地址，去掉账号、路径、查询参数和页内位置。".into());
    }
    Ok(url)
}

/// 严格相等比较正式服务 origin（scheme/host/port 全等；不带 userinfo/query）。
pub fn official_origin(url: &Url) -> bool {
    url.scheme() == "https"
        && url.host_str() == Some("pajio.luckyloading.com")
        && url.port().is_none()
        && url.username().is_empty()
        && url.password().is_none()
}

/// 官方 IdP 登录导航：仅 https + 固定主机 + 默认端口 + /realms/pajio/ 前缀，
/// 允许 OIDC 所需的查询串；拒绝 userinfo、其他主机/端口/路径。
pub fn idp_login_url_allowed(url: &Url) -> bool {
    url.scheme() == "https"
        && url.host_str() == Some(OFFICIAL_IDP_HOST)
        && url.port().is_none()
        && url.username().is_empty()
        && url.password().is_none()
        && url.path().starts_with(OFFICIAL_IDP_REALM_PREFIX)
        && url.fragment().is_none()
}

/// 主窗口导航许可：本机壳 / 已连服务 / （仅当连接的是正式服务时的）官方 IdP 登录。
pub fn login_navigation_allowed(connection: &Connection, url: &Url) -> bool {
    let server = match server_url(&connection.url) {
        Ok(value) => value,
        Err(_) => return false,
    };
    official_origin(&server) && idp_login_url_allowed(url)
}

pub fn bundled_origin(url: &Url) -> bool {
    url.port().is_none()
        && url.username().is_empty()
        && url.password().is_none()
        && ((url.scheme() == "tauri" && url.host_str() == Some("localhost"))
            || (matches!(url.scheme(), "http" | "https")
                && url.host_str() == Some("tauri.localhost")))
}

pub fn native_caller(label: &str, url: &Url) -> bool {
    matches!(label, "main" | "connection") && bundled_origin(url)
}

pub fn load(path: &Path) -> Result<Connection, String> {
    if !path.exists() {
        return Ok(Connection::default());
    }
    if path.is_symlink() {
        return Err("连接设置不可使用符号链接。".into());
    }
    if fs::metadata(path)
        .map_err(|_| "连接设置暂时无法读取。")?
        .len()
        > 4096
    {
        return Err("连接设置格式不完整。".into());
    }
    let bytes = fs::read(path).map_err(|_| "连接设置暂时无法读取。")?;
    if bytes.len() > 4096 {
        return Err("连接设置格式不完整。".into());
    }
    let value: Connection = serde_json::from_slice(&bytes).map_err(|_| "连接设置格式不完整。")?;
    server_url(&value.url)?;
    Ok(value)
}

pub fn save(path: &Path, value: &Connection) -> Result<(), String> {
    server_url(&value.url)?;
    let parent = path.parent().ok_or("无法保存连接设置。")?;
    if parent.is_symlink() || path.is_symlink() {
        return Err("连接目录不可使用符号链接。".into());
    }
    fs::create_dir_all(parent).map_err(|_| "无法保存连接设置。")?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(parent, fs::Permissions::from_mode(0o700))
            .map_err(|_| "无法保存连接设置。")?;
    }
    let mut temporary =
        tempfile::NamedTempFile::new_in(parent).map_err(|_| "无法保存连接设置。")?;
    temporary
        .write_all(&serde_json::to_vec(value).unwrap())
        .map_err(|_| "无法保存连接设置。")?;
    temporary
        .as_file()
        .sync_all()
        .map_err(|_| "无法保存连接设置。")?;
    temporary.persist(path).map_err(|_| "无法保存连接设置。")?;
    Ok(())
}

#[derive(Deserialize)]
struct Bootstrap {
    version: String,
    deployment: String,
}

pub fn verify(url: &Url) -> Result<(), String> {
    // 只有严格匹配的正式服务地址允许 401 未登录引导；自定义地址一律要求 200。
    verify_probe(url, official_origin(url))
}

/// `official_entry`：目标是否为正式服务（生产路径由 official_origin 纯判定，
/// 测试可注入以覆盖 401 分支）。TLS 校验始终启用（reqwest 默认验证证书链）。
pub fn verify_probe(url: &Url, official_entry: bool) -> Result<(), String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(6))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| "连接暂时没有完成。")?;
    let response = client
        .get(url.join("api/bootstrap").unwrap())
        .send()
        .map_err(|_| "Pajio 暂时没连上。检查服务是否已启动，再试一次。")?;
    if response.status().as_u16() == 401 && official_entry {
        // 正式服务未登录：接受并进入页面内登录流程。
        return Ok(());
    }
    if !response.status().is_success() {
        return Err("这个地址暂时没有返回可用的 Pajio 页面。".into());
    }
    let mut bytes = Vec::new();
    response
        .take(65537)
        .read_to_end(&mut bytes)
        .map_err(|_| "连接暂时没有完成。")?;
    if bytes.len() > 65536 {
        return Err("这个地址暂时没有返回可用的 Pajio 页面。".into());
    }
    let info: Bootstrap =
        serde_json::from_slice(&bytes).map_err(|_| "没有读到 Pajio 的连接信息。")?;
    if info.version.is_empty() || !matches!(info.deployment.as_str(), "local" | "cloud") {
        return Err("没有读到 Pajio 的连接信息。".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn account_intents_only_open_fixed_official_paths() {
        for (intent, expected) in [
            ("join", "/join"),
            ("login", "/auth/login"),
            ("continue", "/"),
        ] {
            let url = account_entry(intent).unwrap();
            assert!(official_origin(&url));
            assert_eq!(url.path(), expected);
            assert!(url.query().is_none() && url.fragment().is_none());
        }
        for value in [
            "https://evil.example",
            "join?code=private",
            "//evil.example",
            "logout",
            "",
        ] {
            assert!(account_entry(value).is_err());
        }
    }
    #[test]
    fn production_rejects_custom_endpoints_even_if_https() {
        assert!(connection_for_mode(DEFAULT_SERVER, false).is_ok());
        for value in [
            LOCAL_SERVER,
            "https://example.com/",
            "https://pajio.luckyloading.com:8443/",
        ] {
            assert!(connection_for_mode(value, false).is_err());
            assert!(connection_for_mode(value, true).is_ok());
        }
        assert_eq!(
            development_endpoints_enabled(),
            cfg!(all(debug_assertions, feature = "development-endpoints"))
        );
        assert_eq!(
            development_connection(LOCAL_SERVER).is_ok(),
            development_endpoints_enabled()
        );
    }
    #[test]
    fn first_launch_offers_account_actions_without_automatic_navigation() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("connection.json");
        let first = startup(&path, false);
        assert_eq!(first.connection.url, DEFAULT_SERVER);
        assert!(!first.auto_connect);
        assert!(!path.exists());
    }
    #[test]
    fn legacy_custom_url_migrates_locally_without_network_or_credentials() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("connection.json");
        save(
            &path,
            &Connection {
                url: "https://old-service.invalid/".into(),
            },
        )
        .unwrap();
        let initial = startup(&path, false);
        assert_eq!(initial.connection.url, DEFAULT_SERVER);
        assert!(!initial.auto_connect);
        assert!(initial.warning.is_some());
        assert_eq!(
            fs::read_to_string(&path).unwrap(),
            format!("{{\"url\":\"{DEFAULT_SERVER}\"}}")
        );
        let next = startup(&path, false);
        assert!(next.auto_connect);
        assert!(next.warning.is_none());
    }
    #[test]
    fn development_keeps_custom_url_but_invalid_saved_credentials_are_never_imported() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("connection.json");
        save(
            &path,
            &Connection {
                url: LOCAL_SERVER.into(),
            },
        )
        .unwrap();
        let dev = startup(&path, true);
        assert_eq!(dev.connection.url, LOCAL_SERVER);
        assert!(dev.auto_connect);
        let invalid = br#"{"url":"https://old-service.invalid/","token":"synthetic-secret"}"#;
        fs::write(&path, invalid).unwrap();
        let production = startup(&path, false);
        assert_eq!(production.connection.url, DEFAULT_SERVER);
        assert!(!production.auto_connect);
        assert!(!production.warning.unwrap().contains("synthetic-secret"));
        assert_eq!(fs::read(&path).unwrap(), invalid);
    }
    #[test]
    fn default_is_official_and_local_still_allowed() {
        assert!(official_origin(&server_url(DEFAULT_SERVER).unwrap()));
        for s in [
            LOCAL_SERVER,
            "http://localhost:8765",
            "http://[::1]:8765/",
            "https://wearing.example/",
        ] {
            assert!(server_url(s).is_ok(), "{s}");
        }
    }
    #[test]
    fn endpoints_reject_remote_http_and_embedded_data() {
        for s in [
            "http://evil.example/",
            "http://localhost.evil.example/",
            "file:///tmp/",
            "javascript:alert(1)",
            "https://user:key@server.example/",
            "https://server.example/?token=secret",
            "https://server.example/app",
            "https://server.example/#hello",
        ] {
            assert!(server_url(s).is_err(), "{s}");
        }
    }
    #[test]
    fn remote_content_never_has_native_settings_access() {
        assert!(native_caller(
            "connection",
            &Url::parse("tauri://localhost/index.html").unwrap()
        ));
        assert!(native_caller(
            "main",
            &Url::parse("http://tauri.localhost/").unwrap()
        ));
        assert!(!native_caller("main", &server_url(DEFAULT_SERVER).unwrap()));
        assert!(!native_caller(
            "main",
            &server_url("https://wearing.example").unwrap()
        ));
        assert!(!native_caller(
            "original-1",
            &Url::parse("tauri://localhost/").unwrap()
        ));
        assert!(!native_caller(
            "main",
            &Url::parse("http://tauri.localhost:1234/").unwrap()
        ));
    }
    #[test]
    fn official_origin_rejects_spoofs() {
        for s in [
            "https://pajio.luckyloading.com.evil.example/",
            "https://pajio.luckyloading.com:8443/",
            "http://pajio.luckyloading.com/",
            "https://user@pajio.luckyloading.com/",
            "https://xn--pajio-luckyloading-331b.example/",
        ] {
            let url = match server_url(s) {
                Ok(value) => value,
                Err(_) => continue, // server_url 层已拒绝
            };
            assert!(!official_origin(&url), "{s}");
        }
        assert!(official_origin(
            &server_url("https://pajio.luckyloading.com/").unwrap()
        ));
    }
    #[test]
    fn idp_login_allows_only_official_realm() {
        for s in [
            "https://id.pajio.luckyloading.com/realms/pajio/protocol/openid-connect/auth?state=x",
            "https://id.pajio.luckyloading.com/realms/pajio/login-actions-authenticate?client_id=y",
        ] {
            assert!(idp_login_url_allowed(&Url::parse(s).unwrap()), "{s}");
        }
        for s in [
            "http://id.pajio.luckyloading.com/realms/pajio/auth", // 非 https
            "https://id.pajio.luckyloading.com:8443/realms/pajio/auth", // 端口
            "https://evil.example/realms/pajio/auth",             // 主机
            "https://id.pajio.luckyloading.com/realms/other/auth", // 错 realm
            "https://id.pajio.luckyloading.com/admin/console",    // 错路径
            "https://user@id.pajio.luckyloading.com/realms/pajio/auth", // userinfo
            "https://id.pajio.luckyloading.com/realms/pajio/auth#frag", // fragment
        ] {
            assert!(!idp_login_url_allowed(&Url::parse(s).unwrap()), "{s}");
        }
    }
    #[test]
    fn login_navigation_only_when_connected_to_official() {
        let official = Connection {
            url: "https://pajio.luckyloading.com/".into(),
        };
        let local = Connection {
            url: LOCAL_SERVER.into(),
        };
        let idp =
            Url::parse("https://id.pajio.luckyloading.com/realms/pajio/auth?state=1").unwrap();
        let evil = Url::parse("https://evil.example/realms/pajio/auth").unwrap();
        assert!(login_navigation_allowed(&official, &idp));
        assert!(!login_navigation_allowed(&local, &idp));
        assert!(!login_navigation_allowed(&official, &evil));
        assert!(!login_navigation_allowed(
            &official,
            &Url::parse("https://id.pajio.luckyloading.com/admin").unwrap()
        ));
    }
    #[test]
    fn invalid_saved_settings_are_reported_and_not_replaced() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("connection.json");
        fs::write(&path, b"not json").unwrap();
        assert!(load(&path).is_err());
        assert_eq!(fs::read(path).unwrap(), b"not json");
    }
    #[test]
    fn settings_roundtrip_without_credentials_or_records() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("connection.json");
        let value = Connection {
            url: "https://wearing.example/".into(),
        };
        save(&path, &value).unwrap();
        assert_eq!(load(&path).unwrap().url, value.url);
        let replacement = Connection::default();
        save(&path, &replacement).unwrap();
        assert_eq!(load(&path).unwrap().url, replacement.url);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(path).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }
    }
    fn probe_response(status: &str, body: &str, extra: &str) -> Result<(), String> {
        probe_response_as(status, body, extra, false)
    }
    fn probe_response_as(
        status: &str,
        body: &str,
        extra: &str,
        official_entry: bool,
    ) -> Result<(), String> {
        use std::net::TcpListener;
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = Url::parse(&format!("http://{}/", listener.local_addr().unwrap())).unwrap();
        let response = format!(
            "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n{extra}\r\n{body}",
            body.len()
        );
        let handler = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0; 4096];
            let _ = stream.read(&mut request);
            assert!(String::from_utf8_lossy(&request).starts_with("GET /api/bootstrap "));
            let _ = stream.write_all(response.as_bytes());
        });
        let result = verify_probe(&url, official_entry);
        handler.join().unwrap();
        result
    }
    #[test]
    fn official_401_guides_login_but_custom_stays_strict() {
        // 正式入口：401 = 未登录引导（注入 official_entry=true 覆盖分支语义）；
        // 自定义地址（official_entry=false）维持严格 200。
        assert!(probe_response_as("401 Unauthorized", "", "", true).is_ok());
        assert!(probe_response_as("401 Unauthorized", "", "", false).is_err());
        assert!(probe_response_as(
            "302 Found",
            "",
            "Location: https://pajio.luckyloading.com/\r\n",
            true
        )
        .is_err());
    }
    #[test]
    fn handshake_requires_a_wearing_response() {
        assert!(probe_response(
            "200 OK",
            r#"{"version":"0.2.0","deployment":"local"}"#,
            "Content-Type: application/json\r\n"
        )
        .is_ok());
        assert!(probe_response("200 OK", "<html>another service</html>", "").is_err());
        assert!(probe_response(
            "200 OK",
            r#"{"version":"0.2.0","deployment":"unknown"}"#,
            ""
        )
        .is_err());
    }
    #[test]
    fn handshake_does_not_follow_redirects() {
        assert!(probe_response("302 Found", "", "Location: https://wearing.example/\r\n").is_err());
    }
    #[test]
    fn handshake_bounds_response_size() {
        assert!(probe_response("200 OK", &"x".repeat(70000), "").is_err());
    }
    #[test]
    #[cfg(unix)]
    fn symlink_settings_cannot_read_or_overwrite_other_files() {
        let dir = tempfile::tempdir().unwrap();
        let actual = dir.path().join("other.json");
        fs::write(&actual, b"keep").unwrap();
        let path = dir.path().join("connection.json");
        std::os::unix::fs::symlink(&actual, &path).unwrap();
        assert!(load(&path).is_err());
        assert!(save(&path, &Connection::default()).is_err());
        assert_eq!(fs::read(actual).unwrap(), b"keep");
    }
}
