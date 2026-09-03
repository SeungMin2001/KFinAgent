# Kronos on RunPod

This project uses one authenticated FastAPI service around the upstream
Kronos-base model. Start with this Docker deployment; do not introduce
Kubernetes until there is measured multi-GPU or multi-service demand.

## You need to do

1. Create a RunPod account and a GPU Pod with at least 16 GB VRAM.
2. Build and push the image from this repository:

   ```bash
   docker build -f services/kronos_api/Dockerfile -t YOUR_REGISTRY/kronos-api:0.1.0 .
   docker push YOUR_REGISTRY/kronos-api:0.1.0
   ```

3. Create a persistent RunPod Pod from that image. Set these secrets in its
   environment configuration, never in the image or Git repository:

   ```env
   KRONOS_API_KEY=long-random-secret
   KRONOS_MODEL_ID=NeoQuasar/Kronos-base
   KRONOS_TOKENIZER_ID=NeoQuasar/Kronos-Tokenizer-base
   KRONOS_DEVICE=cuda:0
   ```

4. Expose port `8000` through RunPod's HTTPS proxy. Restrict inbound access to
   this application's client where possible. Do not expose an unauthenticated
   GPU endpoint.
5. On the TradingAgents side, add these values to `.env`:

   ```env
   KRONOS_API_URL=https://YOUR-RUNPOD-PROXY/v1/forecast
   KRONOS_API_KEY=the-same-long-random-secret
   ```

## Operational rules

- The first request downloads model weights from Hugging Face and is slow.
  Keep the Pod persistent; do not load weights for each request.
- `/healthz` confirms service availability but does not load the model. The
  first forecast is the real model readiness check.
- Start with `samples=3` and a 5-trading-day horizon. More samples cost more
  GPU time and do not automatically improve trading performance.
- Record model id, input end date, and response before using a forecast in an
  agent. Later compare it against realised bars in a walk-forward evaluation.
