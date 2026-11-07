FROM python:3.13-slim

# La fábrica: misma pila de dependencias del .venv del host (pin exacto via freeze)
# + ffmpeg (composición final, mezcla -14 LUFS, zoompan) + tesseract (OCR de cutout).
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tesseract-ocr \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /home/facu && chown 1000:1000 /home/facu

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# factoryd se ejecuta desde el volumen del repo (montado en /app) para que las
# ediciones en caliente no requieran rebuild:
#   command: python /app/docker/factory/factoryd.py
