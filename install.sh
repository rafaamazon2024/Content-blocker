#!/bin/bash
# Content Blocker — instalação automática no VPS (Ubuntu 24.04)
# Uso: curl -fsSL <url>/install.sh | bash

set -e

echo ""
echo "=================================================="
echo "  Content Blocker — Setup"
echo "=================================================="
echo ""

# ── 1. Dependências do sistema ──────────────────────────────────────────────
echo "[1/7] Atualizando sistema..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git ufw

# ── 2. Clonar repositório ───────────────────────────────────────────────────
echo "[2/7] Clonando repositório..."
if [ -d /opt/content-blocker ]; then
    cd /opt/content-blocker && git pull
else
    git clone https://github.com/rafaamazon2024/Content-blocker.git /opt/content-blocker
    cd /opt/content-blocker
fi

# ── 3. Ambiente Python ──────────────────────────────────────────────────────
echo "[3/7] Instalando dependências Python..."
python3 -m venv /opt/content-blocker/.venv
/opt/content-blocker/.venv/bin/pip install -q -r /opt/content-blocker/requirements.txt

# ── 4. Configurar .env ──────────────────────────────────────────────────────
echo "[4/7] Configurando variáveis de ambiente..."
if [ ! -f /opt/content-blocker/.env ]; then
    cp /opt/content-blocker/.env.example /opt/content-blocker/.env
    # Gerar token admin aleatório
    ADMIN_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    sed -i "s/change-me-to-a-strong-random-secret/$ADMIN_TOKEN/" /opt/content-blocker/.env
    echo ""
    echo "  ⚠  Guarde este token de admin:"
    echo "     ADMIN_TOKEN=$ADMIN_TOKEN"
    echo ""
fi

# ── 5. Popular blocklist ────────────────────────────────────────────────────
echo "[5/7] Baixando blocklist (~1 milhão de domínios adultos)..."
echo "      Isso pode levar alguns minutos..."
cd /opt/content-blocker
.venv/bin/python blocklist_updater.py

# ── 6. Criar serviços systemd ───────────────────────────────────────────────
echo "[6/7] Criando serviços systemd..."

# Serviço: DNS server
cat > /etc/systemd/system/content-blocker-dns.service << 'EOF'
[Unit]
Description=Content Blocker DNS Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/content-blocker
EnvironmentFile=/opt/content-blocker/.env
ExecStart=/opt/content-blocker/.venv/bin/python dns_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Serviço: API admin
cat > /etc/systemd/system/content-blocker-api.service << 'EOF'
[Unit]
Description=Content Blocker Admin API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/content-blocker
EnvironmentFile=/opt/content-blocker/.env
ExecStart=/opt/content-blocker/.venv/bin/uvicorn api:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Cron: atualização diária da blocklist (03:00)
cat > /etc/cron.d/content-blocker << 'EOF'
0 3 * * * root cd /opt/content-blocker && .venv/bin/python blocklist_updater.py >> /var/log/content-blocker-update.log 2>&1
EOF

systemctl daemon-reload
systemctl enable content-blocker-dns content-blocker-api
systemctl start  content-blocker-dns content-blocker-api

# ── 7. Firewall ─────────────────────────────────────────────────────────────
echo "[7/7] Configurando firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH — não fechar!
ufw allow 53/udp    # DNS
ufw allow 53/tcp    # DNS (respostas grandes)
ufw allow 8080/tcp  # API admin
ufw --force enable

# ── Resultado ───────────────────────────────────────────────────────────────
echo ""
echo "=================================================="
echo "  Instalação concluída!"
echo "=================================================="
IP=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
echo ""
echo "  IP do servidor : $IP"
echo "  DNS            : $IP (porta 53)"
echo "  API admin      : http://$IP:8080"
echo ""
echo "  Verificar status:"
echo "    systemctl status content-blocker-dns"
echo "    systemctl status content-blocker-api"
echo ""
echo "  Ver logs:"
echo "    journalctl -u content-blocker-dns -f"
echo ""
echo "  Use o IP acima no app Android e no setup_windows.py"
echo "=================================================="
