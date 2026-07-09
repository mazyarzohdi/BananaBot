#!/usr/bin/env bash
# =============================================================================
#  BananaBot — Automated Installation & Configuration Script
#  GitHub: https://github.com/mazyarzohdi/BananaBot
# =============================================================================

set -euo pipefail

# ── Redirect stdin to /dev/tty so read works when piped through curl ─────────
# When running as: bash <(curl ...), stdin is the script itself, not the terminal.
exec < /dev/tty

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

# ── Variables ────────────────────────────────────────────────────────────────
REPO_URL="https://github.com/mazyarzohdi/BananaBot"
INSTALL_DIR="/opt/BananaBot"
WEBAPP_DIR="$INSTALL_DIR/webapp"
SERVICE_NAME="bananabot"
WEBAPP_SERVICE="bananabot-web"
PYTHON_MIN="3.11"
VENV_DIR="$INSTALL_DIR/.venv"
WEBAPP_VENV="$WEBAPP_DIR/.venv"
LOG_FILE="/var/log/bananabot-install.log"

# ── Config vars (populated by collect_config) ────────────────────────────────
BOT_TOKEN=""; ADMIN_IDS=""; CARD_NUMBER=""; CARD_HOLDER=""
REQUIRED_CHANNEL=""; DEFAULT_LANG="fa"
SETUP_WEBAPP="no"
WEB_DOMAIN=""; WEB_PORT="8080"; WEB_PATH="/panel"
SSL_CERT=""; SSL_KEY=""

# ── Helpers ──────────────────────────────────────────────────────────────────
log()    { echo -e "${CYAN}[INFO]${NC}  $*" | tee -a "$LOG_FILE"; }
success(){ echo -e "${GREEN}[OK]${NC}    $*" | tee -a "$LOG_FILE"; }
warn()   { echo -e "${YELLOW}[WARN]${NC}  $*" | tee -a "$LOG_FILE"; }
error()  { echo -e "${RED}[ERROR]${NC} $*" | tee -a "$LOG_FILE"; exit 1; }

print_banner() {
cat << 'EOF'

  ██████╗  █████╗ ███╗   ██╗ █████╗ ███╗   ██╗ █████╗ ██████╗  ██████╗ ████████╗
  ██╔══██╗██╔══██╗████╗  ██║██╔══██╗████╗  ██║██╔══██╗██╔══██╗██╔═══██╗╚══██╔══╝
  ██████╔╝███████║██╔██╗ ██║███████║██╔██╗ ██║███████║██████╔╝██║   ██║   ██║
  ██╔══██╗██╔══██║██║╚██╗██║██╔══██║██║╚██╗██║██╔══██║██╔══██╗██║   ██║   ██║
  ██████╔╝██║  ██║██║ ╚████║██║  ██║██║ ╚████║██║  ██║██████╔╝╚██████╔╝   ██║
  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═════╝  ╚═════╝    ╚═╝

  Automated Setup — github.com/mazyarzohdi/BananaBot
EOF
echo ""
}

check_root() {
    [[ $EUID -ne 0 ]] && error "Must be run as root. Use: sudo bash install.sh"
}

check_os() {
    log "Detecting operating system..."
    if ! command -v apt-get &>/dev/null && ! command -v yum &>/dev/null; then
        error "Only Debian/Ubuntu and CentOS/RHEL are supported."
    fi
    success "OS detected."
}

install_system_deps() {
    log "Installing system dependencies..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq
        apt-get install -y -qq python3 python3-pip python3-venv git curl unzip >> "$LOG_FILE" 2>&1
    else
        yum install -y python3 python3-pip git curl unzip >> "$LOG_FILE" 2>&1
    fi
    success "System dependencies installed."
}

check_python() {
    log "Checking Python version..."
    command -v python3 &>/dev/null || error "Python3 not found!"
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_OK=$(python3 -c "import sys; print(1 if sys.version_info >= (3,11) else 0)")
    [[ "$PY_OK" != "1" ]] && error "Python $PYTHON_MIN+ required. Found: $PY_VER"
    success "Python $PY_VER detected."
}

clone_or_update_repo() {
    log "Fetching project from GitHub..."
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        warn "Directory exists. Updating..."
        git -C "$INSTALL_DIR" pull --ff-only >> "$LOG_FILE" 2>&1 || warn "git pull failed — using existing files."
    else
        git clone "$REPO_URL" "$INSTALL_DIR" >> "$LOG_FILE" 2>&1
    fi
    success "Project placed at $INSTALL_DIR"
}

create_virtualenv() {
    log "Creating Python virtual environment for bot..."
    python3 -m venv "$VENV_DIR" >> "$LOG_FILE" 2>&1
    "$VENV_DIR/bin/pip" install --upgrade pip --quiet >> "$LOG_FILE" 2>&1
    success "Bot virtual environment created."
}

