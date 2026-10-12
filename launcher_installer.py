#!/usr/bin/env python3
"""Cross-platform SiGMaR launcher installer.

This script prepares the runtime by loading the Docker images and creating
a desktop/menu shortcut. The shortcut launches ``launcher.py``, which is
responsible for starting the Docker stack and opening the web UI.

Packaging idea:
- Windows: freeze with PyInstaller -> SiGMaR.exe
- macOS: freeze with PyInstaller/py2app -> SiGMaR.app
- Linux: run as a script or freeze similarly
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

APP_URL = "http://localhost:8060"
APP_NAME = "SiGMaR"
PROJECT_DIR = Path(__file__).resolve().parent
LAUNCHER_SCRIPT = PROJECT_DIR / "launcher.py"
LOGO_FILE = PROJECT_DIR / "logo" / "sigmar_logo.png"
APP_IMAGE = PROJECT_DIR / "bin" / "sigmar_app_core.tar.gz"
MODELS_IMAGE = PROJECT_DIR / "bin" / "sigmar_models_bundle.tar.gz"
SHARED_DATA_DIR = PROJECT_DIR / "utilities" / "gdan-tmp-models" / "shared_data"
INSTALL_DIR = Path.home() / ".local" / "share" / APP_NAME
MACOS_PATH_PREFIX = "/opt/homebrew/bin:/usr/local/bin:/Applications/Docker.app/Contents/Resources/bin"


def detect_compose_cmd():
    bootstrap_path()
    if shutil.which("docker"):
        try:
            subprocess.run(["docker", "compose", "version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return ["docker", "compose"]
        except Exception:
            pass
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    raise RuntimeError("Docker Compose is not installed or not available on PATH.")


def docker_ready():
    bootstrap_path()
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def ensure_docker_ready():
    if docker_ready():
        return

    if platform.system().lower() == "darwin" and Path("/Applications/Docker.app").exists():
        print("Starting Docker Desktop...")
        subprocess.run(["open", "-a", "Docker"], check=False)
        for _ in range(60):
            if docker_ready():
                return
            time.sleep(2)

    raise RuntimeError("Docker Desktop is not running or the Docker daemon is not reachable.")


def bootstrap_path():
    if platform.system().lower() == "darwin":
        os.environ["PATH"] = f"{MACOS_PATH_PREFIX}:{os.environ.get('PATH', '')}"


def load_image(image_path):
    bootstrap_path()
    if image_path.exists():
        ensure_docker_ready()
        print(f"Loading {image_path.name}...")
        subprocess.run(["docker", "load", "-i", str(image_path)], check=True)
    else:
        print(f"Skipping missing image: {image_path}")


def ensure_runtime_dirs():
    (SHARED_DATA_DIR / "data").mkdir(parents=True, exist_ok=True)
    (SHARED_DATA_DIR / "tmp").mkdir(parents=True, exist_ok=True)
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)


def launcher_target():
    return str(LAUNCHER_SCRIPT.resolve())


def launcher_command():
    target = launcher_target()
    if platform.system().lower().startswith("win"):
        return f'py -3 "{target}"'
    return f'python3 "{target}"'


def create_macos_icon(app_bundle):
    if not LOGO_FILE.exists() or not shutil.which("sips") or not shutil.which("iconutil"):
        return None

    icon_path = app_bundle / "Contents" / "Resources" / f"{APP_NAME}.icns"
    icon_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_dir:
        iconset = Path(tmp_dir) / f"{APP_NAME}.iconset"
        iconset.mkdir()
        sizes = [16, 32, 128, 256, 512]
        for size in sizes:
            subprocess.run(
                [
                    "sips",
                    "-z",
                    str(size),
                    str(size),
                    str(LOGO_FILE),
                    "--out",
                    str(iconset / f"icon_{size}x{size}.png"),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                [
                    "sips",
                    "-z",
                    str(size * 2),
                    str(size * 2),
                    str(LOGO_FILE),
                    "--out",
                    str(iconset / f"icon_{size}x{size}@2x.png"),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(icon_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    return icon_path


def create_macos_app():
    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    app_bundle = desktop / f"{APP_NAME}.app"
    contents = app_bundle / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)

    executable = macos / APP_NAME
    executable.write_text(
        "#!/usr/bin/env bash\n"
        f'export PATH="{MACOS_PATH_PREFIX}:$PATH"\n'
        f'LOG_DIR="$HOME/Library/Logs/{APP_NAME}"\n'
        'mkdir -p "$LOG_DIR"\n'
        'LOG_FILE="$LOG_DIR/launcher.log"\n'
        'WAIT_FILE="$LOG_DIR/startup.html"\n'
        f'PROJECT_DIR="{PROJECT_DIR}"\n'
        'cat > "$WAIT_FILE" <<\'WAIT_PAGE\'\n'
        '<!DOCTYPE html>\n'
        '<html>\n'
        '  <head>\n'
        '    <title>SiGMaR starting</title>\n'
        '    <style>\n'
        '      body { margin: 0; min-height: 100vh; display: grid; place-items: center; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f8fafc; color: #0f172a; }\n'
        '      main { width: min(520px, calc(100vw - 32px)); padding: 28px; border: 1px solid #bfdbfe; border-radius: 8px; background: #ffffff; box-shadow: 0 16px 40px rgba(15, 23, 42, 0.12); }\n'
        '      h1 { margin: 0 0 10px; font-size: 24px; }\n'
        '      p { margin: 0; line-height: 1.5; color: #475569; }\n'
        '      a { display: inline-flex; align-items: center; justify-content: center; margin-top: 18px; min-height: 34px; padding: 0 14px; border-radius: 999px; background: #0f766e; color: #ffffff; font-weight: 700; text-decoration: none; }\n'
        '      .loader { width: 36px; height: 36px; border: 4px solid #dbeafe; border-top-color: #0f766e; border-radius: 50%; animation: spin 0.9s linear infinite; margin-bottom: 18px; }\n'
        '      @keyframes spin { to { transform: rotate(360deg); } }\n'
        '    </style>\n'
        '  </head>\n'
        '  <body>\n'
        '    <main>\n'
        '      <div class="loader"></div>\n'
        '      <h1>SiGMaR is starting</h1>\n'
        '      <p>Docker is preparing the application. This page will open SiGMaR automatically as soon as it is ready.</p>\n'
        '      <a href="http://localhost:8060/">Open SiGMaR</a>\n'
        '    </main>\n'
        '    <script>\n'
        '      const appUrl = "http://localhost:8060/";\n'
        '      const logoUrl = appUrl + "logo/sigmar_logo.png";\n'
        '      let redirected = false;\n'
        '      function goToApp() {\n'
        '        if (redirected) return;\n'
        '        redirected = true;\n'
        '        window.location.replace(appUrl);\n'
        '      }\n'
        '      function waitForApp() {\n'
        '        const probe = new Image();\n'
        '        probe.onload = goToApp;\n'
        '        probe.onerror = () => setTimeout(waitForApp, 1200);\n'
        '        probe.src = logoUrl + "?t=" + Date.now();\n'
        '      }\n'
        '      setTimeout(waitForApp, 700);\n'
        '      setTimeout(() => {\n'
        '        if (!redirected) {\n'
        '          window.location.replace(appUrl);\n'
        '        }\n'
        '      }, 20000);\n'
        '    </script>\n'
        '  </body>\n'
        '</html>\n'
        'WAIT_PAGE\n'
        'open "$WAIT_FILE" || true\n'
        '{\n'
        '  echo "==== $(date) ===="\n'
        '  cd "$PROJECT_DIR"\n'
        '  if ! command -v docker >/dev/null 2>&1; then\n'
        '    echo "Docker command not found. Install Docker Desktop and make sure it is in PATH."\n'
        '    status=127\n'
        '  else\n'
        '    if ! docker info >/dev/null 2>&1; then\n'
        '      if [ -d "/Applications/Docker.app" ]; then\n'
        '        echo "Starting Docker Desktop..."\n'
        '        open -a Docker || true\n'
        '        for i in $(seq 1 60); do\n'
        '          if docker info >/dev/null 2>&1; then\n'
        '            break\n'
        '          fi\n'
        '          sleep 2\n'
        '        done\n'
        '      fi\n'
        '    fi\n'
        '    if ! docker info >/dev/null 2>&1; then\n'
        '      echo "Docker Desktop is not running or the Docker daemon is not reachable."\n'
        '      status=1\n'
        '    elif docker compose version >/dev/null 2>&1; then\n'
        '      echo "Starting SiGMaR Docker stack with docker compose..."\n'
        '      PWD="$PROJECT_DIR" HOST_PWD="$PROJECT_DIR" docker compose up -d\n'
        '      status=$?\n'
        '    elif command -v docker-compose >/dev/null 2>&1; then\n'
        '      echo "Starting SiGMaR Docker stack with docker-compose..."\n'
        '      PWD="$PROJECT_DIR" HOST_PWD="$PROJECT_DIR" docker-compose up -d\n'
        '      status=$?\n'
        '    else\n'
        '      echo "Docker Compose is not installed or not available on PATH."\n'
        '      status=1\n'
        '    fi\n'
        '  fi\n'
        '  stack_status="${status:-1}"\n'
        '  if [ "$stack_status" -eq 0 ]; then\n'
        f'    echo "Startup page will redirect to {APP_URL} when the app is ready."\n'
        '  fi\n'
        '  status="$stack_status"\n'
        '  echo "Exit status: $status"\n'
        '} >> "$LOG_FILE" 2>&1\n'
        'if [ "$status" -ne 0 ]; then\n'
        '  /usr/bin/osascript -e "display dialog \\"SiGMaR cannot start. Is Docker active? Check log file in $LOG_FILE\\" buttons {\\"OK\\"} default button \\"OK\\" with icon caution" >/dev/null 2>&1 || true\n'
        'fi\n'
        'exit "$status"\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)

    icon_file = create_macos_icon(app_bundle)
    icon_key = f"""
    <key>CFBundleIconFile</key>
    <string>{icon_file.stem}</string>""" if icon_file else ""

    (contents / "Info.plist").write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>{APP_NAME}</string>{icon_key}
    <key>CFBundleIdentifier</key>
    <string>org.sigmar.launcher</string>
    <key>CFBundleName</key>
    <string>{APP_NAME}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
</dict>
</plist>
""",
        encoding="utf-8",
    )
    return app_bundle


