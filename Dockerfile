# Build the UI, then run the API and UI from one Python image.
FROM node:22-alpine AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000
COPY requirements.txt .
# Test and screenshot tools are not needed at runtime.
RUN grep -viE '^(pytest|playwright)==' requirements.txt > runtime.txt \
    && pip install --no-cache-dir -r runtime.txt
COPY backend/ backend/
COPY docs/sample-scam-sms.png docs/sample-scam-sms.png
COPY --from=web /app/web/dist web/dist
RUN useradd --create-home app && mkdir -p data models && chown app data models
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["python", "-m", "backend"]
