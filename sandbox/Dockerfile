FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN useradd --create-home --uid 10001 evodev

RUN pip install --no-cache-dir "pytest==9.1.1"

WORKDIR /workspace
USER evodev

CMD ["python", "--version"]
