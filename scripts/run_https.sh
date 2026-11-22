#!/usr/bin/env bash
# Build the frontend and serve everything from FastAPI over HTTPS (self-signed),
# so phones on the same Wi-Fi can use the camera. Usage: scripts/run_https.sh [port]
set -euo pipefail
PORT="${1:-8443}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/certs"
if [ ! -f "$ROOT/certs/key.pem" ]; then
  IP="$( (ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}') || true)"
  openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
    -keyout "$ROOT/certs/key.pem" -out "$ROOT/certs/cert.pem" \
    -subj "/CN=hccb-lab.local" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1${IP:+,IP:$IP}"
fi
(cd "$ROOT/frontend" && npm run build)
IP="$( (ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}') || echo "<your-LAN-IP>")"
echo
echo "  HCCB Lab:  https://localhost:$PORT    phone:  https://$IP:$PORT"
echo
cd "$ROOT/backend"
exec uvicorn app:app --host 0.0.0.0 --port "$PORT" --ssl-keyfile "$ROOT/certs/key.pem" --ssl-certfile "$ROOT/certs/cert.pem"
