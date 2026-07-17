FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /project
COPY pret/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.2.2 && \
    pip install --no-cache-dir numpy==1.26.4
COPY pret /project/pret
COPY 模型1/models /project/模型1/models
COPY 模型1/utils /project/模型1/utils
ENTRYPOINT ["python", "pret/pipeline.py"]
