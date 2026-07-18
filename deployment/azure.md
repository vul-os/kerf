# Azure Container Apps deployment

Kerf deploys to Microsoft Azure using **Azure Container Apps** —
serverless, scale-to-zero, and supports arbitrary Docker images without
cluster management. The same image built from the monorepo Dockerfile
works here unchanged.

If you need full Kubernetes control (Keda, custom operators, internal
mesh), Azure Kubernetes Service (AKS) is the alternative; see
[Kubernetes alternative](#kubernetes-alternative-aks) below.

## Prerequisites

- Azure CLI installed: `brew install azure-cli`
- Logged in: `az login`
- Subscription active with billing configured
- Resource providers registered:

  ```sh
  az provider register --namespace Microsoft.App
  az provider register --namespace Microsoft.OperationalInsights
  az provider register --namespace Microsoft.DBforPostgreSQL
  az provider register --namespace Microsoft.ContainerRegistry
  ```

- Azure Container Registry: see [Image registry (ACR)](#image-registry-acr) below
- Azure Database for PostgreSQL: see [Postgres](#postgres-azure-database-for-postgresql)
- Storage: **read [azure-blob.md](./azure-blob.md) before continuing** —
  Azure Blob is not S3-compatible out of the box; this requires extra
  setup.

## Region selection

| Audience | Region |
|---|---|
| South Africa | `southafricanorth` (Johannesburg) |
| Europe | `westeurope` (Amsterdam) or `germanywestcentral` (Frankfurt) |
| US | `eastus` |

## Image registry (ACR)

```sh
RESOURCE_GROUP=kerf-rg
REGION=southafricanorth
ACR_NAME=kerfregistry  # must be globally unique, lowercase

az group create --name "${RESOURCE_GROUP}" --location "${REGION}"

az acr create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${ACR_NAME}" \
  --sku Standard \
  --admin-enabled false

# Authenticate
az acr login --name "${ACR_NAME}"

# Build and push
IMAGE="${ACR_NAME}.azurecr.io/kerf:latest"
docker build --build-arg KERF_PERSONA=full -t "${IMAGE}" .
docker push "${IMAGE}"
```

Image path: `<acr-name>.azurecr.io/kerf:<tag>`

Grant the Container Apps environment permission to pull from ACR:

```sh
# Create a managed identity for the Container App
az identity create \
  --name kerf-identity \
  --resource-group "${RESOURCE_GROUP}"

IDENTITY_ID=$(az identity show \
  --name kerf-identity \
  --resource-group "${RESOURCE_GROUP}" \
  --query id --output tsv)

IDENTITY_PRINCIPAL=$(az identity show \
  --name kerf-identity \
  --resource-group "${RESOURCE_GROUP}" \
  --query principalId --output tsv)

ACR_ID=$(az acr show \
  --name "${ACR_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --query id --output tsv)

az role assignment create \
  --assignee "${IDENTITY_PRINCIPAL}" \
  --role AcrPull \
  --scope "${ACR_ID}"
```

## Postgres (Azure Database for PostgreSQL)

Create a Flexible Server instance:

```sh
az postgres flexible-server create \
  --name kerf-pg \
  --resource-group "${RESOURCE_GROUP}" \
  --location "${REGION}" \
  --sku-name Standard_D2ds_v4 \
  --tier GeneralPurpose \
  --version 16 \
  --admin-user kerf_app \
  --admin-password "CHANGE_ME" \
  --storage-size 32 \
  --high-availability Enabled \
  --zone 1 \
  --standby-zone 2
```

`Standard_D2ds_v4` is 2 vCPU / 8 GiB RAM, the recommended production
tier. For early stage, `Standard_B2ms` (burstable) is cheaper; resize
when you need it.

Create the database:

```sh
az postgres flexible-server db create \
  --resource-group "${RESOURCE_GROUP}" \
  --server-name kerf-pg \
  --database-name kerf
```

Connection string:

```
DATABASE_URL=postgres://kerf_app:CHANGE_ME@kerf-pg.postgres.database.azure.com:5432/kerf?sslmode=require
```

Configure firewall to allow Container Apps (or use private VNet
integration — recommended for production):

```sh
# Allow Azure services (quick start; use VNet for production)
az postgres flexible-server firewall-rule create \
  --name allow-azure-services \
  --resource-group "${RESOURCE_GROUP}" \
  --server-name kerf-pg \
  --start-ip-address 0.0.0.0 \
  --end-ip-address 0.0.0.0
```

## Storage (Azure Blob — important caveats)

Azure Blob Storage is **not S3-compatible out of the box**. Kerf's
`STORAGE_BACKEND=s3` requires an S3-compatible endpoint. You have three
options:

1. **MinIO on Container Apps (recommended for v1)** — run a MinIO
   container as a second Container App, backed by Azure Blob via its
   Gateway mode. MinIO exposes an S3-compatible endpoint that Kerf
   talks to.

2. **Use AWS S3 cross-cloud** — Kerf points at an S3 bucket in
   `eu-central-1` or `af-south-1`. You pay $0.09/GB cross-cloud egress
   but no adapter work needed.

3. **Native Azure Blob adapter (TBD)** — a `STORAGE_BACKEND=azure`
   path does not exist yet in Kerf. This is tracked as future work.

See [azure-blob.md](./azure-blob.md) for the full discussion and MinIO
setup steps.

## Secrets (Key Vault)

Store secrets in Azure Key Vault:

```sh
KV_NAME=kerf-kv  # globally unique

az keyvault create \
  --name "${KV_NAME}" \
  --resource-group "${RESOURCE_GROUP}" \
  --location "${REGION}" \
  --sku standard

# Store secrets
az keyvault secret set --vault-name "${KV_NAME}" \
  --name database-url \
  --value "postgres://kerf_app:CHANGE_ME@kerf-pg.postgres.database.azure.com:5432/kerf?sslmode=require"

az keyvault secret set --vault-name "${KV_NAME}" \
  --name jwt-secret \
  --value "$(openssl rand -hex 32)"

# Grant the managed identity access to read secrets
az keyvault set-policy \
  --name "${KV_NAME}" \
  --object-id "${IDENTITY_PRINCIPAL}" \
  --secret-permissions get list
```

## Container Apps environment

```sh
# Create a Log Analytics workspace for Container Apps
LOG_WS=$(az monitor log-analytics workspace create \
  --resource-group "${RESOURCE_GROUP}" \
  --workspace-name kerf-logs \
  --query customerId --output tsv)

LOG_KEY=$(az monitor log-analytics workspace get-shared-keys \
  --resource-group "${RESOURCE_GROUP}" \
  --workspace-name kerf-logs \
  --query primarySharedKey --output tsv)

# Create the Container Apps environment
az containerapp env create \
  --name kerf-env \
  --resource-group "${RESOURCE_GROUP}" \
  --location "${REGION}" \
  --logs-workspace-id "${LOG_WS}" \
  --logs-workspace-key "${LOG_KEY}"
```

## First deploy

```sh
az containerapp create \
  --name kerf \
  --resource-group "${RESOURCE_GROUP}" \
  --environment kerf-env \
  --image "${IMAGE}" \
  --registry-server "${ACR_NAME}.azurecr.io" \
  --registry-identity "${IDENTITY_ID}" \
  --target-port 8080 \
  --ingress external \
  --min-replicas 1 \
  --max-replicas 10 \
  --cpu 2 \
  --memory 4Gi \
  --env-vars \
    ENV=cloud \
    PORT=8080 \
    STORAGE_BACKEND=s3 \
  --secrets \
    database-url=keyvaultref:https://${KV_NAME}.vault.azure.net/secrets/database-url,identityref:${IDENTITY_ID} \
    jwt-secret=keyvaultref:https://${KV_NAME}.vault.azure.net/secrets/jwt-secret,identityref:${IDENTITY_ID} \
  --env-vars \
    DATABASE_URL=secretref:database-url \
    JWT_SECRET=secretref:jwt-secret
```

Run migrations (exec into the running container):

```sh
az containerapp exec \
  --name kerf \
  --resource-group "${RESOURCE_GROUP}" \
  --command "python -m kerf_core.db.migrations.runner"
```

## Subsequent deploys

```sh
docker build --build-arg KERF_PERSONA=full -t "${IMAGE}" .
docker push "${IMAGE}"

az containerapp update \
  --name kerf \
  --resource-group "${RESOURCE_GROUP}" \
  --image "${IMAGE}"
```

## Scaling

Container Apps scales based on HTTP concurrency or custom KEDA rules:

```sh
# HTTP concurrency scaling (scale up at 100 concurrent requests)
az containerapp update \
  --name kerf \
  --resource-group "${RESOURCE_GROUP}" \
  --scale-rule-name http-scale \
  --scale-rule-type http \
  --scale-rule-http-concurrency 100 \
  --min-replicas 1 \
  --max-replicas 20
```

## Workers (separate revision)

Deploy a second Container App revision for workers:

```sh
az containerapp create \
  --name kerf-workers \
  --resource-group "${RESOURCE_GROUP}" \
  --environment kerf-env \
  --image "${IMAGE}" \
  --registry-server "${ACR_NAME}.azurecr.io" \
  --registry-identity "${IDENTITY_ID}" \
  --ingress none \
  --min-replicas 1 \
  --max-replicas 5 \
  --cpu 4 \
  --memory 8Gi \
  --env-vars \
    KERF_WORKERS_ONLY=true \
    STORAGE_BACKEND=s3 \
  --secrets \
    database-url=keyvaultref:https://${KV_NAME}.vault.azure.net/secrets/database-url,identityref:${IDENTITY_ID} \
  --env-vars DATABASE_URL=secretref:database-url \
  --command "kerf-server" \
  --args "--host 0.0.0.0 --port 8080 --workers-only"
```

`--ingress none` means the workers app is not reachable from the
internet — it only communicates internally.

## Multi-region

Deploy the same Container App to a second region and use Azure Traffic
Manager (latency-based) or Azure Front Door to route users:

```sh
# Deploy to westeurope
az containerapp create \
  --name kerf \
  --resource-group "${RESOURCE_GROUP}-eu" \
  --environment kerf-env-eu \
  --location westeurope \
  [... same flags ...]

# Configure Azure Front Door origin group with both endpoints
# (see Azure Front Door documentation)
```

## Observability

- **Logs**: `az containerapp logs show --name kerf --resource-group kerf-rg --follow`
- **Metrics**: Azure Monitor in the portal — CPU, memory, replica count, HTTP errors
- **Application Insights**: add the `APPLICATIONINSIGHTS_CONNECTION_STRING`
  env var and the Python SDK picks it up automatically for distributed
  traces
- **Log Analytics**: query container logs in KQL:
  ```kql
  ContainerAppConsoleLogs_CL
  | where ContainerAppName_s == "kerf"
  | order by TimeGenerated desc
  ```

## Custom domain

Container Apps issues and renews managed TLS certificates for custom
domains:

```sh
# Add the custom domain
az containerapp hostname add \
  --name kerf \
  --resource-group "${RESOURCE_GROUP}" \
  --hostname kerf.example.com

# Bind a managed certificate (auto-renews via Let's Encrypt)
az containerapp hostname bind \
  --name kerf \
  --resource-group "${RESOURCE_GROUP}" \
  --hostname kerf.example.com \
  --validation-method HTTP
```

Azure shows the DNS records to add (CNAME to the Container Apps
endpoint, plus a TXT record for verification). TLS is issued and renewed
automatically via Let's Encrypt.

## Kubernetes alternative (AKS)

If you need full Kubernetes control, AKS can deploy the same image using
`deployment/kubernetes.yaml` as a starting point:

```sh
az aks create \
  --resource-group "${RESOURCE_GROUP}" \
  --name kerf-aks \
  --node-count 2 \
  --node-vm-size Standard_D2s_v3 \
  --enable-managed-identity \
  --attach-acr "${ACR_NAME}"

az aks get-credentials \
  --resource-group "${RESOURCE_GROUP}" \
  --name kerf-aks

kubectl apply -f deployment/kubernetes.yaml
```

AKS adds operational overhead (node upgrades, etcd backups, ingress
controllers). For most Kerf deployments, Container Apps is the better
starting point.

## Cost (rough, mid-2026)

| Resource | Spec | Monthly |
|---|---|---|
| Container Apps (app) | 2 vCPU / 4 GiB, ~20% utilisation | ~$30-45 |
| Container Apps (workers) | 4 vCPU / 8 GiB, min-1 | ~$50-70 |
| Azure DB for PostgreSQL | `Standard_B2ms` dev / `Standard_D2ds_v4` prod | $30 dev / $130 prod |
| Azure Blob / MinIO | $0.0184/GB-mo Blob + MinIO container overhead | < $10 at small scale |
| Bandwidth | $0.087/GB egress after 5 GB free | < $5 at small scale |
| ACR | $0.10/GB stored, $5/mo Standard tier | ~$5 |
| **Total at small scale** | (1k-5k users, dev DB) | **~$100-130/mo** |

Container Apps bills per vCPU-second consumed (not reserved). With
`--min-replicas 1`, you pay for one idle replica continuously;
with `--min-replicas 0` you get cold starts.

## Rollback

```sh
# List revisions
az containerapp revision list \
  --name kerf \
  --resource-group "${RESOURCE_GROUP}"

# Activate a previous revision and route all traffic to it
az containerapp ingress traffic set \
  --name kerf \
  --resource-group "${RESOURCE_GROUP}" \
  --revision-weight kerf--00012=100
```

## Troubleshooting

- **Container pull fails**: check that the managed identity has `AcrPull`
  on the ACR resource. A common error is `InaccessibleImage` in the
  Container App's revision logs.
- **Key Vault reference not resolving**: the managed identity must have
  Key Vault `get` and `list` secret permissions. Check the Key Vault
  access policy in the portal.
- **Postgres connection refused**: `allowAzureServices` firewall rule is
  required if not using VNet integration. For production, set up VNet
  peering between the Container Apps environment and the Postgres server.
- **Storage not working**: see [azure-blob.md](./azure-blob.md) — this
  is the most common first-deploy issue on Azure. The MinIO facade
  approach is the fastest path to a working deployment.
- **Migrations not running**: NOT automatic. Run via `az containerapp exec`
  after schema-changing deploys.
