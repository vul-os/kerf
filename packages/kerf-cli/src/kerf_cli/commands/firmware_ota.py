"""kerf_cli.commands.firmware_ota — `kerf firmware ota` subcommands.

Commands:
  kerf firmware ota keygen [--out <path>]
      Generate a new ed25519 keypair and save the private key as a PEM file.
      Prints the hex-encoded public key (embed this in your firmware).

  kerf firmware ota release --key <pem> --firmware <bin> --version <ver> \\
                             --device-type <type> [--url <download-url>]
      Sign a firmware binary and POST the release manifest to the Kerf server.
      Prints the manifest JSON on success.

  kerf firmware ota pubkey --key <pem>
      Print the hex-encoded public key for an existing keypair.

The private key never leaves the developer's machine.  Only the manifest
(version, sha256, ed25519_signature, public_key) is uploaded to the server.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _get_signer_class():
    """Lazy import so the module loads even when cryptography is absent."""
    from kerf_firmware.ota.sign import OTASigner
    return OTASigner


def cmd_keygen(args: argparse.Namespace) -> int:
    """Generate a new ed25519 keypair."""
    OTASigner = _get_signer_class()
    out = args.out or "kerf_ota_key.pem"

    if Path(out).exists() and not getattr(args, "force", False):
        print(f"Error: {out!r} already exists.  Use --force to overwrite.", file=sys.stderr)
        return 1

    signer = OTASigner.from_new_keypair()
    signer.save_pem(out)
    print(f"Private key saved to: {out}  (chmod 600 applied)")
    print(f"Public key (hex, embed in firmware):\n{signer.public_key_bytes.hex()}")
    return 0


def cmd_pubkey(args: argparse.Namespace) -> int:
    """Print the public key for an existing private key PEM."""
    OTASigner = _get_signer_class()
    signer = OTASigner.from_pem(args.key)
    print(signer.public_key_bytes.hex())
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    """Sign a firmware binary and POST the release to the Kerf server."""
    OTASigner = _get_signer_class()

    fw_path = args.firmware
    if not Path(fw_path).exists():
        print(f"Error: firmware file not found: {fw_path!r}", file=sys.stderr)
        return 1

    signer = OTASigner.from_pem(args.key)
    manifest = signer.sign_image(
        fw_path=fw_path,
        version=args.version,
        device_type=args.device_type,
        download_url=getattr(args, "url", "") or "",
    )

    print("Manifest:")
    print(manifest.to_json())

    server = getattr(args, "server", None)
    if server:
        import urllib.request
        import urllib.error

        payload = json.dumps(json.loads(manifest.to_json())).encode()
        url = server.rstrip("/") + "/v1/ota/release"
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                body = resp.read().decode()
                print(f"Server response ({resp.status}): {body}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            print(f"Server returned {exc.code}: {body}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"Failed to reach server: {exc}", file=sys.stderr)
            return 1

    return 0


# ---------------------------------------------------------------------------
# argparse integration (used when the CLI dispatches to this module)
# ---------------------------------------------------------------------------

def build_parser(subparsers=None):
    """Build the `firmware ota` argument parser."""
    if subparsers is not None:
        p = subparsers.add_parser("ota", help="OTA firmware update commands")
    else:
        p = argparse.ArgumentParser(prog="kerf firmware ota")

    sub = p.add_subparsers(dest="ota_cmd", required=True)

    # keygen
    kg = sub.add_parser("keygen", help="Generate a new ed25519 OTA keypair")
    kg.add_argument("--out", default="kerf_ota_key.pem",
                    help="Output PEM file path (default: kerf_ota_key.pem)")
    kg.add_argument("--force", action="store_true",
                    help="Overwrite existing key file")

    # pubkey
    pk = sub.add_parser("pubkey", help="Print public key for an existing keypair")
    pk.add_argument("--key", required=True, help="Path to the private key PEM file")

    # release
    rel = sub.add_parser("release", help="Sign and register an OTA firmware release")
    rel.add_argument("--key", required=True, help="Path to the private key PEM file")
    rel.add_argument("--firmware", required=True, help="Path to the firmware .bin file")
    rel.add_argument("--version", required=True, help="Release version string (e.g. 1.2.3)")
    rel.add_argument("--device-type", required=True,
                     dest="device_type", help="Device family (e.g. esp32, stm32, samd)")
    rel.add_argument("--url", default="",
                     help="Download URL for the signed firmware image")
    rel.add_argument("--server", default="",
                     help="Kerf server base URL (e.g. http://localhost:8000); "
                          "if omitted, only prints the manifest without uploading")

    return p


def dispatch(args: argparse.Namespace) -> int:
    """Dispatch to the correct ota sub-command handler."""
    handlers = {
        "keygen":  cmd_keygen,
        "pubkey":  cmd_pubkey,
        "release": cmd_release,
    }
    handler = handlers.get(args.ota_cmd)
    if handler is None:
        print(f"Unknown ota command: {args.ota_cmd!r}", file=sys.stderr)
        return 1
    return handler(args)


if __name__ == "__main__":
    parser = build_parser()
    parsed = parser.parse_args()
    sys.exit(dispatch(parsed))
