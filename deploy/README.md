# Deploying the demo on AWS

**Why AWS:** judges need a working demo link. The build environment also can't reach `ingest.neatlogs.com`, so a hosted instance with `NEATLOGS_API_KEY` set produces real neatlogs traces from real dashboard runs. Keywarden itself doesn't depend on AWS, and its adapters stay sandboxed mocks.

**Target:** one Lightsail container service (power `nano`, scale 1) runs the single image in `Dockerfile`, with the FastAPI backend and statically exported dashboard on port 8000. The hackathon AWS credit is meant to cover it. Check the current Lightsail container pricing before you deploy, and delete the service after judging.

## Deploy

```bash
export AWS_REGION=us-east-1            # any Lightsail region
export NEATLOGS_API_KEY=...            # optional, enables tracing from the live demo; never commit it
./deploy/aws-lightsail.sh              # builds, pushes, deploys, prints the public URL
```

Prerequisites: Docker, AWS CLI v2 signed in to the account with the credit, and the `lightsailctl` plugin.

The demo identities (analyst, approver, viewer, other org) are built into this sandbox build, so anyone with the link can use them. Writes are rate-limited per identity. Data lives on the container's disk and resets on every redeploy.

## Run the same image locally

```bash
docker build -t keywarden .
docker run --rm -p 8000:8000 -e NEATLOGS_API_KEY keywarden   # http://localhost:8000
```

## Tear down

```bash
aws lightsail delete-container-service --service-name keywarden --region "$AWS_REGION"
```
