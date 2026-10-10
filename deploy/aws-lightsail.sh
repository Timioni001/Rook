#!/usr/bin/env bash
# Deploy Keywarden (sandbox demo) to an AWS Lightsail container service.
#
# Needs: Docker, AWS CLI v2 with credentials for the account holding the hackathon credit,
# and the lightsailctl plugin (used by `aws lightsail push-container-image`).
# Optional: NEATLOGS_API_KEY in the environment, passed to the container so the live demo traces.
set -euo pipefail

SERVICE="${SERVICE:-keywarden}"
REGION="${AWS_REGION:-us-east-1}"
POWER="${POWER:-nano}"          # smallest tier; plenty for a single-process demo
cd "$(dirname "$0")/.."

docker build -t keywarden:latest .

if ! aws lightsail get-container-services --service-name "$SERVICE" --region "$REGION" >/dev/null 2>&1; then
  aws lightsail create-container-service --service-name "$SERVICE" --power "$POWER" --scale 1 --region "$REGION" >/dev/null
  echo "created container service $SERVICE ($POWER) in $REGION"
fi

state() { aws lightsail get-container-services --service-name "$SERVICE" --region "$REGION" \
            --query 'containerServices[0].state' --output text; }
until [[ "$(state)" == "READY" || "$(state)" == "RUNNING" ]]; do echo "waiting for service: $(state)"; sleep 15; done

aws lightsail push-container-image --service-name "$SERVICE" --label app --image keywarden:latest --region "$REGION"
IMAGE=$(aws lightsail get-container-images --service-name "$SERVICE" --region "$REGION" \
          --query 'containerImages[0].image' --output text)

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
python3 - "$IMAGE" > "$TMP/containers.json" <<'PY'
import json, os, sys
env = {"KEYWARDEN_STEP_DELAY": "0.6", "ROOK_VERSION": os.getenv("ROOK_VERSION", "aws")}
if os.getenv("NEATLOGS_API_KEY"):
    env["NEATLOGS_API_KEY"] = os.environ["NEATLOGS_API_KEY"]
print(json.dumps({"app": {"image": sys.argv[1], "ports": {"8000": "HTTP"}, "environment": env}}))
PY
cat > "$TMP/endpoint.json" <<'JSON'
{"containerName": "app", "containerPort": 8000,
 "healthCheck": {"path": "/api/health", "intervalSeconds": 10, "successCodes": "200"}}
JSON

aws lightsail create-container-service-deployment --service-name "$SERVICE" --region "$REGION" \
  --containers "file://$TMP/containers.json" --public-endpoint "file://$TMP/endpoint.json" >/dev/null

until [[ "$(state)" == "RUNNING" ]]; do echo "deploying: $(state)"; sleep 15; done
echo "Keywarden is live at: $(aws lightsail get-container-services --service-name "$SERVICE" --region "$REGION" \
  --query 'containerServices[0].url' --output text)"
