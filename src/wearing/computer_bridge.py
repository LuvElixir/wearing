"""Small CLI bridge to Hermes' existing desktop driver and control lease.

Runs under the managed Hermes interpreter. No model keys are loaded here;
driver download verification, permissions and input remain upstream-owned.
"""
import json
from pathlib import Path
import sys


def main():
    source, action = Path(sys.argv[1]).resolve(), sys.argv[2]
    sys.path.insert(0, str(source))
    from tools.bot_desktop import lease
    if action == "status":
        from tools.computer_use.permissions import computer_use_status
        value = computer_use_status()
        executable = (value.get("source") or {}).get("executable")
        if executable and sys.platform == "darwin":
            bundle = next((p for p in Path(executable).parents if p.suffix == ".app"), None)
            if bundle and bundle.is_dir():
                value["permission_app_path"] = str(bundle)
        value["control"] = lease.public_view(lease.get())
        print(json.dumps(value))
    elif action in ("takeover", "resume", "control"):
        if action == "takeover":
            current = lease.acquire("wearing-local-user", reason="用户已在 Wearing 接管电脑")
        elif action == "resume":
            current = lease.release("wearing-local-user")
        else:
            current = lease.get()
        print(json.dumps(lease.public_view(current)))
    elif action == "install":
        from hermes_cli.tools_config_cua import install_cua_driver
        sys.exit(0 if install_cua_driver() else 1)
    elif action == "permissions":
        import subprocess
        from tools.computer_use.cua_backend_driver import resolve_cua_driver_cmd
        from tools.computer_use.cua_backend import sanitized_cua_driver_env
        binary = resolve_cua_driver_cmd()
        if sys.platform != "darwin" or not binary:
            raise RuntimeError("The macOS driver is not installed")
        # The driver's bounded prompt helper waits for the person. Do not hold
        # a web request open or treat taking longer to approve as a failure.
        subprocess.Popen([binary, "permissions", "grant"], env=sanitized_cua_driver_env(),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    else:
        raise ValueError("Unknown desktop operation")


if __name__ == "__main__":
    main()
