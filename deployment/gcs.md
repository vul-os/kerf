# Google Cloud Storage

Kerf uses Cloud Storage as its object-storage backend on GCP — project
blobs, mesh tessellations, thumbnails, and Workshop content. Cloud
Storage exposes an S3-compatible XML API, so `STORAGE_BACKEND=s3` works
unchanged; the only difference is the endpoint URL and the credential
type (HMAC keys instead of IAM access keys).

## Why Cloud Storage (vs keeping AWS S3 on GCP)

- **No cross-cloud egress** — data stays inside Google's network. AWS
  S3 from a GCP Cloud Run service adds $0.09/GB internet egress.
- **SA region** — `africa-south1` (Johannesburg) has low latency for SA
  users with no egress charge to Cloud Run in the same region.
- **Unified billing** — one GCP invoice rather than GCP + AWS.
- **Pricing** — $0.020/GB-mo standard (JNB), slightly cheaper than AWS
  S3's $0.023/GB-mo.

The tradeoff: HMAC keys (not IAM roles), and you must use the S3
interop endpoint explicitly. Setup is a one-time 10-minute task.

## Enable interoperability

Cloud Storage S3 compatibility is off by default per project. Enable it:

1. Cloud Console → Cloud Storage → Settings → Interoperability tab
2. Click **Enable interoperability access**
3. The S3 endpoint for your project is:
   `https://storage.googleapis.com`

You can also enable via `gcloud`:

```sh
gcloud storage hmac access enable
```

## Create the bucket

```sh
PROJECT_ID=$(gcloud config get-value project)

# SA users: africa-south1 (Johannesburg)
gsutil mb -p "${PROJECT_ID}" \
  -l africa-south1 \
  -c standard \
  gs://kerf-blobs-${PROJECT_ID}

# EU users: europe-west3 (Frankfurt)
# gsutil mb -p "${PROJECT_ID}" -l europe-west3 -c standard gs://kerf-blobs-${PROJECT_ID}-eu
```

Block public access (Kerf serves files through the app, not directly):

```sh
gsutil uniformbucketlevelaccess set on gs://kerf-blobs-${PROJECT_ID}
gsutil pap set enforced gs://kerf-blobs-${PROJECT_ID}
```

## Create HMAC keys

Cloud Storage S3 interop uses **HMAC keys** tied to a service account
(not a user account). Create them for the Kerf service account:

```sh
SA="kerf-api@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud storage hmac create "${SA}" \
  --project="${PROJECT_ID}"

# Output:
#   accessId: GOOGXXXXXXXXXXX
#   secret:   <40-char secret>
```

Grant the service account object-level access on the bucket:

```sh
gsutil iam ch "serviceAccount:${SA}:objectAdmin" \
  gs://kerf-blobs-${PROJECT_ID}
```

## Map credentials to Kerf env vars

| GCS / HMAC value | Kerf env var |
|---|---|
| `accessId` from above | `KERF_STORAGE_S3_ACCESS_KEY` |
| `secret` from above | `KERF_STORAGE_S3_SECRET_KEY` |
| `gs://kerf-blobs-<PROJECT_ID>` (bucket name only) | `KERF_STORAGE_S3_BUCKET` |
| `https://storage.googleapis.com` | `KERF_STORAGE_S3_ENDPOINT` |
| `africa-south1` (or your region) | `KERF_STORAGE_S3_REGION` |
| `s3` | `STORAGE_BACKEND` |

Store these as Cloud Run secrets, not plain env vars:

```sh
printf "GOOGXXXXXXXXXXX" | gcloud secrets create kerf-gcs-hmac-access --data-file=-
printf "<40-char-secret>" | gcloud secrets create kerf-gcs-hmac-secret --data-file=-
printf "kerf-blobs-${PROJECT_ID}" | gcloud secrets create kerf-gcs-bucket --data-file=-
```

## Versioning (recommended)

Enable object versioning so accidental deletes or overwrites are
recoverable:

```sh
gsutil versioning set on gs://kerf-blobs-${PROJECT_ID}
```

Soft-delete is also enabled by default on new buckets (7-day retention).
Versioning gives you finer control.

To list noncurrent versions:

```sh
gsutil ls -a gs://kerf-blobs-${PROJECT_ID}
```

## Lifecycle policies (optional)

Delete or downgrade storage class for stale derived objects to reduce
cost:

```json
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {
          "age": 90,
          "matchesPrefix": ["tessellations/"],
          "isLive": false
        }
      },
      {
        "action": {"type": "SetStorageClass", "storageClass": "NEARLINE"},
        "condition": {
          "age": 30,
          "matchesPrefix": ["thumbnails/"]
        }
      }
    ]
  }
}
```

Apply:

```sh
gsutil lifecycle set lifecycle.json gs://kerf-blobs-${PROJECT_ID}
```

Storage class costs: Standard $0.020/GB-mo, Nearline $0.010/GB-mo
(30-day minimum), Coldline $0.004/GB-mo (90-day minimum). Nearline and
Coldline have per-operation retrieval charges — only use them for cold
archives, not active project blobs.

## CORS configuration

If the frontend uploads directly to GCS (presigned URLs), configure
CORS:

```json
[
  {
    "origin": ["https://kerf.example.com"],
    "method": ["PUT", "POST", "GET", "HEAD"],
    "responseHeader": ["Content-Type", "Content-MD5", "Authorization"],
    "maxAgeSeconds": 3600
  }
]
```

```sh
gsutil cors set cors.json gs://kerf-blobs-${PROJECT_ID}
```

## Limits worth knowing

- **Per-object size**: 5 TiB (GCS standard).
- **Multipart upload**: GCS S3 interop supports S3 multipart API. Kerf
  uses chunked uploads above ~50 MB, which works correctly.
- **Request rate**: GCS hot-object limit is ~5,000 reads/second per
  prefix. Kerf's key layout (`user_id/project_id/...`) naturally
  distributes load.
- **HMAC key limit**: 10 HMAC keys per service account. Rotate expired
  keys to stay within the limit.

## Local dev

For local dev, point at MinIO as you would for any other provider:

```sh
STORAGE_BACKEND=s3
KERF_STORAGE_S3_ENDPOINT=http://localhost:9000
KERF_STORAGE_S3_BUCKET=kerf-local
KERF_STORAGE_S3_ACCESS_KEY=minioadmin
KERF_STORAGE_S3_SECRET_KEY=minioadmin
KERF_STORAGE_S3_REGION=us-east-1
```

The `docker-compose.yml` includes a MinIO service for this.

## Troubleshooting

- **403 on upload / SignatureDoesNotMatch**: the HMAC key must be for
  the service account, not a user account. Check the `accessId` prefix —
  it starts with `GOOG`. User HMAC keys are no longer recommended for
  production use.
- **NoSuchBucket**: bucket names are global; your name may be taken. Use
  a project-ID suffix (e.g., `kerf-blobs-${PROJECT_ID}`).
- **Slow uploads from Cloud Run**: if you see >500 ms latency from
  Cloud Run to GCS, confirm both are in the same region. Cross-region
  traffic adds latency and egress charges.
- **Versioning consumes storage**: noncurrent versions are billed at the
  same rate as live objects. Add a lifecycle rule to delete noncurrent
  versions older than 30 days if bucket size is growing unexpectedly.
- **HMAC key expired**: HMAC keys don't expire, but they can be
  deactivated. Check `gcloud storage hmac list` to confirm the key is
  `ACTIVE`.
