#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  NovaMind Pro v6 — Production VPS Setup
#  Tested on: Ubuntu 22.04 LTS, Debian 12
#  Author: NovaMind Project
# ═══════════════════════════════════════════════════════════

set -e

NOVAMIND_DIR="/opt/novamind"
NOVAMIND_USER="novamind"
GITHUB_REPO="${1:-}"

echo "═══════════════════════════════════════════════════════════"
echo "  🚀 NovaMind Pro v6 — VPS Setup"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ─── 1. System Update ───────────────────────────────────
echo "[1/8] Updating system packages..."
sudo apt update -qq
sudo apt upgrade -y -qq
echo "     ✅ System updated"
echo ""

# ─── 2. Install Dependencies ────────────────────────────
echo "[2/8] Installing dependencies..."
sudo apt install -y -qq \
    python3 python3-pip python3-venv \
    git tmux curl wget nano \
    build-essential \
    ca-certificates
echo "     ✅ Dependencies installed"
echo ""

# ─── 3. Create User ─────────────────────────────────────
echo "[3/8] Creating user '$NOVAMIND_USER'..."
if ! id -u "$NOVAMIND_USER" >/dev/null 2>&1; then
    sudo useradd -m -s /bin/bash "$NOVAMIND_USER"
    echo "     ✅ User created"
else
    echo "     ⏭  User already exists"
fi
echo ""

# ─── 4. Setup Directory ─────────────────────────────────
echo "[4/8] Setting up $NOVAMIND_DIR..."
sudo mkdir -p "$NOVAMIND_DIR"
sudo mkdir -p "$NOVAMIND_DIR/logs"
sudo chown -R "$NOVAMIND_USER:$NOVAMIND_USER" "$NOVAMIND_DIR"
echo "     ✅ Directory ready"
echo ""

# ─── 5. Clone or Copy Project ───────────────────────────
echo "[5/8] Getting NovaMind code..."
if [ -n "$GITHUB_REPO" ]; then
    if [ ! -d "$NOVAMIND_DIR/.git" ]; then
        sudo -u "$NOVAMIND_USER" git clone "$GITHUB_REPO" "$NOVAMIND_DIR"
        echo "     ✅ Cloned from $GITHUB_REPO"
    else
        cd "$NOVAMIND_DIR" && sudo -u "$NOVAMIND_USER" git pull
        echo "     ✅ Updated from git"
    fi
else
    echo "     ⏭  No repo provided. Copy your code to $NOVAMIND_DIR manually."
    echo "        Or run: $0 <github-repo-url>"
fi
echo ""

# ─── 6. Python Dependencies ─────────────────────────────
echo "[6/8] Installing Python packages..."
sudo -u "$NOVAMIND_USER" python3 -m venv "$NOVAMIND_DIR/.venv" 2>/dev/null || true
sudo -u "$NOVAMIND_USER" "$NOVAMIND_DIR/.venv/bin/pip" install --quiet --upgrade pip

# Install deps if requirements.txt exists
if [ -f "$NOVAMIND_DIR/requirements.txt" ]; then
    sudo -u "$NOVAMIND_USER" "$NOVAMIND_DIR/.venv/bin/pip" install --quiet -r "$NOVAMIND_DIR/requirements.txt"
    echo "     ✅ Installed from requirements.txt"
else
    sudo -u "$NOVAMIND_USER" "$NOVAMIND_DIR/.venv/bin/pip" install --quiet \
        python-telegram-bot google-genai tenacity python-dotenv pytest requests
    echo "     ✅ Installed default packages"
fi
echo ""

# ─── 7. Systemd Service ─────────────────────────────────
echo "[7/8] Creating systemd service..."
sudo tee /etc/systemd/system/novamind.service > /dev/null << SVC
[Unit]
Description=NovaMind Pro v6 Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$NOVAMIND_USER
Group=$NOVAMIND_USER
WorkingDirectory=$NOVAMIND_DIR
Environment="PATH=$NOVAMIND_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=-$NOVAMIND_DIR/.env
ExecStart=$NOVAMIND_DIR/.venv/bin/python $NOVAMIND_DIR/daemon.py
Restart=always
RestartSec=10
StandardOutput=append:$NOVAMIND_DIR/logs/daemon.log
StandardError=append:$NOVAMIND_DIR/logs/daemon_error.log

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=$NOVAMIND_DIR

[Install]
WantedBy=multi-user.target
SVC

sudo systemctl daemon-reload
sudo systemctl enable novamind.service
echo "     ✅ Service created & enabled"
echo ""

# ─── 8. Cloudflare Tunnel (optional) ────────────────────
echo "[8/8] Installing cloudflared (for dashboard)..."
if ! command -v cloudflared >/dev/null 2>&1; then
    ARCH=$(dpkg --print-architecture)
    wget -q "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}.deb" \
        -O /tmp/cloudflared.deb
    sudo dpkg -i /tmp/cloudflared.deb >/dev/null 2>&1
    rm -f /tmp/cloudflared.deb
    echo "     ✅ cloudflared installed"
else
    echo "     ⏭  cloudflared already installed"
fi
echo ""

# ─── Done ───────────────────────────────────────────────
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ NovaMind Pro v6 installed successfully!"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo ""
echo "  1. Create .env file with your tokens:"
echo "     sudo -u $NOVAMIND_USER nano $NOVAMIND_DIR/.env"
echo ""
echo "     Required:"
echo "       GITHUB_TOKEN=ghp_..."
echo "       TELEGRAM_BOT_TOKEN=..."
echo "       GEMINI_API_KEY=..."
echo ""
echo "  2. Start the daemon:"
echo "     sudo systemctl start novamind"
echo ""
echo "  3. Check status:"
echo "     sudo systemctl status novamind"
echo "     sudo journalctl -u novamind -f"
echo ""
echo "  4. Dashboard tunnel (optional):"
echo "     cloudflared tunnel --url http://localhost:8000"
echo ""
echo "═══════════════════════════════════════════════════════════"
