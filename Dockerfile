FROM python:3.12-slim

# ffmpeg/ffprobe: el backend los invoca por subprocess para cortar, convertir
# y exportar clips (ver main.py). yt-dlp además necesita ffmpeg para remuxear.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY index.html .
COPY prompts.json .
COPY teaser_templates.json .

# Cloud Run inyecta $PORT (default 8080) y espera que el proceso escuche ahí.
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
