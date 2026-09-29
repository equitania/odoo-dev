# PostgreSQL with pgvector for the odoodev dev database (PGVECTOR=true in .env).
#
# Built locally by `odoodev docker up` as odoodev-postgres-pgvector:<PG_VERSION>
# on top of the same postgres:<PG_VERSION> image the service uses without it.
#
# Alpine tags (odoodev's default): pgvector is compiled from source. Keeping the
# Alpine/musl base keeps the existing data volume and its collations valid - a
# switch to a Debian (glibc) image would change collation behaviour under the
# existing indexes. $DOCKER_PG_LLVM_DEPS is set by the official Alpine image.
# Debian tags: the postgresql-<major>-pgvector package from apt.postgresql.org,
# which the official Debian image already carries.
ARG PG_VERSION
FROM postgres:${PG_VERSION}
ARG PGVECTOR_VERSION=v0.8.6
RUN set -eux; \
    if command -v apk >/dev/null 2>&1; then \
        apk add --no-cache --virtual .build-deps git build-base $DOCKER_PG_LLVM_DEPS; \
        git clone --branch "$PGVECTOR_VERSION" --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector; \
        make -C /tmp/pgvector OPTFLAGS=""; \
        make -C /tmp/pgvector install; \
        rm -rf /tmp/pgvector; \
        apk del .build-deps; \
    else \
        apt-get update; \
        apt-get install -y --no-install-recommends "postgresql-${PG_MAJOR}-pgvector"; \
        rm -rf /var/lib/apt/lists/*; \
    fi