install_python_deps() {
    log "Installing bot Python packages..."
    "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --quiet >> "$LOG_FILE" 2>&1
    success "Bot packages installed."
}

# ── Configuration wizard ──────────────────────────────────────────────────────
collect_config() {
    echo ""
    echo -e "${BOLD}════════════════════════════════════════════${NC}"
    echo -e "${BOLD}   Bot Configuration — Please fill in info  ${NC}"
    echo -e "${BOLD}════════════════════════════════════════════${NC}"
    echo ""

    # 1) Bot token
    while true; do
        echo -e "${CYAN}1) Telegram Bot Token (from @BotFather):${NC}"
        read -rp "   BOT_TOKEN: " BOT_TOKEN
        BOT_TOKEN="${BOT_TOKEN// /}"
        [[ -n "$BOT_TOKEN" && "$BOT_TOKEN" != "your_bot_token_here" ]] && break
        warn "Invalid token. Please try again."
    done

    # 2) Admin IDs
    echo ""
    echo -e "${CYAN}2) Admin numeric ID(s) — separate multiple with commas:${NC}"
    echo -e "   ${YELLOW}Example: 123456789  or  123456789,987654321${NC}"
    while true; do
        read -rp "   ADMIN_IDS: " ADMIN_IDS
        ADMIN_IDS="${ADMIN_IDS// /}"
        ADMIN_IDS="${ADMIN_IDS#[}"; ADMIN_IDS="${ADMIN_IDS%]}"
        if [[ "$ADMIN_IDS" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
            ADMIN_IDS="[${ADMIN_IDS}]"
            break
        fi
        warn "Invalid format. Only digits and commas allowed."
    done

    # 3) Card number (optional)
    echo ""
    echo -e "${CYAN}3) Card number for payments (optional — Enter to skip):${NC}"
    echo -e "   ${YELLOW}Example: 6037-1234-5678-9012${NC}"
    read -rp "   CARD_NUMBER: " CARD_NUMBER
    CARD_NUMBER="${CARD_NUMBER// /}"

    if [[ -n "$CARD_NUMBER" ]]; then
        echo ""
        echo -e "${CYAN}4) Card holder name:${NC}"
        read -rp "   CARD_HOLDER: " CARD_HOLDER
    else
        CARD_HOLDER=""
    fi

    # 5) Required channel (optional)
    echo ""
    echo -e "${CYAN}5) Required Telegram channel (optional — Enter to skip):${NC}"
    echo -e "   ${YELLOW}Example: @mychannel${NC}"
    read -rp "   REQUIRED_CHANNEL: " REQUIRED_CHANNEL
    REQUIRED_CHANNEL="${REQUIRED_CHANNEL// /}"

    # 6) Language
    echo ""
    echo -e "${CYAN}6) Default bot language:${NC}"
    echo "   [1] Persian / Farsi (fa) — default"
    echo "   [2] English (en)"
    read -rp "   Choice [1/2]: " LANG_CHOICE
    case "$LANG_CHOICE" in
        2) DEFAULT_LANG="en" ;;
        *) DEFAULT_LANG="fa" ;;
    esac

    # 7) Web Panel (optional)
    echo ""
    echo -e "${BOLD}════════════════════════════════════════════${NC}"
    echo -e "${BOLD}   Web Panel Configuration (Optional)       ${NC}"
    echo -e "${BOLD}════════════════════════════════════════════${NC}"
    echo -e "   ${YELLOW}Press Enter on the domain field to skip web panel setup.${NC}"
    echo ""
    echo -e "${CYAN}7) Domain or server IP for web panel:${NC}"
    echo -e "   ${YELLOW}Example: panel.example.com  or  1.2.3.4${NC}"
    read -rp "   DOMAIN (Enter to skip): " WEB_DOMAIN
    WEB_DOMAIN="${WEB_DOMAIN// /}"

    if [[ -n "$WEB_DOMAIN" ]]; then
        SETUP_WEBAPP="yes"

        echo ""
        echo -e "${CYAN}8) Web panel port [default: 8080]:${NC}"
        read -rp "   PORT: " WEB_PORT
        WEB_PORT="${WEB_PORT// /}"
        WEB_PORT="${WEB_PORT:-8080}"

        echo ""
        echo -e "${CYAN}9) URL path for the panel [default: /panel]:${NC}"
        echo -e "   ${YELLOW}Example: /panel  →  http://domain:port/panel${NC}"
        read -rp "   WEB_PATH: " WEB_PATH
        WEB_PATH="${WEB_PATH// /}"
        WEB_PATH="${WEB_PATH:-/panel}"
        [[ "${WEB_PATH:0:1}" != "/" ]] && WEB_PATH="/${WEB_PATH}"

        echo ""
        echo -e "${CYAN}10) SSL certificate path (optional — Enter to skip):${NC}"
        echo -e "    ${YELLOW}Example: /etc/letsencrypt/live/domain/fullchain.pem${NC}"
        read -rp "    SSL_CERT: " SSL_CERT
        SSL_CERT="${SSL_CERT// /}"

        if [[ -n "$SSL_CERT" ]]; then
            echo ""
            echo -e "${CYAN}11) SSL private key path:${NC}"
            read -rp "    SSL_KEY: " SSL_KEY
            SSL_KEY="${SSL_KEY// /}"
        else
            SSL_KEY=""
        fi
    else
        SETUP_WEBAPP="no"
        WEB_DOMAIN=""; WEB_PORT="8080"; WEB_PATH="/panel"
        SSL_CERT=""; SSL_KEY=""
    fi

    echo ""
    success "Configuration collected."
}

