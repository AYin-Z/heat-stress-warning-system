FROM python:3.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/informer

WORKDIR /app

ARG INSTALL_TORCH=true

COPY deploy/model-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
# Use the CPU wheel repository. Installing the default PyPI wheel can pull
# several gigabytes of CUDA runtime that this deployment does not use.
RUN if [ "$INSTALL_TORCH" = "true" ]; then \
      pip install --no-cache-dir torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu; \
    fi

COPY deploy/model-service/app /app/app
COPY deploy/tests /app/tests
COPY 模型1/models /app/informer/models
COPY 模型1/utils /app/informer/utils

RUN useradd --system --uid 10001 --create-home appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
