FROM python:3.12-slim

LABEL org.opencontainers.image.title="synmich"
LABEL org.opencontainers.image.description="Synology Photos → Immich migration tool"
LABEL org.opencontainers.image.source="https://github.com/t3ksin/synmich"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY pyproject.toml README.md ./
COPY synmich ./synmich

RUN pip install --no-cache-dir .

# Volume for config + checkpoint
VOLUME ["/config", "/data"]
ENV XDG_CONFIG_HOME=/config

WORKDIR /data

ENTRYPOINT ["synmich"]
CMD ["--help"]