write_env_file() {
    log "Writing bot .env file..."
    cat > "$INSTALL_DIR/.env" << EOF
# Generated by install.sh — $(date)
BOT_TOKEN=${BOT_TOKEN}
ADMIN_IDS=${ADMIN_IDS}
DATABASE_PATH=data/bot.db
DEFAULT_LANG=${DEFAULT_LANG}
CARD_NUMBER=${CARD_NUMBER}
CARD_HOLDER=${CARD_HOLDER}
REQUIRED_CHANNEL=${REQUIRED_CHANNEL}
WEB_DOMAIN=${WEB_DOMAIN}
WEB_PORT=${WEB_PORT}
WEB_PATH=${WEB_PATH}
SSL_CERT=${SSL_CERT}
SSL_KEY=${SSL_KEY}
EOF
    chmod 600 "$INSTALL_DIR/.env"
    success "Bot .env file created."
}

create_data_dir() {
    mkdir -p "$INSTALL_DIR/data"
    chown -R root:root "$INSTALL_DIR"
    success "data/ directory ready."
}

create_systemd_service() {
    log "Creating bot systemd service..."
    cat > "/etc/systemd/system/${SERVICE_NAME}.service" << EOF
[Unit]
Description=BananaBot — Telegram Bot
After=network.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${VENV_DIR}/bin/python main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${SERVICE_NAME}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME" >> "$LOG_FILE" 2>&1
    success "Bot systemd service created and enabled."
}

# ── Web Panel Setup ────────────────────────────────────────────────────────────
setup_webapp() {
    if [[ "$SETUP_WEBAPP" != "yes" ]]; then
        log "Skipping web panel setup."
        return
    fi

    log "Setting up web panel..."

    # Check webapp directory exists
    if [[ ! -d "$WEBAPP_DIR" ]]; then
        warn "webapp/ directory not found in $INSTALL_DIR. Skipping web panel."
        SETUP_WEBAPP="no"
        return
    fi

    # Virtual env for webapp
    log "Creating web panel virtual environment..."
    python3 -m venv "$WEBAPP_VENV" >> "$LOG_FILE" 2>&1
    "$WEBAPP_VENV/bin/pip" install --upgrade pip --quiet >> "$LOG_FILE" 2>&1
    "$WEBAPP_VENV/bin/pip" install -r "$WEBAPP_DIR/requirements.txt" --quiet >> "$LOG_FILE" 2>&1
    success "Web panel packages installed."

    # Generate Django secret key
    DJANGO_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")

    # Write webapp .env
    cat > "$WEBAPP_DIR/.env" << EOF
DJANGO_SECRET_KEY=${DJANGO_SECRET}
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=${WEB_DOMAIN},localhost,127.0.0.1
BOT_TOKEN=${BOT_TOKEN}
ADMIN_IDS=${ADMIN_IDS}
BOT_DB_PATH=${INSTALL_DIR}/data/bot.db
WEB_PATH=${WEB_PATH}
WEB_PORT=${WEB_PORT}
SSL_CERT=${SSL_CERT}
SSL_KEY=${SSL_KEY}
EOF
    chmod 600 "$WEBAPP_DIR/.env"

    # Build SSL args for gunicorn
    SSL_ARGS=""
    if [[ -n "$SSL_CERT" && -f "$SSL_CERT" && -n "$SSL_KEY" && -f "$SSL_KEY" ]]; then
        SSL_ARGS="    --certfile \"${SSL_CERT}\" \\\\\n    --keyfile  \"${SSL_KEY}\" \\\\"
    fi

    # Create gunicorn startup script
    cat > "$WEBAPP_DIR/start_webapp.sh" << STARTEOF
#!/usr/bin/env bash
set -a
source "\$(dirname "\$0")/.env"
set +a
exec "\$(dirname "\$0")/.venv/bin/gunicorn" \\
    --workers 2 \\
    --bind "0.0.0.0:\${WEB_PORT:-8080}" \\
    --access-logfile /var/log/bananabot-web-access.log \\
    --error-logfile  /var/log/bananabot-web-error.log \\
    bananabot_web.wsgi:application
STARTEOF
    chmod +x "$WEBAPP_DIR/start_webapp.sh"

    # Inject SSL args into startup script if provided
    if [[ -n "$SSL_ARGS" ]]; then
        sed -i "s|bananabot_web.wsgi:application|--certfile \"${SSL_CERT}\" \\\\\n    --keyfile  \"${SSL_KEY}\" \\\\\n    bananabot_web.wsgi:application|" "$WEBAPP_DIR/start_webapp.sh"
    fi

    # Collect static files
    log "Collecting static files..."
    cd "$WEBAPP_DIR"
    export DJANGO_SECRET_KEY="$DJANGO_SECRET"
    export DJANGO_DEBUG=0
    export DJANGO_ALLOWED_HOSTS="${WEB_DOMAIN},localhost"
    export BOT_TOKEN="$BOT_TOKEN"
    export ADMIN_IDS="$ADMIN_IDS"
    export BOT_DB_PATH="${INSTALL_DIR}/data/bot.db"
    export WEB_PATH="$WEB_PATH"
    "$WEBAPP_VENV/bin/python" manage.py collectstatic --noinput >> "$LOG_FILE" 2>&1
    "$WEBAPP_VENV/bin/python" manage.py migrate --run-syncdb >> "$LOG_FILE" 2>&1
    cd "$INSTALL_DIR"
    success "Static files collected."

    # systemd service for webapp
    log "Creating web panel systemd service..."
    cat > "/etc/systemd/system/${WEBAPP_SERVICE}.service" << EOF
[Unit]
Description=BananaBot Web Panel
After=network.target

[Service]
Type=simple
WorkingDirectory=${WEBAPP_DIR}
ExecStart=${WEBAPP_DIR}/start_webapp.sh
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${WEBAPP_SERVICE}

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable "$WEBAPP_SERVICE" >> "$LOG_FILE" 2>&1
    systemctl start  "$WEBAPP_SERVICE"
    sleep 2

    if systemctl is-active --quiet "$WEBAPP_SERVICE"; then
        success "Web panel started on port ${WEB_PORT}."
    else
        warn "Web panel failed to start. Check: journalctl -u ${WEBAPP_SERVICE} -n 50"
    fi
}

