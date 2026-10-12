# Smart Software Deployer

A Windows master/slave software deployment system for pushing application installs, updates, and remote management commands across every PC in a LAN — built to replace manual, pendrive-based software installation in shared computer labs.

Two single-file installers (`master.exe` and `slave.exe`) are all that's needed to get a full deployment fleet running. Each lab PC joins by entering a short pairing code shown on the master — no configuration files, shared secrets, or project files to copy around.

**[Download the latest release](https://github.com/rohitkvanjre/SmartSoftwareDeployer/releases/latest)**

---

## Table of Contents

- [Why This Exists](#why-this-exists)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Usage](#usage)
- [For Developers](#for-developers)
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
- Code-based pairing: each slave joins with a short, time-limited code and receives its own credential, which can be revoked individually
- Slaves pin the master's certificate, so another machine on the network can't impersonate the master
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

Download `master.exe` and `slave.exe` from the **[latest release](https://github.com/rohitkvanjre/SmartSoftwareDeployer/releases/latest)**. They run on Windows 10 or 11 (64-bit) and need nothing else installed — no Python, no source code.

The installers aren't code-signed, so Windows may show "Windows protected your PC" the first time you run them. Click **More info → Run anyway**.

1. Run `master.exe` on the admin/control PC. It generates its own TLS certificate and sets up the local database. On first launch it asks you to set a password for the `admin` account.
2. In the Master, click **Pair New Slaves...**. This opens a 30-minute pairing window and shows a code like `7KQ4-M2XP`.
3. Run `slave.exe` on each lab PC and enter that code when asked. It registers itself as a Windows Service, configures Windows Firewall, pairs with the Master, and starts on its own.
4. Slaves find the Master automatically over the LAN. If your network blocks broadcast traffic (common on Wi-Fi with client isolation), also enter the Master's IP address on the same installer page.

To avoid typing the code on every PC, install silently from a batch file or network share. The pairing dialog shows this command with your code filled in:

```bat
slave.exe /VERYSILENT /PAIRCODE=7KQ4-M2XP
```

Add `/MASTERIP=192.168.1.10` if broadcast discovery doesn't work on your network.

**How pairing stays secure.** The code is a one-time key, not the credential itself. Once a slave proves it knows the code, the Master gives that slave its own long random token, which is what authenticates it from then on. The code stops working when the window closes, and the Master stops accepting guesses from a machine after a few wrong attempts. The Master also proves it knows the code before the slave trusts it, and the slave then pins the Master's certificate, so no other machine can pose as the Master.

**Managing pairings.**
- To re-pair a PC, open a new pairing window and run `slave.exe` on it again with the new code. Its settings are kept.
- To remove a PC (for example, a stolen or retired one), right-click it in the node list and choose **Revoke Pairing...**. It's disconnected immediately and can't reconnect until it's paired again.
- The Master's certificate is created once and kept. If you reinstall the Master from scratch (deleting its data), every slave must be paired again.

## Usage

1. **Add software to the catalog** — drop installer files into the Master's installers folder so they're available to push. For an installed Master that's `C:\ProgramData\SmartSoftwareDeployer\Master\installers`; when running from source it's the `installers` folder at the repository root (create it if it doesn't exist).
2. **Select target nodes** — pick individual machines or a whole group from the node list.
3. **Deploy** — choose "Install from Catalog," select one or more applications, and the Master handles the rest: transfer, integrity verification, silent install, and status reporting back in real time.
4. **Monitor** — the Dashboard tab gives a live view of fleet health and recent deployment outcomes; the Audit Log records every action taken.

## For Developers

Only needed if you want to run or change the code yourself. To just use the software, download the installers from the [latest release](https://github.com/rohitkvanjre/SmartSoftwareDeployer/releases/latest) instead.

### Running from source

**Prerequisites:** Python 3.13+ and Windows 10/11.

```bash
git clone https://github.com/rohitkvanjre/SmartSoftwareDeployer.git
cd SmartSoftwareDeployer
pip install -r requirements.txt
```

Create the two local config files from the templates included in the repository (the real files are ignored by git, so they don't exist after a fresh clone):

```bash
copy master\data\config.json.example master\data\config.json
copy slave\config.json.example slave\config.json
```

Run the master:

```bash
python -m master.main
```

In the master, click **Pair New Slaves...** to get a pairing code. Then run the slave as a console process (useful for development, since it logs to the terminal instead of running as a Windows Service), passing the code the first time:

```bash
python -m slave --pair 7KQ4-M2XP
```

After it has paired once, start it with plain `python -m slave`. Its credentials are kept in `slave/credentials/`, which git ignores.

## Security

This project treats a lab network as an untrusted environment by default:

- All master↔slave traffic is encrypted with TLS. Slaves pin the master's certificate when they pair, so another machine on the network can't pose as the master.
- Each slave authenticates with its own random token, issued during pairing. The master stores only a hash of it, and any single slave can be revoked without affecting the others. On the slave, the token is readable only by SYSTEM and Administrators, not by the user logged on to the lab PC.
- Pairing codes are short-lived and can't be guessed online (the master locks out a machine after a few wrong attempts) or cracked offline (each guess costs an scrypt computation).
- Admin credentials are never stored in plaintext — passwords are hashed with PBKDF2 and a per-user salt.
- All subprocess execution uses argument lists (never shell strings built from untrusted input), eliminating shell-injection risk.
- Database access is fully parameterized, eliminating SQL-injection risk.

## Project Structure

```
├── master/              # Master application (GUI, networking, database, auth)
├── slave/               # Slave agent (Windows Service, tray app, task execution)
├── common/              # Pairing protocol shared by the master and the slave
├── installer_build/     # PyInstaller specs, Inno Setup scripts, and build_installers.py
└── requirements.txt     # Python dependencies
```

## License

This project is distributed for educational and portfolio purposes. Contact the repository owner regarding reuse or licensing terms.
