# Quality Engineer Companion — overlap-only image (no MiniLM / sentence-transformers).
# Never bake GOOGLE_API_KEY. Pass it at runtime if you want Gemini.

FROM node:22-alpine AS ui
WORKDIR /ui
COPY qe-console/package.json qe-console/package-lock.json ./
RUN npm ci
COPY qe-console/ ./
RUN npm run build

FROM python:3.11-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COMPANION_RERANK=0 \
    COMPANION_UI_DIST=/app/qe-console/dist
COPY pyproject.toml README.md ./
COPY companion ./companion
RUN pip install --no-cache-dir .
COPY --from=ui /ui/dist /app/qe-console/dist
EXPOSE 8000
CMD ["sh", "-c", "python -m companion serve --host 0.0.0.0 --port ${PORT:-8000}"]
