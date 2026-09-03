# RunPod-compatible GPU inference image. Kubernetes is intentionally not part
# of this first deployment: one persistent GPU pod is simpler to secure and
# operate while request volume is low.
FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    KRONOS_DEVICE=cuda:0 \
    KRONOS_MODEL_ID=NeoQuasar/Kronos-base \
    KRONOS_TOKENIZER_ID=NeoQuasar/Kronos-Tokenizer-base

WORKDIR /srv
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git clone https://github.com/shiyu-coder/Kronos.git /opt/kronos \
    && cd /opt/kronos && git checkout 67b630e67f6a18c9e9be918d9b4337c960db1e9a

COPY services/kronos_api/requirements.txt /srv/requirements.txt
RUN pip install -r /srv/requirements.txt
COPY services/kronos_api/app /srv/app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
