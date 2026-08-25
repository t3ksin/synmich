<div align="center">

<img src="docs/synmich-logo.png" alt="synmich" width="500">

### Migrate Synology Photos to Immich — or a local backup — properly: albums, sharing and all.

![version](https://img.shields.io/badge/version-2.1.1-1D9E75)
![license](https://img.shields.io/badge/license-MIT-blue)
![python](https://img.shields.io/badge/python-3.9%2B-3776AB)
![platform](https://img.shields.io/badge/GUI%20%2B%20CLI-1e2a36)
![stars](https://img.shields.io/github/stars/t3ksin/synmich?style=social)

<br>

<img src="docs/screenshots/gui-immich.png" alt="synmich — the graphical app" width="880">

</div>

---

## 🎯 Why synmich

Moving off Synology Photos usually means losing the parts that matter: your **albums**, **who they were shared with**, and the **per-user libraries**. Most tools dump a flat pile of files into one account and call it a day.

Instead, synmich migrates **each Synology user into their own Immich account**, recreates their albums, and preserves shared albums the way Synology had them — mirror the sharing, give everyone their own copy, or skip sharing entirely. Photos are deduplicated by **SHA1**, the run is **resumable**, and your **Synology NAS is never modified** (read-only). Best of all, it ships with a **real graphical app**, not just a CLI.

> Tested in production: **67,844 photos** migrated successfully, every asset validated via SHA1 checksum.

| | immich-go | PhotoMigrator | **synmich** |
| --- | :---: | :---: | :---: |
| Reads the Synology Photos API | ❌ | ✅ | ✅ |
| Multiple Synology users | ❌ | ✅ | ✅ |
| **Shared albums** between users | ❌ | ❌ | ✅ |
| Correct **owner** preserved per photo | ❌ | ❌ | ✅ |
| Synology permissions → Immich roles | ❌ | ❌ | ✅ |
| Synology **Shared Space** | ❌ | ❌ | ✅ |
| **2FA** with remembered device (enter the code once) | ❌ | ❌ | ✅ |
| Graphical interface | ❌ | ✅ web | ✅ desktop |
| License | AGPL-3.0 | GPL-3.0 | MIT |

<sub>Based on each project's README at the time of writing — corrections welcome. Both [immich-go](https://github.com/simulot/immich-go) and [PhotoMigrator](https://github.com/jaimetur/PhotoMigrator) are excellent general-purpose photo movers; synmich is the specialist for multi-user Synology Photos with shared albums.</sub>

---

## 🖥️ The app (start here)

The graphical app is the easiest way to use synmich — one window, dark theme, no command line. Install it via the **Quick start** below, then run `synmich gui`.

**Three operations, as tabs (top-right):**

| Tab | What it does |
| --- | --- |
| **Synology to Immich** | Migrate your Synology Photos (albums + timeline) into Immich — each user into their own account, **keeping the original owners, shared albums and permissions** from Synology |
| **Synology to local** | Download your Synology albums to a folder on this computer (no Immich needed) |
| **Immich Album Manager** | Browse and rename your Immich albums, grouped per user |

**Left panel — Settings (always there):**
- **Servers.** Your Synology and Immich addresses (an IP with a port is fine, e.g. `192.168.0.2:5000`).
- **Users / accounts.** Managed per tab — *Synology to Immich* needs a Synology login **plus** an Immich API key per user; *Synology to local* needs only the Synology login. A **Check NAS users** button lists the real users on your NAS (system accounts hidden).
- **Stats / Doctor** at the bottom, and a scoped **Reset…** (progress / 2FA devices / configuration / everything — *never your photos*).

**Running a migration:**
1. Fill in the **Synology** and **Immich** addresses (left panel), then **Add user** (it tests the connection on the spot; 2FA codes are remembered).
2. Pick your options: **All albums** or **Specific albums**, the **shared-albums** mode (`mirror-syno` = keep Synology's sharing, `separate` = a copy per user, `skip`), and whether to include each user's **full timeline**.
3. In *Specific albums*, the list is split into **one sub-tab per user**, with **Check all / Uncheck all**, a live count, and a *shared with …* badge on shared albums.
4. Hit **START MIGRATION** and watch the live counters (uploaded / duplicate / failed), the progress bar and the log. **Pause** or **Stop** any time — it's fully resumable.

> Tip: the window opens at a comfortable size and adapts to smaller screens. Everything is read-only on the Synology side.

---

## ⚡ Quick start

**Prerequisites** — Linux, macOS or Windows · **Python 3.9+** · a reachable
Synology Photos instance · an Immich server with one API key per user.

```bash
git clone https://github.com/t3ksin/synmich.git
cd synmich
python3 -m venv .venv && source .venv/bin/activate   # Windows: py -m venv .venv && .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e ".[gui]"
synmich gui                                          # 👉 launch the app
```

**Prefer the terminal?** Run `synmich init` instead — an interactive setup wizard that then starts the migration.

> Re-activate the venv (`source .venv/bin/activate`) in each new terminal. If
> `synmich` isn't found, run **`python -m synmich gui`**.

<details>
<summary><b>Troubleshooting</b> — macOS, Windows & common errors</summary>

- **macOS — grey / blank window:** CustomTkinter needs **Tcl/Tk 8.6**, but
  Apple's system Python ships 8.5. Check with
  `python -c "import tkinter; print(tkinter.TkVersion)"`; if it says `8.5`,
  install Python from [python.org](https://www.python.org/downloads/macos/)
  (bundles Tk 8.6) and recreate the venv.
- **`pip` not found / "externally managed" (macOS):** use the python.org
  Python; inside an activated venv `pip` always works.
- **"neither 'setup.py' nor 'setup.cfg' found":** your pip is too old for
  editable installs — `python -m pip install --upgrade pip`, then reinstall.
- **`synmich: command not found`:** activate the venv, or use
  `python -m synmich gui` (or `.venv/bin/synmich gui`).
- **`tkinter` missing (Linux):** `sudo apt install python3-tk` (Debian/Ubuntu)
  or `sudo dnf install python3-tkinter` (Fedora).

</details>

---

## ✨ Features

- 🖥️ **Graphical app** — `synmich gui` opens a dark, beginner-friendly window: add your users, pick your options, hit **Start**, and watch live progress. No command line required.
- 👥 **Multi-user migration** — every Synology user is migrated into *their own* Immich account, in a single run.
- 🤝 **Shared albums, your way** — keep Synology's exact sharing (`mirror-syno`), give each user their own copy (`separate`), or skip sharing (`skip`). Owners and members are preserved either way.
- 🗂️ **Albums + timeline** — bring over the full library, just the albums, or hand-pick specific albums per user.
- 💾 **Local backup** — download a user's Synology albums straight to a folder (Synology → local), no Immich needed.
- 📱 **Live Photos** — the HEIC still and the motion MOV are migrated as a real Immich Live Photo, not a broken `.HEIC`.
- 🔐 **2-factor authentication (2FA)** — if an account uses Synology's 2-step verification, synmich asks for the code **once**, then stores a **trusted device token** (exactly like your browser does) so future runs never prompt again. Tokens stay only on your machine and can be wiped from **Reset → 2FA devices**.
- ♻️ **Resumable & deduplicated** — a checkpoint records every item, and photos already in Immich are matched by **SHA1** and skipped. Stop and re-run any time, no duplicates.
- 🩺 **Doctor** — one command checks your servers, accounts, free disk space and config, with a clear ✓ / ✗ for each.
- 🔒 **Safe by design** — the Synology NAS is only ever **read**, never modified.

---

## ⚙️ Configuration

The wizard writes the config for you (and chains straight into a first migration):

```bash
synmich init
```

Or edit `~/.config/synmich/config.yaml` by hand:

```yaml
synology:
  url: http://192.168.0.2:5000     # IP or host, with port
  verify_ssl: false

immich:
  url: http://192.168.0.2:2283     # IP or host, with port

users:
  - name: jeffrey
    syno_username: jeffrey
    syno_password: "********"
    immich_api_key: "paste-jeffreys-immich-api-key"
  - name: roberta
    syno_username: roberta
    syno_password: "********"
    immich_api_key: "paste-robertas-immich-api-key"

migration:
  include_albums: true
  include_timeline: true
  shared_albums_mode: link         # link (mirror-syno) | duplicate (separate) | ignore (skip)
```

> Config and checkpoint files stay on your machine and are git-ignored — no credentials ever leave your computer.

---

## ⌨️ CLI (for power users)

Prefer the terminal, or scripting / cron? Everything is available on the command line too — including a **full interactive setup wizard** (`synmich init`) that walks you through servers, users and options, plus a **live dashboard** during the migration.

<div align="center">
<img src="docs/screenshots/cli-immich.png" alt="synmich CLI live dashboard" width="860">
</div>

```bash
synmich --help
```

| Command | What it does |
| --- | --- |
| `synmich gui` | Launch the graphical app |
| `synmich init` | Setup wizard, then run the first migration |
| `synmich migrate` | Run the migration (resumable, live dashboard) |
| `synmich migrate --select` | Pick albums in a per-user picker (one tab per user) |
| `synmich doctor` | Full diagnostic: servers, accounts, disk, config |
| `synmich stats` | Checkpoint statistics |
| `synmich users` | List configured users and their status |
| `synmich albums` | List the albums detected on Synology |
| `synmich reset` | Reset the migration checkpoint |
| `synmich config` | Show config paths and validate |

```bash
synmich migrate                 # migrate everything (albums + timeline)
synmich migrate --albums-only   # albums only, skip the timeline
synmich migrate --select        # choose albums, grouped by user
synmich migrate --dry-run       # simulate: nothing downloaded or uploaded
```

> Choosing albums works in both the GUI and the CLI (`--select`). Without it, the CLI migrates everything, optionally filtered by `filters.include_albums_regex` in the config.

---

## 🧭 Architecture

```mermaid
flowchart LR
    subgraph Source
        S[Synology Photos<br/>read-only]
    end
    subgraph synmich
        L[List albums<br/>+ sharing]
        D[Download<br/>+ SHA1]
        U[Upload<br/>+ dedup]
        CP[(Checkpoint)]
    end
    subgraph Destination
        I[Immich<br/>per-user accounts]
        F[Local folder]
    end

    S --> L --> D --> U --> I
    D -.->|backup mode| F
    U <--> CP
    L <--> CP
```

For each user, synmich logs into Synology, enumerates albums and their sharing, downloads originals to a temp area, checksums them, and uploads only what Immich doesn't already have — recording every step in a checkpoint so an interrupted run picks up exactly where it stopped.

---

## 📊 Real-world results

Built to move a real, messy, decade-old library, synmich is validated against it:

- **67,844 photos** migrated successfully
- Every asset **validated via SHA1** before being counted as done
- **0 photos modified or deleted** on the Synology side
- Shared albums preserved with their original owner and members

---

## 🗺️ Roadmap

- [ ] Google Takeout import (bring legacy Google Photos in alongside Synology)
- [ ] Scheduled / incremental sync
- [ ] One-click packaged builds of the GUI (no Python needed)
- [ ] Selective per-album backup presets

Shipped in 2.0: the **GUI**, **local backup**, **shared-album modes**, **2FA device tokens** and a scoped **Reset**.

---

## 🤝 Contributing

```bash
git clone https://github.com/t3ksin/synmich.git
cd synmich
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[gui,dev]"

synmich doctor      # sanity-check your setup
synmich gui         # run the app from source
```

The codebase splits cleanly into `core/` (Synology + Immich clients, the migrator), `ui/` (CLI theming, wizard, album picker), `commands/` (CLI subcommands) and `gui/` (the CustomTkinter app). PRs and issues welcome.

---

## 📄 License

[MIT](LICENSE) © synmich contributors
