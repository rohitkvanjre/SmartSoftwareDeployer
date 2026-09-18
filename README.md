# Smart Software Deployer

A Windows master/slave software deployment system for pushing application installs, updates, and remote management commands across every PC in a LAN — built to replace manual, pendrive-based software installation in shared computer labs.

Two single-file installers (`master.exe` and `slave.exe`) are all that's needed to get a full deployment fleet running. No manual configuration, shared tokens, or file copying required — everything an admin needs is handled by the installers themselves.

---

## Table of Contents

- [Why This Exists](#why-this-exists)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Usage](#usage)
- [Security](#security)
- [Project Structure](#project-structure)
- [License](#license)

---

## Why This Exists

Institutional computer labs frequently need the same set of applications installed, updated, or removed across dozens of machines. Commercial deployment suites (SCCM, PDQ Deploy, etc.) solve this well, but are often out of reach for smaller institutions due to licensing cost and infrastructure requirements (domain controllers, dedicated servers, paid support).

Smart Software Deployer provides a lightweight, self-contained alternative: one admin machine (the **Master**) can discover, install software on, and manage every lab PC (the **Slave** agents) over a standard LAN — wired or Wi-Fi — with zero third-party infrastructure.

## Key Features

**Deployment**
- Silent install/uninstall of `.exe` and `.msi` packages, individually or in bulk across selected nodes or entire groups
- Automatic installer-type detection (NSIS, Inno Setup, InstallShield, WiX Burn) — deploys most software silently without ever needing to hand-configure silent-install flags
- Hybrid file transfer: direct socket transfer for small batches, automatic fallback to FTP for large-scale rollouts
- Content-hash verification on every transfer, so a stale cached file is never mistaken for the version currently being pushed
- Scheduled deployments and remote agent self-update (with automatic backup/rollback if an update fails to start)

**Remote Management & Monitoring**
- Live dashboard with fleet-wide status, deployment outcome breakdown, and per-node history
- Full software inventory per machine, refreshed on demand
- Remote screenshot capture, remote command/PowerShell script execution, and broadcast messaging to logged-in users
- Remote power control (shutdown / restart / sleep) for selected nodes or groups
- Policy-based compliance engine — define "must have" / "must not have" software rules per group, with automatic detection and remediation

**Reliability**
- UDP broadcast auto-discovery of the Master on the local network, with a manual-IP fallback for networks that block broadcast traffic (e.g. Wi-Fi client isolation)
- Slave agent runs as a genuine Windows Service (auto-starts on boot, auto-reconnects on network loss)
- Companion tray application for the logged-in user, used to bridge operations (like screenshots) that a Session-0 Windows Service cannot perform directly

**Security**
- All master↔slave traffic encrypted with TLS (self-signed certificates generated automatically per machine, no OpenSSL dependency)
- Shared-secret authentication between master and every slave
- Password hashing via PBKDF2 for master admin accounts
- Parameterized database queries and list-based subprocess execution throughout (no shell/SQL injection surface)

## Architecture

```
                 ┌─────────────────────────┐
                 │         Master          │
                 │  (Admin control panel)  │
                 └───────────┬─────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │ UDP Broadcast        │ TCP + TLS            │ TCP (file transfer)
        │ (discovery)          │ (control channel)     │
        ▼                     ▼                       ▼
┌───────────────┐    ┌───────────────┐        ┌───────────────┐
│  Slave Agent   │    │  Slave Agent   │  ...   │  Slave Agent   │
│ (Windows Svc)  │    │ (Windows Svc)  │        │ (Windows Svc)  │
└───────────────┘    └───────────────┘        └───────────────┘
        │
        ▼
┌───────────────┐
│  Tray App      │  (runs in the logged-on user's session;
│ (per user)     │   relays screenshot requests the Service
└───────────────┘   can't fulfill itself — Session 0 isolation)
```

- **Master**: a Tkinter desktop application that discovers slaves, dispatches commands, and tracks fleet state in a local SQLite database.
- **Slave**: a Windows Service running as `LocalSystem`, always on, that connects back to the Master, executes commands, and reports status/inventory.
- **Tray App**: a small per-user companion process (auto-starts at logon) that fulfills the one class of operation a background service structurally cannot — anything requiring an interactive desktop, such as capturing a screenshot.

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.13 |
| Master GUI | Tkinter (custom dark theme, Canvas-based dashboard widgets) |
| Windows Service integration | `pywin32` |
| Cryptography / TLS | `cryptography`, Python `ssl` |
| System info & networking | `psutil` |
| Imaging | `Pillow` |
| Tray icon | `pystray` |
| Database | SQLite |
| Packaging | PyInstaller (onedir builds) |
| Installers | Inno Setup 6 |

## Getting Started

### For lab administrators (recommended)

No Python installation or source setup required.

1. Download `master.exe` and run it on the admin/control PC. It generates its own TLS certificate, sets up the local database, and creates the shared authentication token automatically.
2. Download `slave.exe` and run it on every lab PC that should be managed. It registers itself as a Windows Service, configures the Windows Firewall automatically, and starts on its own.
3. Slaves discover the Master automatically over the LAN. If your network blocks broadcast traffic, the slave installer offers an optional field to enter the Master's IP address directly.
4. Log in to the Master application and your slaves will appear as they come online.

### For developers (running from source)

**Prerequisites:** Python 3.13+, Windows 10/11, Inno Setup 6 (only needed for building installers)

```bash
git clone https://github.com/rohitkvanjre/SmartSoftwareDeployer.git
cd Smart-Software-Deployer
pip install -r requirements.txt
```

Run the master from source:
```bash
python -m master
```

Run the slave from source (as an interactive console, for development):
```bash
python -m slave
```

To build the distributable installers yourself:
```bash
pyinstaller installer_build/master.spec --distpath installer_build/dist --workpath installer_build/work
pyinstaller installer_build/slave.spec --distpath installer_build/dist --workpath installer_build/work
# then compile installer_build/MasterSetup.iss and SlaveSetup.iss with Inno Setup 6
```

## Usage

1. **Add software to the catalog** — drop installer files into the Master's `installers` folder (or use the in-app catalog editor) so they're available to push.
2. **Select target nodes** — pick individual machines or a whole group from the node list.
3. **Deploy** — choose "Install from Catalog," select one or more applications, and the Master handles the rest: transfer, integrity verification, silent install, and status reporting back in real time.
4. **Monitor** — the Dashboard tab gives a live view of fleet health and recent deployment outcomes; the Audit Log records every action taken.

## Security

This project treats a lab network as an untrusted environment by default:

- Every control-channel connection is authenticated with a shared token and encrypted with TLS.
- Admin credentials are never stored in plaintext — passwords are hashed with PBKDF2 and a per-user salt.
- All subprocess execution uses argument lists (never shell strings built from untrusted input), eliminating shell-injection risk.
- Database access is fully parameterized, eliminating SQL-injection risk.

## Project Structure

```
├── master/              # Master application (GUI, networking, database, auth)
├── slave/               # Slave agent (Windows Service, tray app, task execution)
├── installer_build/     # PyInstaller specs and Inno Setup scripts for both installers
└── installers/          # Sample/staged installer files for the deployment catalog
```

## License

This project is distributed for educational and portfolio purposes. Contact the repository owner regarding reuse or licensing terms.
