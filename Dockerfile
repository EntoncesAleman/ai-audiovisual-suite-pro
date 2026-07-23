FROM python:3.12-slim

# ffmpeg/ffprobe: el backend los invoca por subprocess para cortar, convertir
# y exportar clips (ver main.py). yt-dlp además necesita ffmpeg para remuxear.
# curl + unzip: usados solo para instalar deno en la capa siguiente
# (el instalador de deno necesita unzip para extraer el binario descargado).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# deno: yt-dlp lo usa como runtime de JavaScript para resolver los challenges
# de firma que YouTube exige antes de entregar formatos de video reales
# (sin esto, yt-dlp solo consigue miniaturas/imágenes, no video descargable).
ENV DENO_INSTALL=/usr/local
RUN curl -fsSL https://deno.land/install.sh | sh

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
