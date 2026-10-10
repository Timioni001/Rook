# Single container: FastAPI backend + statically exported dashboard on port 8000.
FROM public.ecr.aws/docker/library/node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY web/ ./
RUN STATIC_EXPORT=1 npx next build

FROM public.ecr.aws/docker/library/python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY rook/ rook/
COPY --from=web /web/out web/out
RUN useradd --create-home --uid 10001 keywarden && mkdir /data && chown keywarden /data
USER keywarden
ENV KEYWARDEN_DB=/data/keywarden.db PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "rook.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
