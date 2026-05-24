# Tigris storage

[Tigris](https://www.tigrisdata.com/) is an S3-compatible object-storage
service. Kerf uses it as the object-storage backend for project blobs,
mesh tessellations, project thumbnails, and Workshop content.

Tigris was originally developed as a fly.io-native service but is
accessible via the public endpoint `fly.storage.tigris.dev` from
**any host** — including Koyeb, GCP, and AWS. The endpoint hostname is
the real public hostname; it is not Fly-specific.

## Why Tigris (vs Cloudflare R2 or AWS S3)

- **Anycast network** — low-latency access from any region; zero egress
  when used alongside fly.io (`jnb`/`fra` machines). From Koyeb Frankfurt,
  Tigris Frankfurt-replicated objects are served with minimal round-trip.
- **S3-compatible API** — drop-in for the existing `STORAGE_BACKEND=s3`
  path. No code changes.
- **Multi-region by default** — Tigris replicates writes to multiple
  regions automatically.
- **Pricing**: ~$0.02/GB-month storage, $0/GB egress within fly; egress
  to external hosts at standard rates. R2 is $0.015/GB; AWS S3 is
  $0.023/GB plus $0.09/GB egress.

The model in `billingmodel/projections.py` uses $0.02/GB-mo for Tigris.

## Provisioning

```sh
# Creates a bucket and prints credentials.
flyctl storage create kerf-blobs

# Output:
#   BUCKET_NAME=kerf-blobs-abc123
#   AWS_ACCESS_KEY_ID=tid_...
#   AWS_SECRET_ACCESS_KEY=tsec_...
#   AWS_ENDPOINT_URL_S3=https://fly.storage.tigris.dev
```

Map these to Kerf's env vars:

| Tigris var | Kerf env var |
|---|---|
| `BUCKET_NAME` | `KERF_STORAGE_S3_BUCKET` |
| `AWS_ACCESS_KEY_ID` | `KERF_STORAGE_S3_ACCESS_KEY` |
| `AWS_SECRET_ACCESS_KEY` | `KERF_STORAGE_S3_SECRET_KEY` |
| `AWS_ENDPOINT_URL_S3` | `KERF_STORAGE_S3_ENDPOINT` |

Plus pin region to auto-route:

```sh
flyctl secrets set KERF_STORAGE_S3_REGION="auto"
```

## Versioning (recommended)

Enable bucket versioning so that an accidental delete or overwrite is
recoverable. Run once per bucket using the AWS CLI against the Tigris
endpoint:

```sh
aws --endpoint-url=https://fly.storage.tigris.dev \
  s3api put-bucket-versioning \
  --bucket kerf-blobs-abc123 \
  --versioning-configuration Status=Enabled
```

## Lifecycle policies (optional)

Tigris supports S3-compatible lifecycle rules. Useful examples:

- Expire derived artifacts (mesh tessellations) after 30 days unused.
- Transition project thumbnails older than 90 days to colder storage if
  Tigris adds tiering.

```sh
# Apply a lifecycle.json describing your rules:
aws --endpoint-url=https://fly.storage.tigris.dev \
  s3api put-bucket-lifecycle-configuration \
  --bucket kerf-blobs-abc123 \
  --lifecycle-configuration file://lifecycle.json
```

## Limits worth knowing

- **Per-object size**: 5 TiB (S3 standard).
- **Multipart upload threshold**: Kerf uses chunked uploads above ~50MB
  (see `kerf-api` chunked-upload helpers). Tigris fully supports S3
  multipart.
- **Bucket count**: per Tigris org pricing — check the Tigris dashboard.

## Local dev

For local dev or test, point at MinIO instead:

```sh
# In .env or kerf.toml
STORAGE_BACKEND=s3
KERF_STORAGE_S3_ENDPOINT=http://localhost:9000
KERF_STORAGE_S3_BUCKET=kerf-local
KERF_STORAGE_S3_ACCESS_KEY=minioadmin
KERF_STORAGE_S3_SECRET_KEY=minioadmin
```

The `docker-compose.yml` includes a MinIO service for this.

## Troubleshooting

- **403 forbidden on upload**: check `KERF_STORAGE_S3_BUCKET` matches the
  exact bucket name (it's prefixed with a random suffix).
- **Upload latency from non-Fly hosts**: Tigris is highly optimized for
  Fly-native traffic. From Koyeb or other external hosts, uploads go
  through the public `fly.storage.tigris.dev` endpoint; latency is
  comparable to R2 from outside the Fly network.
- **Egress charges**: $0 from inside the Fly network. From Koyeb or
  other external hosts, standard Tigris egress rates apply. If you see
  unexpected egress, verify `KERF_STORAGE_S3_ENDPOINT` is set to
  `https://fly.storage.tigris.dev`.
