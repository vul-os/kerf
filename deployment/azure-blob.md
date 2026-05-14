# Azure Blob Storage (+ S3 adapter gap)

This document covers Azure Blob Storage for Kerf deployments. Read this
before deploying to Azure — **Azure Blob is not S3-compatible out of the
box**, and Kerf's current storage layer assumes an S3-compatible API.
This page explains the gap and the practical workarounds.

## The gap

Kerf uses `STORAGE_BACKEND=s3` throughout, which calls the S3 API
(presigned URLs, multipart upload, `GetObject`, `PutObject`, etc.).
Azure Blob Storage has its own REST API and SDK — it is not a drop-in
replacement. Azure does offer an S3-compatible endpoint as part of its
**Azure Data Lake Storage Gen2 Blob NFS** and through some third-party
gateways, but there is no straightforward "enable S3 compatibility"
toggle for a general-purpose Blob container.

**In short:** Kerf + Azure Blob natively requires either:

1. A `STORAGE_BACKEND=azure` adapter (not yet implemented — tracked as
   future work), or
2. An S3-compatible gateway layer in front of Azure Blob.

## Recommended approach for v1: MinIO as S3 facade

Run MinIO in Gateway mode backed by Azure Blob. MinIO's Azure gateway
presents an S3-compatible endpoint; Kerf connects to MinIO exactly as it
would to any other S3 endpoint. Data actually lives in Azure Blob.

```
Kerf app (STORAGE_BACKEND=s3)
  → MinIO Gateway (s3-compatible API)
    → Azure Blob Storage
```

### Deploy MinIO Gateway as a Container App

```sh
RESOURCE_GROUP=kerf-rg
REGION=southafricanorth

# Create an Azure Storage account for MinIO to back onto
az storage account create \
  --name kerfminiobacking \
  --resource-group "${RESOURCE_GROUP}" \
  --location "${REGION}" \
  --sku Standard_LRS \
  --kind StorageV2

# Get the storage account key
STORAGE_KEY=$(az storage account keys list \
  --resource-group "${RESOURCE_GROUP}" \
  --account-name kerfminiobacking \
  --query '[0].value' --output tsv)

# Create a Blob container for Kerf
az storage container create \
  --name kerf-blobs \
  --account-name kerfminiobacking \
  --account-key "${STORAGE_KEY}"

# Deploy MinIO Gateway as a Container App (internal-only)
MINIO_ACCESS=minioadmin  # change in production
MINIO_SECRET=$(openssl rand -hex 32)

az containerapp create \
  --name kerf-minio \
  --resource-group "${RESOURCE_GROUP}" \
  --environment kerf-env \
  --image minio/minio:latest \
  --ingress internal \
  --target-port 9000 \
  --min-replicas 1 \
  --max-replicas 1 \
  --cpu 0.5 \
  --memory 1Gi \
  --env-vars \
    MINIO_ROOT_USER="${MINIO_ACCESS}" \
    MINIO_ROOT_PASSWORD="${MINIO_SECRET}" \
  --args "gateway azure --console-address :9001" \
  --env-vars \
    AZURE_STORAGE_ACCOUNT_NAME=kerfminiobacking \
    AZURE_STORAGE_ACCOUNT_KEY="${STORAGE_KEY}"
```

