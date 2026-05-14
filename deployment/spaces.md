# DigitalOcean Spaces

DigitalOcean Spaces is the S3-compatible object storage service on
DigitalOcean. Kerf uses it as the object-storage backend for project
blobs, mesh tessellations, thumbnails, and Workshop content. Spaces
speaks the S3 API natively, so `STORAGE_BACKEND=s3` works with no
changes to Kerf's code — just set the endpoint URL.

## Why Spaces

- **S3-compatible API** — drop-in for `STORAGE_BACKEND=s3`. No adapter
  needed.
- **$5/mo all-in for small scale** — 250 GB storage + 1 TB outbound
  bandwidth included. No per-request charges.
- **CDN included** — enable the Spaces CDN to serve thumbnails and
  public assets from DigitalOcean's edge network at no extra cost.
- **Simple pricing** — after the included allowance, $0.02/GB storage
  and $0.01/GB bandwidth (verify on DO pricing page). Much simpler to
  reason about than AWS S3 + data transfer.

## Create a Space

```sh
REGION=lon1
BUCKET=kerf-blobs

doctl spaces create "${BUCKET}" --region "${REGION}"
```

Space names are globally unique across DigitalOcean. If `kerf-blobs` is
taken, use a unique suffix like `kerf-blobs-<your-team>`.

### Verify the Space exists

```sh
doctl spaces list
```

## Create Spaces access keys

App Platform and DOKS services authenticate using Spaces access keys
(not IAM roles — DigitalOcean does not support role-based S3 access for
Spaces at time of writing).

```sh
# Create a key scoped to this bucket
doctl spaces keys create \
  --name kerf-api \
  --grants "bucket:${BUCKET}:readwrite"
```

Output:
```
Access Key: DO00XXXXXXXXXX
Secret Key: <40-char secret>
```

Store these as App Platform secrets (see `digitalocean.md` for the full
app spec). Do not commit them to the repository.

## Map credentials to Kerf env vars

| Spaces value | Kerf env var |
|---|---|
| `kerf-blobs` (bucket name) | `KERF_STORAGE_S3_BUCKET` |
| `https://lon1.digitaloceanspaces.com` | `KERF_STORAGE_S3_ENDPOINT` |
| `lon1` | `KERF_STORAGE_S3_REGION` |
| Access Key from above | `KERF_STORAGE_S3_ACCESS_KEY` |
| Secret Key from above | `KERF_STORAGE_S3_SECRET_KEY` |
| `s3` | `STORAGE_BACKEND` |

**Important**: `KERF_STORAGE_S3_ENDPOINT` must include the region
subdomain: `https://lon1.digitaloceanspaces.com`. Using
`https://digitaloceanspaces.com` without the region prefix causes
`NoSuchBucket` errors.

## Versioning

Spaces does not support object versioning (unlike S3 or GCS). There is
no `put-bucket-versioning` equivalent. Protect against accidental
overwrites at the application layer — Kerf uses content-addressable keys
for most blobs, so the same object key always points to the same
content. For user-facing file versions, Kerf's `file_revisions` table in
Postgres is the source of truth.

## Lifecycle policies

Spaces supports lifecycle rules via the S3-compatible API:

```sh
# Apply lifecycle using AWS CLI against the Spaces endpoint
aws --endpoint-url="https://${REGION}.digitaloceanspaces.com" \
  s3api put-bucket-lifecycle-configuration \
  --bucket "${BUCKET}" \
  --lifecycle-configuration '{
    "Rules": [
      {
        "ID": "expire-tessellations",
        "Status": "Enabled",
        "Filter": {"Prefix": "tessellations/"},
        "Expiration": {"Days": 30}
      }
    ]
  }'
```

Set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` to the Spaces keys
when running the AWS CLI against the Spaces endpoint.

## CDN integration

Enable the Spaces CDN to serve public assets (thumbnails, SPA static
assets if you offload them) from DigitalOcean's CDN edge:

```sh
# Enable CDN via the control panel:
# Spaces → select bucket → CDN → Enable CDN
# Custom domain: set CNAME cdn.kerf.example.com → <space>.cdn.digitaloceanspaces.com
```

CDN is included in the $5/mo Spaces price — no additional charge per GB
served through the CDN. Useful for reducing latency on thumbnails served
to SA users (CDN has a JNB PoP).

The CDN URL format: `https://<bucket>.<region>.cdn.digitaloceanspaces.com/<key>`

To use the CDN URL in Kerf, set:

```sh
CDN_BASE_URL=https://kerf-blobs.lon1.cdn.digitaloceanspaces.com
```

When `CDN_BASE_URL` is set, Kerf generates presigned download URLs
using the CDN endpoint for public assets.

## CORS configuration

For direct browser-to-Spaces uploads (presigned PUT):

```sh
aws --endpoint-url="https://${REGION}.digitaloceanspaces.com" \
  s3api put-bucket-cors \
  --bucket "${BUCKET}" \
  --cors-configuration '{
    "CORSRules": [
      {
        "AllowedOrigins": ["https://kerf.example.com"],
        "AllowedMethods": ["PUT", "POST", "GET", "HEAD"],
        "AllowedHeaders": ["Content-Type", "Content-MD5", "Authorization"],
        "MaxAgeSeconds": 3600
      }
    ]
  }'
```

## Limits worth knowing

- **No versioning**: Spaces does not support bucket versioning. See note
  above on how Kerf handles this.
- **Per-object size**: 5 TiB (same as S3 standard).
- **Multipart upload**: supported — Kerf's chunked-upload helpers work
  correctly with Spaces.
- **Bandwidth**: 1 TB/mo included. After that, $0.01/GB outbound.
  Inbound (uploads) are free.
- **Request count**: no per-request charge. Unlike AWS S3, you are not
  billed per PUT/GET.
- **Regions with Spaces**: `nyc3`, `sfo3`, `ams3`, `sgp1`, `fra1`,
  `lon1`, `syd1`. No `jnb`. Use `lon1` for SA users.

## Local dev

For local dev, use MinIO as a Spaces stand-in:

```sh
STORAGE_BACKEND=s3
KERF_STORAGE_S3_ENDPOINT=http://localhost:9000
KERF_STORAGE_S3_BUCKET=kerf-local
KERF_STORAGE_S3_ACCESS_KEY=minioadmin
KERF_STORAGE_S3_SECRET_KEY=minioadmin
KERF_STORAGE_S3_REGION=lon1
```

The `docker-compose.yml` includes a MinIO service for this. Any S3 SDK
that supports custom endpoints works against Spaces in production, so
MinIO local dev is a faithful proxy.

## Troubleshooting

- **NoSuchBucket**: check that the bucket exists (`doctl spaces list`)
  and that `KERF_STORAGE_S3_ENDPOINT` includes the region subdomain
  (`https://lon1.digitaloceanspaces.com`, not `https://digitaloceanspaces.com`).
- **403 on upload**: check the Spaces key has `readwrite` access. Keys
  scoped to `readonly` only work for GET/HEAD. Recreate the key with
  `--grants "bucket:${BUCKET}:readwrite"`.
- **SignatureDoesNotMatch**: `KERF_STORAGE_S3_REGION` must match the
  region the Space was created in. Mismatches cause signature errors even
  if the endpoint URL is correct.
- **CORS error on presigned PUT from browser**: ensure CORS is configured
  on the bucket (see above) and that the allowed origin exactly matches
  the frontend URL (no trailing slash).
- **CDN returning stale content**: Spaces CDN has a default TTL of 1
  hour. For frequently updated thumbnails, use a short `Cache-Control`
  header on the objects or invalidate the CDN path after updates.
