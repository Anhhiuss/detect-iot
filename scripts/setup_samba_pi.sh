#!/usr/bin/env bash
set -euo pipefail

# Setup Samba share so Windows can browse Pi folder in Network
# Usage on Pi:
#   chmod +x scripts/setup_samba_pi.sh
#   ./scripts/setup_samba_pi.sh
# Optional:
#   PI_USER=pi4b SHARE_NAME=weedshare SHARE_PATH=/home/pi4b/weed_detection_project ./scripts/setup_samba_pi.sh

PI_USER="${PI_USER:-pi4b}"
SHARE_NAME="${SHARE_NAME:-weedshare}"
SHARE_PATH="${SHARE_PATH:-/home/${PI_USER}/weed_detection_project}"

echo "[INFO] Installing samba..."
sudo apt update
sudo apt install -y samba

echo "[INFO] Ensuring share path exists: ${SHARE_PATH}"
mkdir -p "${SHARE_PATH}"
sudo chown -R "${PI_USER}:${PI_USER}" "${SHARE_PATH}"

CONF="/etc/samba/smb.conf"
BLOCK_START="# --- weed_detection_project share start ---"
BLOCK_END="# --- weed_detection_project share end ---"

if ! grep -q "${BLOCK_START}" "${CONF}"; then
  echo "[INFO] Appending Samba share config..."
  sudo tee -a "${CONF}" >/dev/null <<EOF

${BLOCK_START}
[${SHARE_NAME}]
   comment = Weed Detection Project
   path = ${SHARE_PATH}
   browseable = yes
   read only = no
   writable = yes
   guest ok = no
   valid users = ${PI_USER}
   create mask = 0664
   directory mask = 0775
${BLOCK_END}
EOF
else
  echo "[INFO] Samba share block already exists, skip append."
fi

echo "[INFO] Add/Update Samba password for ${PI_USER} (interactive)..."
sudo smbpasswd -a "${PI_USER}" || true

echo "[INFO] Restart samba services..."
sudo systemctl restart smbd nmbd
sudo systemctl enable smbd nmbd

IP="$(hostname -I | awk '{print $1}')"
echo
echo "[DONE] Samba share is ready."
echo "Windows access path:"
echo "  \\\\${IP}\\${SHARE_NAME}"
echo
echo "If Windows prompts credentials, use:"
echo "  Username: ${PI_USER}"
echo "  Password: (the one you set with smbpasswd)"
