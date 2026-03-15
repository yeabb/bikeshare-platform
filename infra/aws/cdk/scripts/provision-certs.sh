#!/bin/bash
# provision-certs.sh
#
# Creates IoT X.509 certificates for each station and saves them locally.
# Run this once before deploying BikeshareIotStack.
#
# What it does:
#   - For each station: calls `aws iot create-keys-and-certificate` to generate
#     a key pair and certificate signed by AWS IoT CA.
#   - Saves certificate.pem, private.key, and root-ca.pem to certs/{station_id}/
#   - Writes certs/certs-config.json with all certificate ARNs for CDK to read.
#
# Usage:
#   cd infra/aws/cdk
#   bash scripts/provision-certs.sh
#
# After running, deploy the IoT stack:
#   cdk deploy BikeshareIotStack
#
# ⚠️  The certs/ directory is gitignored. Back it up securely — if you lose
#     the private keys you will need to deactivate the certificates in AWS
#     and re-provision new ones.

set -e

REGION="us-east-1"
STATIONS=("S001" "S002" "S003" "S004" "S005")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERTS_DIR="$SCRIPT_DIR/../certs"
CONFIG_FILE="$CERTS_DIR/certs-config.json"

mkdir -p "$CERTS_DIR"

for STATION_ID in "${STATIONS[@]}"; do
  STATION_DIR="$CERTS_DIR/$STATION_ID"

  if [ -f "$STATION_DIR/certificate_arn.txt" ]; then
    echo "[$STATION_ID] Certificate already exists — skipping."
  else
    echo "[$STATION_ID] Creating certificate..."
    mkdir -p "$STATION_DIR"

    RESPONSE=$(aws iot create-keys-and-certificate \
      --set-as-active \
      --region "$REGION" \
      --output json)

    echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['certificatePem'])" \
      > "$STATION_DIR/certificate.pem"

    echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['keyPair']['PrivateKey'])" \
      > "$STATION_DIR/private.key"

    CERT_ARN=$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['certificateArn'])")
    echo "$CERT_ARN" > "$STATION_DIR/certificate_arn.txt"

    # Amazon Root CA — needed by station firmware to verify IoT Core's identity
    curl -s https://www.amazontrust.com/repository/AmazonRootCA1.pem \
      > "$STATION_DIR/root-ca.pem"

    echo "[$STATION_ID] Done: $CERT_ARN"
  fi
done

# Write certs-config.json for CDK to read.
# Reads ARNs from each station's certificate_arn.txt (written above).
python3 - "$CERTS_DIR" "$CONFIG_FILE" <<'EOF'
import json, os, sys

certs_dir = sys.argv[1]
config_file = sys.argv[2]
stations = ["S001", "S002", "S003", "S004", "S005"]

config = {}
for station_id in stations:
    arn_file = os.path.join(certs_dir, station_id, "certificate_arn.txt")
    with open(arn_file) as f:
        config[station_id] = f.read().strip()

with open(config_file, "w") as f:
    json.dump(config, f, indent=2)
    f.write("\n")
EOF

echo ""
echo "✅ Done. Certificate ARNs written to: $CONFIG_FILE"
echo ""
echo "Each station's files are in: certs/{station_id}/"
echo "  certificate.pem   — send to station firmware"
echo "  private.key       — send to station firmware (keep safe)"
echo "  root-ca.pem       — send to station firmware"
echo ""
echo "⚠️  The certs/ directory is gitignored. Back it up securely."
echo ""
echo "Next step: cdk deploy BikeshareIotStack"
