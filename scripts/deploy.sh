#!/usr/bin/env bash
# Deploys Shot Deadline to Cloud Run. Gemini via Vertex AI; Grafana token and OTLP header in Secret Manager.
# Usage: PROJECT=... REGION=us-central1 GRAFANA_URL=https://yourstack.grafana.net OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-....grafana.net/otlp ./scripts/deploy.sh
set -euo pipefail
PROJECT="${PROJECT:?}"; REGION="${REGION:-us-central1}"; SERVICE="${SERVICE:-shot-deadline}"
GRAFANA_URL="${GRAFANA_URL:?}"; OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:?}"
gcloud config set project "$PROJECT" >/dev/null
gcloud services enable run.googleapis.com cloudbuild.googleapis.com aiplatform.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com >/dev/null
gcloud secrets describe grafana-token >/dev/null 2>&1 || { read -rsp "Grafana service account token: " T; echo; printf '%s' "$T" | gcloud secrets create grafana-token --data-file=-; }
gcloud secrets describe otlp-headers >/dev/null 2>&1 || { read -rsp "OTLP headers (Authorization=Basic ...): " T; echo; printf '%s' "$T" | gcloud secrets create otlp-headers --data-file=-; }
PN=$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)'); SA="$PN-compute@developer.gserviceaccount.com"
for ROLE in roles/aiplatform.user roles/secretmanager.secretAccessor; do gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA" --role "$ROLE" >/dev/null; done
# min-instances 1 + no-cpu-throttling: the simulation must keep emitting between requests
gcloud run deploy "$SERVICE" --source . --region "$REGION" --allow-unauthenticated \
  --memory 1Gi --cpu 1 --concurrency 10 --timeout 600 --min-instances 1 --max-instances 1 --no-cpu-throttling \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=$REGION,GRAFANA_URL=$GRAFANA_URL,OTEL_EXPORTER_OTLP_ENDPOINT=$OTEL_EXPORTER_OTLP_ENDPOINT,OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf,EMIT=true,TICK_SECONDS=10" \
  --set-secrets "GRAFANA_SERVICE_ACCOUNT_TOKEN=grafana-token:latest,OTEL_EXPORTER_OTLP_HEADERS=otlp-headers:latest"
gcloud run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)'
