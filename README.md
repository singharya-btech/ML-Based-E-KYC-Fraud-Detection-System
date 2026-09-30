# E-KYC Website Integration (India)

This project delegates customer identity checks to Digio DigiKYC. Streamlit starts a request through FastAPI, the customer completes Digio's hosted KYC flow, and the website reads the final provider status. The app does not locally compare faces or store uploaded documents/face templates.

## Digio Setup

1. Obtain Digio sandbox client credentials and enable DigiStudio/DigiKYC for your account.
2. Create PAN and Aadhaar workflow templates in DigiStudio. Configure the required document verification, selfie face match, liveness checks, reviewer/approval rules, and retention policy. Put each exact template name in `.env`.
3. Copy `.env.example` to `.env` and set the sandbox credentials, both template names, and fresh random values for `APP_API_TOKEN` and `DIGIO_WEBHOOK_SECRET`. Keep `.env` private; it is git-ignored. Do not put credentials in Streamlit widgets or browser JavaScript.
4. Configure a DigiStudio webhook group to call `https://<your-public-api-host>/api/kyc/webhooks/digio`, set its secret to the same `DIGIO_WEBHOOK_SECRET`, and enable KYC request events. Digio signs the raw JSON body with HMAC-SHA256 in `X-Digio-Checksum`.
5. Test using sandbox credentials first. Digio's sandbox API is `https://ext.digio.in:444`; production is `https://api.digio.in`. The environment is selected by `DIGIO_ENV`.

Digio's official references:

- [DigiKYC](https://documentation.digio.in/digikyc/)
- [Create DigiStudio request](https://documentation.digio.in/digistudio/integration/create_request_api/)
- [Digio Web SDK](https://documentation.digio.in/sdk/web/web/)
- [Get request status](https://documentation.digio.in/digistudio/integration/get_status/)
- [Webhook security and setup](https://documentation.digio.in/webhooks/faq/)
- [Environment URLs](https://documentation.digio.in/digienvironments/)

## Run Locally

Use one virtual environment for both Streamlit and FastAPI:

```powershell
py -3.10 -m venv .venv
\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` locally with your Digio sandbox credentials, the template names created in DigiStudio, and independent random values for `APP_API_TOKEN` and `DIGIO_WEBHOOK_SECRET`. Generate random values with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Never send or commit secrets.

In the first terminal, start FastAPI:

```powershell
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

In a second terminal, activate the same `.venv` and start Streamlit:

```powershell
\.venv\Scripts\Activate.ps1
python -m streamlit run app.py
```

The UI opens at `http://localhost:8501`. FastAPI listens only on loopback in this local example. For a deployed site, expose FastAPI only behind HTTPS and a trusted reverse proxy; use deployment secret storage, not a committed `.env`.

In local development, Swagger is available at `http://127.0.0.1:8000/docs` and ReDoc at `http://127.0.0.1:8000/redoc`. Set `API_DOCS_ENABLED=false` in the deployment environment to disable these docs and the OpenAPI schema in production.

## API Contract

- `POST /api/kyc/sessions` creates a Digio request. It requires the private `APP_API_TOKEN`, explicit consent, a valid contact identifier, and a configured template.
- `GET /api/kyc/sessions/{session_id}` retrieves status from Digio; only Digio's final `approved` status is returned as `verified: true`.
- `POST /api/kyc/webhooks/digio` validates `X-Digio-Checksum` against the exact raw request body and handles repeated event IDs idempotently. Webhook events are not treated as proof of approval; the status endpoint remains authoritative.

The KYC database stores only provider request IDs, random local session IDs, document type, status, event IDs, and timestamps. It does not store document numbers, names, DOBs, uploaded images, or embeddings. Protect and expire these records under your retention requirements. The old local OCR/FaceNet modules remain in the repository for reference but are not called by the website flow and are not part of the production requirements.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Production Gate

This is a provider-backed integration scaffold, not a certification of regulatory compliance. Before accepting real customers, complete Digio onboarding and template approval; verify that your templates require the intended ID verification, selfie match, liveness, and approval rules; configure a public HTTPS webhook and verify sandbox and production account behavior; keep FastAPI's session endpoints on a private network and expose only the webhook through an HTTPS reverse proxy; add rate limits, user authentication/authorization, audit/retention/deletion processes, encrypted backups, monitoring, incident response, and a user privacy/consent notice; and obtain legal/compliance approval for your exact Aadhaar/PAN use case. Never use a sandbox result to make a production decision.

## Docker Compose

Prerequisites: Docker Engine/Desktop with Compose v2 and a configured local `.env`.

```powershell
docker compose -f compose.yaml up --build -d
docker compose -f compose.yaml ps
docker compose -f compose.yaml logs -f backend frontend
```

Local URLs: Streamlit `http://localhost:8501`, FastAPI health `http://localhost:8000/health`, Swagger `http://localhost:8000/docs` is disabled in the Compose backend, and Prometheus `http://localhost:9090`. The backend database and Prometheus TSDB use named Docker volumes. Stop the stack with `docker compose -f compose.yaml down`; add `-v` only if you intentionally want to delete those volumes and their records.

## Kubernetes

Prerequisites: an existing Kubernetes cluster, ingress-nginx, a default StorageClass, a TLS certificate/secret, and the ability to push images to a registry reachable by cluster nodes. Update `image:` values in `kubernetes/app.yaml` to your registry tags, set the DigiStudio template names in the ConfigMap, and replace `kyc.example.com` with your real host. Do not commit Kubernetes Secret YAML.

Build and push the images, then create the namespace and runtime Secret from the local `.env`:

```powershell
docker build -f Dockerfile.backend -t YOUR_REGISTRY/ekyc-backend:VERSION .
docker build -f Dockerfile.frontend -t YOUR_REGISTRY/ekyc-frontend:VERSION .
docker push YOUR_REGISTRY/ekyc-backend:VERSION
docker push YOUR_REGISTRY/ekyc-frontend:VERSION
kubectl apply -f kubernetes/namespace.yaml
kubectl create secret generic ekyc-secrets -n ekyc --from-env-file=.env
```

Create the Prometheus scrape ConfigMap and deploy the application and monitoring stack:

```powershell
kubectl create configmap prometheus-config -n ekyc --from-file=prometheus.yml=monitoring/prometheus-kubernetes.yml
kubectl apply -f kubernetes/app.yaml
kubectl apply -f kubernetes/monitoring.yaml
kubectl -n ekyc get pods,services,ingress,pvc
```

The manifests deliberately use one backend replica because SQLite is on a single-writer persistent volume. For horizontal scaling, move session metadata to a managed database before increasing backend replicas. Prometheus and the backend metrics endpoint are ClusterIP-only; do not expose `/metrics` publicly. Configure the Digio webhook URL as `https://YOUR_HOST/api/kyc/webhooks/digio` and its HMAC secret to the same value used in `.env`.

Kubernetes Secrets are base64-encoded, not encrypted merely by creating them. Enable cluster Secret encryption at rest and restrict RBAC access. Use a managed secret store for production deployments where available.
