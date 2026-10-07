use serde::{Deserialize, Serialize};
use std::{
    fs,
    io::{Read, Write},
    path::Path,
    time::Duration,
};
use url::Url;

pub const DEFAULT_SERVER: &str = "http://127.0.0.1:8765/";

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

pub fn server_url(value: &str) -> Result<Url, String> {
    let url = Url::parse(value.trim()).map_err(|_| "请填写完整的 Wearing 地址。")?;
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
        return Err("请填写 Wearing 首页地址，去掉账号、路径、查询参数和页内位置。".into());
    }
    Ok(url)
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
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(6))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| "连接暂时没有完成。")?;
    let response = client
        .get(url.join("api/bootstrap").unwrap())
        .send()
        .map_err(|_| "Wearing 暂时没连上。检查服务是否已启动，再试一次。")?;
    if !response.status().is_success() {
        return Err("这个地址暂时没有返回可用的 Wearing 页面。".into());
    }
    let mut bytes = Vec::new();
    response
        .take(65537)
        .read_to_end(&mut bytes)
        .map_err(|_| "连接暂时没有完成。")?;
    if bytes.len() > 65536 {
        return Err("这个地址暂时没有返回可用的 Wearing 页面。".into());
    }
    let info: Bootstrap =
        serde_json::from_slice(&bytes).map_err(|_| "没有读到 Wearing 的连接信息。")?;
    if info.version.is_empty() || !matches!(info.deployment.as_str(), "local" | "cloud") {
        return Err("没有读到 Wearing 的连接信息。".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn endpoints_allow_loopback_and_https() {
        for s in [
            DEFAULT_SERVER,
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
        let result = verify(&url);
        handler.join().unwrap();
        result
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
