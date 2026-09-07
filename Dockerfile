FROM python:3.12.14-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd --gid 10001 minamix \
    && useradd --uid 10001 --gid minamix --no-create-home --shell /usr/sbin/nologin minamix

COPY --chown=minamix:minamix . .

USER minamix

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 CMD ["sh", "-c", "test -f /tmp/minamix-ready && test $(find /tmp/minamix-ready -mmin -1 -print | wc -l) -eq 1"]

CMD ["python", "main.py"]
