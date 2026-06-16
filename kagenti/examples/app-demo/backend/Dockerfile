FROM python:3.11-slim@sha256:9a7765b36773a37061455b332f18e265e7f58f6fea9c419a550d2a8b0e9db834 AS builder

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir uv==0.5.11 && \
    uv pip compile pyproject.toml --generate-hashes -o requirements.txt && \
    uv pip install --system --no-cache -r requirements.txt
COPY app/ app/

FROM python:3.11-slim@sha256:9a7765b36773a37061455b332f18e265e7f58f6fea9c419a550d2a8b0e9db834

RUN useradd --create-home appuser
WORKDIR /home/appuser

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY --from=builder /build/app app/

USER appuser
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
