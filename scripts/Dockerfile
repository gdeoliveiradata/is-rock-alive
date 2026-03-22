# Stage 1: install dependencies into a virtual env
FROM python:3.10-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Stage 2: minimal runtime image
FROM python:3.10-slim

# orjson needs liblzma at runtime for nothing here, but tar.xz
# extraction needs the xz binary (part of xz-utils in slim already).
# No extra packages needed — slim includes what we need.

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY load_dump.py .

ENTRYPOINT ["python", "load_dump.py"]
