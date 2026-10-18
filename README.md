# Lab 2 — Docker

## 1. Install the tools

Choose **local Python** to run and test the source, or **Docker** to run the container. You do not need both.

| Tool | Local Python route | Docker route | Installation and version |
| --- | --- | --- | --- |
| Git | Required for cloning | Required for cloning | Install [Git](https://git-scm.com/downloads/); a current Git 2.x release is sufficient. Alternatively, download and extract this repository's ZIP from GitHub. |
| Python | Required | Included in image | Install [Python](https://www.python.org/downloads/) **3.13.x** to match the Dockerfile. The tests were also verified with Python 3.14.7. Include `venv` and `sqlite3`; on Windows, enable the installer option to add Python to PATH. |
| Docker and Compose | Optional | Required | Follow the official [Docker installation guide](https://docs.docker.com/get-started/get-docker/). Docker Desktop includes Compose; on Linux, Docker Engine plus the Compose plugin also works. Use the `docker compose` command (Compose v2 or newer). Start Docker Desktop or the Docker daemon before continuing. |
| Web browser | Required | Required | Use a current Chrome, Firefox, Edge, or Safari with JavaScript enabled. |

The Python server and tests use only the standard library. **No `pip install`, requirements file, Node.js, npm, separate SQLite server, or database account is needed for the local route.** The test suite needs SQLite **3.35.0 or newer** for its schema-migration test (`DROP COLUMN`).

The container uses `python:3.13-slim` and installs **`tzdata==2026.4`** during its build. The page optionally loads **GSAP 3.13.0** and **Motion 11.11.13** from jsDelivr for animation. Internet access is needed to download tools, clone the repository, build/pull images, and load these optional scripts. Native browser animations provide a fallback when the CDN is unavailable.

## 2. Get the lab

Open a terminal (PowerShell on Windows, Terminal on macOS, or a terminal on Linux), then run:

```sh
git clone https://github.com/DADS7305-MLOps-002306229/Lab-2.git
cd Lab-2
```

If you downloaded a ZIP, extract it and open a terminal in the extracted folder containing `README.md`, `app/`, and `Dockerfile`. Run all subsequent commands from this repository root.

## 3. Run locally with Python

### Create an isolated environment

**macOS / Linux:**

```sh
python3 --version
python3 -m venv .venv
source .venv/bin/activate
```

**Windows PowerShell:**

```powershell
py -3.13 --version
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run `.\.venv\Scripts\python.exe` in place of `python` in the commands below; activation is optional. On Debian/Ubuntu, if environment creation reports that `ensurepip` is unavailable, install the `python3-venv` package matching your Python installation and retry.

Confirm the environment and database support:

```sh
python --version
python -c "import sqlite3; print('SQLite', sqlite3.sqlite_version)"
```

### Start the dashboard

For a first run with six example goals:

```sh
python -m app.server --demo
```

Expected terminal message:

```text
One Progress is ready at http://127.0.0.1:8000
```

Keep that terminal running and open **http://127.0.0.1:8000** in your browser. HTTP request log lines in the terminal are normal. Stop the server with **Ctrl+C**.

For an empty dashboard instead, start with:

```sh
python -m app.server
```

The server automatically creates `progress.sqlite3` in the repository root. `--demo` seeds examples only when the cards table is first created; it does not add samples to an existing database or overwrite your goals. To try a separate demo without changing existing data, use a new database filename:

**macOS / Linux:**

```sh
PROGRESS_DB=demo-progress.sqlite3 python -m app.server --demo
```

**Windows PowerShell:**

```powershell
$env:PROGRESS_DB = "demo-progress.sqlite3"
python -m app.server --demo
```

To change the port, use `python -m app.server --port 8080` and open http://127.0.0.1:8080. The local process uses your operating system's timezone. Set the OS timezone appropriately before checking scheduled updates.

## 4. Run with Docker Compose

Host Python is unnecessary for this route. Confirm Docker is installed and running:

```sh
docker --version
docker compose version
docker info
```

### Build the lab image locally

This route does not depend on a published GHCR package being available:

```sh
docker build -t one-progress:lab2 .
```

Create a file named **`.env`** in the repository root using a text editor, with exactly:

```dotenv
IMAGE=one-progress:lab2
PORT=8000
TZ=America/New_York
```

Then run:

```sh
docker compose config
docker compose up -d
docker compose ps
docker compose logs app
```

Open **http://127.0.0.1:8000**. A successful deployment shows the service running, eventually marked **healthy**, and a log message containing `One Progress is ready at http://0.0.0.0:8000`. The health check runs every 30 seconds, so the healthy status may take a short time to appear. Use `127.0.0.1` in the browser; `0.0.0.0` is the container's listening address.

The container starts with an **empty dashboard** because its command does not include `--demo`. Four calendar widgets and the “No active progress” message are expected until you add a goal.

Compose runs the app as UID/GID `10001:10001`, exposes the port only on the host's loopback interface, and stores SQLite data at `/data/progress.sqlite3` in the named `progress-data` volume (normally prefixed with the Compose project name). The Dockerfile creates `/data` with ownership for this user.

Stop the service with:

```sh
docker compose down
```

Start it again with `docker compose up -d`; your goals should still be present. **Do not use `docker compose down -v` unless you intend to delete the stored goals.** Local Python databases and the Compose database are separate.

### Use a published GHCR image instead

If the workflow has published the repository's package, replace the `IMAGE` line in `.env` with:

```bash
docker pull ghcr.io/dads7305-mlops-002306229/lab-2:sha-99fdccb54ad2c5f2281d7dee56578c79788b35a7
```

Then in docker desktop run the image and add the following parameters - 

Container Name: Lab-2
Ports: 40000:8000/tcp
Volumes: [Your local host directory]:/data
TZ: America/New_York

For a reproducible submission, use the exact `:sha-<full-commit-sha>` image reference printed in the successful Actions run's summary instead of `:latest`. The repository's package visibility and publication status must allow the pull. For a private package, authenticate using `docker login ghcr.io -u YOUR_GITHUB_USERNAME` and enter a token with package read access at the password prompt. If the image is unavailable, use the local build instructions above.
