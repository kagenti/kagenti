FROM quay.io/pdettori/python:3.12-slim
ARG RELEASE_VERSION="main"
COPY --from=ghcr.io/astral-sh/uv:0.6.16 /uv /bin/
WORKDIR /app
COPY . .
RUN uv sync --no-cache --locked --link-mode copy
ENV PRODUCTION_MODE=True \
    RELEASE_VERSION=${RELEASE_VERSION}

USER 1001

CMD ["uv", "run", "--no-sync", "streamlit", "run", "--server.address", "0.0.0.0", "Home.py"]