MinIO Gateway is deprecated in newer MinIO versions in favour of the
standalone mode with tiering. If you hit issues, see the MinIO
[Azure Gateway migration guide](https://min.io/docs/minio/linux/operations/install-deploy-manage/migrate-to-minio.html)
or use the **alternative cross-cloud approach** below.

### Point Kerf at the MinIO endpoint

Once the `kerf-minio` Container App is running, its internal FQDN is:
`kerf-minio.<unique>.internal.<region>.azurecontainerapps.io:9000`

Set these on the main `kerf` Container App:

```sh
az containerapp update --name kerf --resource-group "${RESOURCE_GROUP}" \
  --set-env-vars \
    STORAGE_BACKEND=s3 \
    KERF_STORAGE_S3_ENDPOINT="http://kerf-minio.internal.<unique>.<region>.azurecontainerapps.io:9000" \
    KERF_STORAGE_S3_BUCKET=kerf-blobs \
    KERF_STORAGE_S3_REGION=us-east-1 \
  --secrets minio-access=<value> minio-secret=<value> \
  --set-env-vars \
    KERF_STORAGE_S3_ACCESS_KEY=secretref:minio-access \
    KERF_STORAGE_S3_SECRET_KEY=secretref:minio-secret
```

## Alternative: cross-cloud AWS S3

For teams already on Azure who do not want the MinIO complexity, use an
AWS S3 bucket in `eu-central-1` (Frankfurt) as the storage backend.
Kerf works with `STORAGE_BACKEND=s3` pointing at AWS from inside Azure.

Tradeoff: ~$0.09/GB egress from Azure to S3 (cross-cloud internet). At
small scale (< 100 GB/month) this is < $9/month — tolerable. At larger
scale, migrate to the MinIO facade.

## Future: native Azure Blob adapter

A `STORAGE_BACKEND=azure` path in Kerf would remove the MinIO layer
entirely. The adapter would use the Azure Blob SDK
(`azure-storage-blob`) and implement the same internal interface as the
S3 backend. This is tracked as future work and is not blocking current
deployments.

## Native Azure Blob setup (for when the adapter lands)

Even if you are using MinIO for now, create and configure the Blob
Storage account so that it is ready when the native adapter is
implemented.

### Create the storage account

```sh
az storage account create \
  --name kerfblobs \
  --resource-group "${RESOURCE_GROUP}" \
  --location "${REGION}" \
  --sku Standard_LRS \
  --kind StorageV2 \
  --allow-blob-public-access false \
  --min-tls-version TLS1_2
```

### Create the container

```sh
az storage container create \
  --name kerf-blobs \
  --account-name kerfblobs \
  --auth-mode login
```

### Assign access to the managed identity

```sh
IDENTITY_PRINCIPAL=$(az identity show \
  --name kerf-identity \
  --resource-group "${RESOURCE_GROUP}" \
  --query principalId --output tsv)

STORAGE_ID=$(az storage account show \
  --name kerfblobs \
  --resource-group "${RESOURCE_GROUP}" \
  --query id --output tsv)

az role assignment create \
  --assignee "${IDENTITY_PRINCIPAL}" \
  --role "Storage Blob Data Contributor" \
  --scope "${STORAGE_ID}"
```

### Versioning

```sh
az storage account blob-service-properties update \
  --account-name kerfblobs \
  --resource-group "${RESOURCE_GROUP}" \
  --enable-versioning true \
  --enable-delete-retention true \
  --delete-retention-days 30
```

### Lifecycle management

```sh
az storage account management-policy create \
  --account-name kerfblobs \
  --resource-group "${RESOURCE_GROUP}" \
  --policy '{
    "rules": [
      {
        "name": "archive-old-blobs",
        "type": "Lifecycle",
        "definition": {
          "filters": {"blobTypes": ["blockBlob"], "prefixMatch": ["blobs/"]},
          "actions": {
            "baseBlob": {
              "tierToCool": {"daysAfterModificationGreaterThan": 30},
              "tierToArchive": {"daysAfterModificationGreaterThan": 90}
            }
          }
        }
      }
    ]
  }'
```

Storage tier costs (verify on Azure pricing):
- Hot: $0.0184/GB-mo
- Cool: $0.01/GB-mo (30-day minimum)
- Archive: $0.00099/GB-mo (180-day minimum, rehydration required)

## Local dev

For local development on Azure, use Azurite (Microsoft's Azure Storage
emulator) or MinIO:

```sh
# Azurite — Azure-compatible emulator
docker run -p 10000:10000 mcr.microsoft.com/azure-storage/azurite \
  azurite-blob --blobHost 0.0.0.0

# OR MinIO (simpler — works with STORAGE_BACKEND=s3 directly)
docker run -p 9000:9000 -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin minio/minio server /data
```

The `docker-compose.yml` uses MinIO. If you prefer Azurite, swap the
compose service — but note that Azurite does not speak the S3 API;
you would need to use the Azure SDK or the Azurite Blob endpoint
(`http://localhost:10000/devstoreaccount1`).

## Limits worth knowing

- **Per-blob size**: 200 GiB per block blob (block count limit × block
  size). Block blob max size is 200 GiB with 50,000 blocks × 4 MiB.
  Practically, for STEP files and meshes this is not a concern.
- **Throughput per account**: 20 Gbps ingress / 10 Gbps egress (LRS,
  Standard tier). Not a concern at small scale.
- **MinIO Gateway deprecation**: MinIO Inc. deprecated the gateway
  mode as of MinIO RELEASE.2022-10-29. It still works but is not
  receiving new feature development. For long-term stability, the
  native adapter or cross-cloud S3 is preferred.

## Troubleshooting

- **MinIO Gateway fails to start**: ensure the storage account key is
  set correctly in the env vars. Check Container App logs:
  `az containerapp logs show --name kerf-minio --resource-group kerf-rg`
- **Kerf 403 on upload via MinIO**: the MinIO access/secret keys in
  Kerf's env must match what MinIO was started with.
- **MinIO internal FQDN not resolving**: the MinIO Container App and the
  Kerf Container App must be in the same Container Apps environment.
  Cross-environment internal DNS does not work.
- **Blob container access denied (future native adapter)**: ensure the
  managed identity has `Storage Blob Data Contributor` (not just
  `Storage Blob Data Reader`) on the storage account.