start_bot() {
    log "Starting bot..."
    systemctl start "$SERVICE_NAME"
    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        success "Bot started successfully!"
    else
        warn "Bot did not start. Check logs:"
        echo "    journalctl -u $SERVICE_NAME -n 30 --no-pager"
    fi
}

print_summary() {
    echo ""
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${GREEN}   Installation complete!                   ${NC}"
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  Install path:      ${CYAN}$INSTALL_DIR${NC}"
    echo -e "  Bot config:        ${CYAN}$INSTALL_DIR/.env${NC}"
    echo -e "  Install log:       ${CYAN}$LOG_FILE${NC}"
    echo ""
    echo -e "  ${BOLD}Management panel:${NC}"
    echo -e "    ${CYAN}sudo bash $INSTALL_DIR/manage.sh${NC}"
    echo ""
    echo -e "  ${BOLD}Bot quick commands:${NC}"
    echo -e "    Start:    ${CYAN}systemctl start $SERVICE_NAME${NC}"
    echo -e "    Stop:     ${CYAN}systemctl stop $SERVICE_NAME${NC}"
    echo -e "    Logs:     ${CYAN}journalctl -u $SERVICE_NAME -f${NC}"

    if [[ "$SETUP_WEBAPP" == "yes" ]]; then
        PROTO="http"
        [[ -n "$SSL_CERT" ]] && PROTO="https"
        echo ""
        echo -e "  ${BOLD}Web Panel:${NC}"
        echo -e "    URL:    ${CYAN}${PROTO}://${WEB_DOMAIN}:${WEB_PORT}${WEB_PATH}/${NC}"
        echo -e "    Config: ${CYAN}$WEBAPP_DIR/.env${NC}"
        echo -e "    Start:  ${CYAN}systemctl start $WEBAPP_SERVICE${NC}"
        echo -e "    Logs:   ${CYAN}journalctl -u $WEBAPP_SERVICE -f${NC}"
        echo ""
        echo -e "  ${YELLOW}NOTE: Login via Telegram Login Widget.${NC}"
        echo -e "  ${YELLOW}Make sure bot username is set in @BotFather settings (domain).${NC}"
    fi
    echo ""
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
    print_banner
    touch "$LOG_FILE"
    log "Starting installation — $(date)"

    check_root
    check_os
    install_system_deps
    check_python
    clone_or_update_repo
    create_virtualenv
    install_python_deps
    collect_config
    write_env_file
    create_data_dir
    create_systemd_service
    setup_webapp
    start_bot
    print_summary
}

main "$@"