def create_shortcut():
    ensure_runtime_dirs()
    cmd = launcher_command()
    system = platform.system().lower()

    if system.startswith("win"):
        desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
        desktop.mkdir(parents=True, exist_ok=True)
        shortcut = desktop / f"{APP_NAME}.bat"
        shortcut.write_text(
            "@echo off\r\n"
            f"{cmd} run\r\n",
            encoding="utf-8",
        )
        return shortcut

    if system == "darwin":
        return create_macos_app()

    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    launcher = desktop / f"{APP_NAME}.sh"
    launcher.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"{cmd} run\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)

    shortcut = desktop / f"{APP_NAME}.desktop"
    shortcut.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Launch the SiGMaR web app\n"
        f"Exec={launcher}\n"
        f"Icon={LOGO_FILE if LOGO_FILE.exists() else 'web-browser'}\n"
        "Terminal=false\n"
        "Categories=Science;Biology;Utility;\n",
        encoding="utf-8",
    )
    shortcut.chmod(0o755)
    return shortcut


def open_app():
    try:
        webbrowser.open(APP_URL, new=2)
    except Exception:
        print(f"Open this URL in your browser: {APP_URL}")


def start_stack():
    ensure_docker_ready()
    compose_cmd = detect_compose_cmd()
    print("Starting SiGMaR Docker stack...")
    env = os.environ.copy()
    env["PWD"] = str(PROJECT_DIR)
    env["HOST_PWD"] = str(PROJECT_DIR)
    subprocess.run(compose_cmd + ["up", "-d"], cwd=str(PROJECT_DIR), env=env, check=True)
    return compose_cmd


def load_images_if_present():
    load_image(APP_IMAGE)
    load_image(MODELS_IMAGE)


def install():
    print("Installing SiGMaR launcher...")
    load_images_if_present()
    shortcut = create_shortcut()
    print(f"Launcher ready. Shortcut created at: {shortcut}")
    print("Use the shortcut to start the Docker stack and open the app.")


def run():
    start_stack()
    open_app()


def main():
    parser = argparse.ArgumentParser(description="SiGMaR launcher")
    try:
        parser.add_argument("mode", nargs="?", choices=["install"], default="install")
        parser.parse_args()
        install()
    # try:
    #     if args.run_flag or args.mode == "run":
    #         run()
    #     else:
    #         install()
    except Exception as exc:
        print(f"SiGMaR launcher failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
