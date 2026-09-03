ARG POSTGRES_MAJOR=16
FROM postgres:${POSTGRES_MAJOR}-bookworm

ARG POSTGRES_MAJOR

RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends ca-certificates \
    && sed -i 's|http://|https://|g' \
        /etc/apt/sources.list.d/debian.sources \
        /etc/apt/sources.list.d/pgdg.list \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        "postgresql-${POSTGRES_MAJOR}-postgis-3" \
        "postgresql-${POSTGRES_MAJOR}-postgis-3-scripts" \
    && rm -rf /var/lib/apt/lists/*
