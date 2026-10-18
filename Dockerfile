FROM python:3.13-slim

# Install timezone data in the image; the desired timezone is set by Compose.
RUN python -m pip install --no-cache-dir tzdata==2026.4 \
    && python -c "import os, shutil, tzdata; from pathlib import Path; shutil.copytree(Path(tzdata.__file__).parent / 'zoneinfo', '/usr/share/zoneinfo', dirs_exist_ok=True); Path('/data').mkdir(exist_ok=True); os.chown('/data', 10001, 10001)"

WORKDIR /app
ENV PROGRESS_DB=/data/progress.sqlite3
COPY app/ ./app/

EXPOSE 8000

CMD ["python", "-m", "app.server", "--host", "0.0.0.0"]
