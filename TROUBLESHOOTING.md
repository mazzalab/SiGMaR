# SiGMaR Troubleshooting (macOS / Windows / Linux)

This file collects known installation and startup issues for all three operating systems, with cause and fix for each. It merges the per-OS "Common issues" chapters of `Installation_Guide_SiGMaR.pdf` and the former `TROUBLESHOOTING_LINUX.md`, kept in one place so the README can link to a single document.

Jump to: [macOS](#macos) · [Windows](#windows) · [Linux](#linux) · [Installing Docker](#appendix--installing-docker)

Quick check, any OS:

```bash
docker info   # Docker daemon running?
docker ps     # SiGMaR container running (look for sigmar_container)?
```

Regardless of OS, SiGMaR is used from the browser at `http://localhost:8060`. If it does not open automatically, open that address manually. To shut it down, run `docker compose down` from a terminal in the SiGMaR installation folder (Docker Desktop itself can stay running).

---

## macOS

**Launcher log** (check this first for any macOS issue):

```bash
tail -n 80 ~/Library/Logs/SiGMaR/launcher.log
```

### "App from an unidentified developer" prevents opening

**Cause:** Gatekeeper blocks apps that are not signed/notarized by Apple.

**Fix:** System Settings → Privacy & Security → click "Open Anyway" next to the message about SiGMaR, then try opening `Install SiGMaR.app` (or `SiGMaR.app`) again.

### The app does not start / the page does not load

**Cause:** Docker Desktop is not running, or the Docker engine has not finished starting yet.

**Fix:** open Docker from Applications and wait for the whale icon to become steady, then retry. Check the log shown above.

### Docker Desktop is not installed where SiGMaR expects it

**Cause:** SiGMaR looks for Docker Desktop at the standard path `/Applications/Docker.app`. If it was installed elsewhere, the launcher cannot start it automatically.

**Fix:** reinstall Docker Desktop by dragging the app into Applications (the default path proposed by Docker's `.dmg` installer).

### The first launch is very slow

**Cause:** on the first launch, Docker must finish loading the included images (several GB); subsequent launches are much faster.

**Fix:** wait for it to finish without closing the Terminal/launcher window.

---

## Windows

**Launcher log** (check this first for any Windows issue):

```powershell
Get-Content "$env:LOCALAPPDATA\SiGMaR\launcher.log" -Tail 80
```

### Docker Desktop reports "WSL 2 installation is incomplete" or does not start

**Cause:** virtualization is disabled in the BIOS/UEFI, or the WSL2 components are not yet enabled in Windows.

**Fix 1 — check whether virtualization is enabled:**
- Open Task Manager (Ctrl+Shift+Esc) → Performance tab → CPU: "Virtualization: Enabled" should appear in the bottom right.
- Alternatively, from PowerShell: `systeminfo` and look for "Virtualization Enabled In Firmware: Yes" in the Hyper-V requirements section.

**Fix 2 — if it is disabled, enable it from the BIOS/UEFI:**
- Restart the PC and enter the BIOS/UEFI (key varies by manufacturer: Del, F2, F10, or Esc during startup — check the boot screen or the PC manual).
- Look, usually under the Advanced or CPU Configuration section, for an entry called Intel VT-x / Intel Virtualization Technology (Intel CPU) or AMD-V / SVM Mode (AMD CPU).
- Set it to Enabled, save the changes, and exit (typically F10 → confirm).

**Fix 3 — enable the Windows features required for WSL2** (from PowerShell as Administrator):

```powershell
wsl --install
```

If the command is not available, manually enable the two features and restart:

```powershell
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
```

After the restart, set WSL2 as the default version:

```powershell
wsl --set-default-version 2
```

Finally, reopen Docker Desktop and wait until it shows "running".

### The installer does not start or freezes immediately

**Cause:** `SiGMaR-Setup.exe` and `SiGMaR-Setup-1.bin` are not in the same folder, or one of the two has been renamed.

**Fix:** re-download both files, making sure they stay together, without renaming them, in the same folder.

### Windows/antivirus blocks the downloaded file ("Windows protected your PC")

**Cause:** SmartScreen or the antivirus flag an executable that is not widely recognized.

**Fix:** in the SmartScreen window click "More info" then "Run anyway". If the antivirus quarantines `SiGMaR-Setup-1.bin`, add an exception for the download folder before reinstalling.

### Loading the Docker images is very slow or gets stuck

**Cause:** insufficient disk space, or resources (CPU/RAM) assigned to Docker Desktop too low.

**Fix:** make sure at least 30-50 GB are free; increase resources in Docker Desktop → Settings → Resources (recommended: 8-16 GB RAM, 4-8 cores); restart Docker Desktop and repeat the installation.

### Port 8060 is already in use

**Symptom:** the container starts but the browser does not show the dashboard, or `docker compose up` reports a port conflict.

**Check** from PowerShell:

```powershell
netstat -ano | findstr :8060
```

**Fix:** close the process using the port (via the PID shown), or change the exposed port in the `docker-compose.win.yaml` file in the installation folder.

### TMP subtyping method fails on Windows

The TMP subtyping method (based on several external Docker models) could previously fail to complete correctly on Windows, due to a path issue between nested Docker containers. **The problem has been identified and fixed**, and the fix has been verified with a complete, successful run of all TMP models. The fix is included starting with the current Windows installer; if the app is already installed from an older version, reinstall with the latest `SiGMaR-Setup.exe` to get it.

---

## Linux

Distributed as the `sigmar_1.0_amd64.deb` package (Debian/Ubuntu-based distributions).

Quick prerequisite check:

```bash
docker info
docker compose version || docker-compose version
```

### `apt install` reports a permission error during download/cache

Typical symptom:

```text
N: Download is performed unsandboxed as root as file '/home/user/Desktop/sigmar_1.0_amd64.deb' couldn't be accessed by user '_apt'. - pkgAcquire::Run (13: Permission denied)
```

**Cause:** `apt` reads the local `.deb` as the system user `_apt`, which does not have permission to traverse folders with restricted permissions (e.g. `~/Desktop` at `700`).

**Is it blocking? No.** It is only a warning during apt's cache phase: the unpack and `Setting up` steps of the package proceed regardless. Verify with:

```bash
dpkg -l | grep sigmar
```

If `ii  sigmar  1.0  amd64` appears, the package installed correctly despite the warning.

**Fix to avoid the warning in the future:**

```bash
cp ~/Desktop/sigmar_1.0_amd64.deb /tmp/ && sudo apt install /tmp/sigmar_1.0_amd64.deb
```

or open the permissions on the file before installing:

```bash
chmod 644 ~/Desktop/sigmar_1.0_amd64.deb
sudo apt install ~/Desktop/sigmar_1.0_amd64.deb
```

### No icon created on the Desktop after installation

**Cause:** the `.deb` package installs the application entry in `/usr/share/applications/` (system application menu), not a direct shortcut on the Desktop.

**Fix:** copy the `.desktop` file to the Desktop manually.

```bash
find /usr/share/applications -iname "*sigmar*"
cp /usr/share/applications/sigmar.desktop ~/Desktop/
chmod +x ~/Desktop/sigmar.desktop
```

On GNOME/Nautilus, after copying you may need to right-click the file on the Desktop → **Allow Launching**, since unsigned `.desktop` launchers are blocked by default for security.

### Startup page does not open: "Access to the file was denied" on `startup.html`

**Symptom:** the browser shows `ERR_ACCESS_DENIED` for a file such as:

```text
file:///home/user/.local/state/sigmar/startup.html
```

**Step-by-step diagnosis:**

1. Verify Docker is running and the container is up:

   ```bash
   docker ps
   ```

   If nothing shows up, the problem is upstream: Docker hasn't started. Start it with `sudo systemctl start docker` and relaunch the app.

2. Verify the file actually exists and permissions are correct:

   ```bash
   ls -la ~/.local/state/sigmar/startup.html
   ```

3. Verify the whole folder chain (the user opening the file needs `x` at every level):

   ```bash
   namei -l ~/.local/state/sigmar/startup.html
   ```

If both the file and the permission chain look correct for the user but the error persists, the most likely cause is **not a Linux permissions problem**, but **browser sandboxing**.

**Most common real cause: browser installed as a snap.** Firefox and Chromium via `snap` run in a confined environment that denies access to paths outside the snap's whitelist (`~/.local/state` is typically not included), even when POSIX permissions are correct.

Check whether the browser is a snap:

```bash
snap list 2>/dev/null | grep -iE "chrom|firefox"
```

**Fix:**

- Quick confirmation test: `xdg-open ~/.local/state/sigmar/startup.html`. If the page opens correctly from the terminal but not from the app, SiGMaR's automatic launch is probably using a different browser profile/path that still ends up inside the sandbox.
- Definitive fix: install a version of the browser **not confined by snap** (native `.deb` package), for example:

  ```bash
  sudo add-apt-repository ppa:mozillateam/ppa
  sudo apt update
  sudo apt install -t 'o=LP-PPA-mozillateam' firefox
  ```

  or for Chromium:

  ```bash
  sudo snap remove chromium
  sudo apt install chromium-browser
  ```

### `docker: permission denied` or error on `docker.sock`

**Cause:** the user is not part of the `docker` group.

**Fix:**

```bash
sudo usermod -aG docker $USER
```

You then need to log out and back in (or restart) for the new group to take effect.

### Port 8060 is already in use

**Symptom:** the container starts but the browser does not show the dashboard, or `docker compose up` reports a port conflict.

**Check:**

```bash
sudo ss -ltnp | grep 8060
```

**Fix:** close the process using the port, or change the exposed port in the project's `docker-compose.yaml`.

### Quick diagnosis summary

```bash
dpkg -l | grep sigmar                        # package installed?
docker info                                  # Docker daemon running?
docker ps                                    # SiGMaR container running?
snap list | grep -iE "chrom|firefox"         # browser sandboxed?
namei -l ~/.local/state/sigmar/startup.html  # permission chain ok?
```

---

## Appendix — Installing Docker

Docker is the engine that runs SiGMaR's containers. It must be installed **before** SiGMaR and must be running every time you want to use the app. Needed only if Docker is not yet installed on the computer.

### Windows

1. System requirement: 64-bit Windows 10/11 with virtualization enabled in the BIOS/UEFI. Docker Desktop requires the WSL2 subsystem (see the [WSL2 fix](#docker-desktop-reports-wsl-2-installation-is-incomplete-or-does-not-start) above for the full procedure).
2. Download Docker Desktop for Windows from the official website: `https://www.docker.com/products/docker-desktop/`
3. Run `Docker Desktop Installer.exe` and follow the wizard (recommended WSL2 option, selected by default). Restart the computer when finished if prompted.
4. Start Docker Desktop from the Start menu and wait until the icon in the taskbar shows "Docker Desktop is running".
5. Verify the installation from PowerShell:

   ```powershell
   docker --version
   docker info
   ```

If both commands respond without errors, Docker is ready.

### macOS

1. Download Docker Desktop for Mac from the official website, choosing the correct version for your processor: `https://www.docker.com/products/docker-desktop/` — Apple Silicon (M1/M2/M3/M4) or Intel chip, depending on the Mac in use (check via Apple Menu → About This Mac).
2. Open the downloaded `.dmg` file and drag the Docker icon into the Applications folder.
3. Launch Docker from Applications: on first launch macOS will ask for confirmation and may require the user password to complete the installation of network/virtualization components.
4. Wait for the whale icon in the menu bar to become steady (not animated): this means the Docker engine is running.
5. Verify from Terminal:

   ```bash
   docker --version
   docker info
   ```

**Important path for SiGMaR:** on macOS, SiGMaR expects Docker Desktop to be installed at the standard path `/Applications/Docker.app` — this is the path created automatically by dragging the app into Applications above. If Docker is installed elsewhere, SiGMaR's launcher may not be able to start it automatically.

### Linux

1. On Debian/Ubuntu distributions, install Docker Engine and the Docker Compose plugin using the official convenience script:

   ```bash
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   ```

   Alternatively, follow the apt-based procedure described at `docs.docker.com/engine/install/` for your distribution.

2. Add your user to the `docker` group, to be able to run commands without `sudo`:

   ```bash
   sudo usermod -aG docker $USER
   newgrp docker
   ```

   After this command you may need to log out and back in (or restart) for the new group to take effect.

3. Enable and start the Docker service:

   ```bash
   sudo systemctl enable --now docker
   ```

4. Verify the installation:

   ```bash
   docker info
   docker compose version
   ```

Both commands must respond without errors before installing SiGMaR.
