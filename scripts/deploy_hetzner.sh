#!/usr/bin/env bash
# Deploy Persian_type to the Hetzner VPS.
# Usage:
#   export HETZNER_HOST=204.168.246.73
#   export HETZNER_USER=root
#   export HETZNER_SSH_KEY=/path/to/private_key   # or paste PEM into this env var
#   ./scripts/deploy_hetzner.sh
set -euo pipefail

HOST="${HETZNER_HOST:-204.168.246.73}"
USER_NAME="${HETZNER_USER:-root}"
APP_DIR="${HETZNER_APP_DIR:-/opt/persian-type}"
BRANCH="${HETZNER_BRANCH:-cursor/bid-7156}"
REPO_URL="${HETZNER_REPO:-https://github.com/robotvision03-dotcom/Persian_type.git}"
KEY_FILE="${HETZNER_SSH_KEY_FILE:-$HOME/.ssh/hetzner_persian_type}"
DOWNLOAD_ASR="${HETZNER_DOWNLOAD_ASR:-1}"

if [[ -n "${HETZNER_SSH_KEY:-}" && "${HETZNER_SSH_KEY}" == *"BEGIN"* ]]; then
  KEY_FILE="$(mktemp)"
  printf '%s\n' "$HETZNER_SSH_KEY" >"$KEY_FILE"
  chmod 600 "$KEY_FILE"
  trap 'rm -f "$KEY_FILE"' EXIT
fi

if [[ ! -f "$KEY_FILE" ]]; then
  echo "Missing SSH key. Set HETZNER_SSH_KEY (PEM) or HETZNER_SSH_KEY_FILE." >&2
  exit 1
fi

SSH=(ssh -i "$KEY_FILE" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new)

echo "Checking SSH to ${USER_NAME}@${HOST}..."
"${SSH[@]}" "${USER_NAME}@${HOST}" 'echo connected; hostname; whoami'

echo "Installing packages and app on ${HOST}..."
"${SSH[@]}" "${USER_NAME}@${HOST}" bash -s -- "$APP_DIR" "$REPO_URL" "$BRANCH" "$DOWNLOAD_ASR" "$HOST" <<'REMOTE'
set -euo pipefail
APP_DIR="$1"
REPO_URL="$2"
BRANCH="$3"
DOWNLOAD_ASR="$4"
PUBLIC_HOST="$5"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git nginx curl openssl

mkdir -p "$APP_DIR"
if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" fetch origin
  git -C "$APP_DIR" checkout "$BRANCH"
  git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
else
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

mkdir -p /var/lib/persian-type
mkdir -p "$APP_DIR/models"

if [[ "$DOWNLOAD_ASR" == "1" ]]; then
  bash "$APP_DIR/scripts/download_shenava_ctc.sh" "$APP_DIR/models"
fi

cat >/etc/systemd/system/persian-type.service <<EOF
[Unit]
Description=Persian Type dealership portal
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
Environment=PERSIAN_TYPE_DATA=/var/lib/persian-type
Environment=MODELS_DIR=$APP_DIR/models
ExecStart=$APP_DIR/.venv/bin/python -m app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/nginx/sites-available/persian-type <<EOF
upstream persian_type_app {
    server 127.0.0.1:8000;
}

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;

    client_max_body_size 32m;
    ssl_certificate     /etc/nginx/ssl/persian-type.crt;
    ssl_certificate_key /etc/nginx/ssl/persian-type.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://persian_type_app;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
EOF

mkdir -p /etc/nginx/ssl
if [[ ! -f /etc/nginx/ssl/persian-type.crt ]]; then
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout /etc/nginx/ssl/persian-type.key \
    -out /etc/nginx/ssl/persian-type.crt \
    -subj "/CN=${PUBLIC_HOST}" \
    -addext "subjectAltName=IP:${PUBLIC_HOST}"
fi
chmod 600 /etc/nginx/ssl/persian-type.key

ln -sfn /etc/nginx/sites-available/persian-type /etc/nginx/sites-enabled/persian-type
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl daemon-reload
systemctl enable --now persian-type
systemctl restart persian-type
systemctl reload nginx

# Give the app a moment, then warm the ASR model into memory.
sleep 2
curl -fsS -X POST http://127.0.0.1:8000/api/boot || true
echo

if command -v ufw >/dev/null 2>&1; then
  ufw allow OpenSSH || true
  ufw allow 80/tcp || true
  ufw allow 443/tcp || true
  ufw --force enable || true
fi

systemctl --no-pager --full status persian-type | sed -n '1,20p'
curl -fsSk "https://127.0.0.1/" | head -c 200 || true
echo
echo "Deployed $APP_DIR on branch $BRANCH"
REMOTE

echo "Public URL: https://${HOST}/"
echo "Office: https://${HOST}/office"
echo "Buyer:  https://${HOST}/buyer"
echo "Voice:  open HTTPS, accept cert warning, then شروع تماس (Allow microphone)"
