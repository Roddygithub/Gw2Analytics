# ---------------------------------------------------------------------------
# Repository-owned MinIO image.
#
# WHY THIS EXISTS: `minio/minio` is no longer pullable from any registry —
# the Docker Hub repository was deleted (2026-09-11), quay.io denies anonymous
# pull for it, and dl.min.io/server/ returns HTTP 410. MinIO Community Edition
# is source-only since minio/minio was archived (2026-04-25), but the official
# GitHub Release for each pinned tag still ships the upstream-built binary
# together with a published `.sha256sum`.
#
# So this builds a thin Debian image around that binary and verifies its
# SHA-256 *during the build*: `sha256sum -c -` fails the build on any
# mismatch, which means a `gw2a-minio:<release>` tag can only ever contain the
# expected bytes. Nothing is downloaded at run time.
#
# UPGRADING: change MINIO_RELEASE and the two per-arch hashes below (take them
# from that release's `minio.linux-<arch>.<release>.sha256sum` assets), then
# `docker compose build minio`.
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim

# Exact upstream release tag from github.com/minio/minio.
ARG MINIO_RELEASE=RELEASE.2025-09-07T16-13-09Z

# Declared WITHOUT a default: BuildKit then sets it to the build platform
# (arm64 on a plain `docker build --platform linux/arm64`). A default here
# would override that and silently ship an amd64 binary in an arm64 image.
ARG TARGETARCH

# SHA-256 of the official asset `minio.linux-<arch>.<MINIO_RELEASE>`, as
# published by github.com/minio/minio in that release's `.sha256sum` files.
# The amd64 pin is enforced by any build on an amd64 host; the arm64 pin is
# only exercised by an actual arm64 build, so cross-check both hashes against
# the upstream `.sha256sum` assets when upgrading.
ARG MINIO_SHA256_AMD64=7c5bd8512c6e966455b1d198209358b2d191c77a83ab377c4073281065fb855f
ARG MINIO_SHA256_ARM64=5c83cd2cf151717ba0243f73e1c7802ff36e272b67144bdd7f1f7d684fd6f03d

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl; \
    rm -rf /var/lib/apt/lists/*; \
    case "${TARGETARCH}" in \
      amd64) minio_sha="${MINIO_SHA256_AMD64}" ;; \
      arm64) minio_sha="${MINIO_SHA256_ARM64}" ;; \
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fLsS --retry 3 -o /usr/local/bin/minio \
      "https://github.com/minio/minio/releases/download/${MINIO_RELEASE}/minio.linux-${TARGETARCH}.${MINIO_RELEASE}"; \
    echo "${minio_sha}  /usr/local/bin/minio" | sha256sum -c -; \
    chmod 0555 /usr/local/bin/minio; \
    /usr/local/bin/minio --version

# Same ports, data directory and user (root, matching the previous upstream
# image) as the `minio/minio` image this replaces, so existing named volumes
# and the compose healthchecks keep working unchanged.
EXPOSE 9000 9001
VOLUME ["/data"]
ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["server", "/data", "--console-address", ":9001"]
