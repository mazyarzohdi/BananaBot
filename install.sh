#!/usr/bin/env bash
# =============================================================================
#  BananaBot — Automated Installation & Configuration Script
#  GitHub: https://github.com/mazyarzohdi/BananaBot
# =============================================================================

set -euo pipefail

# ── Force a UTF-8 locale ──────────────────────────────────────────────────────
# Many minimal VPS images have no locale configured at all (LANG/LC_ALL unset,
# effectively "C"/"POSIX"). Under that locale, bash's `read` builtin can fail
# to correctly assemble multi-byte UTF-8 characters typed or pasted at a
# prompt (e.g. a Persian CARD_HOLDER name) — the bytes get corrupted, install
# still "succeeds", and the bot crashes much later with a confusing
# `UnicodeDecodeError` when it tries to read the resulting .env file. Force a
# UTF-8 locale up front so that never happens, using whichever UTF-8 locale is
# actually available on this system.
for _candidate_locale in C.UTF-8 en_US.UTF-8; do
    if locale -a 2>/dev/null | grep -qi "^${_candidate_locale//./\\.}$"; then
        export LANG="$_candidate_locale" LC_ALL="$_candidate_locale"
        break
    fi
done
unset _candidate_locale

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
WEBHOOK_SERVICE="bananabot-webhook"
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

# ── Fail loudly, not silently ────────────────────────────────────────────────
# With `set -e`, any failing command (apt-get, git, pip, ...) kills the script
# immediately — and since most of those commands redirect their own output
# into $LOG_FILE, the terminal itself would otherwise show NOTHING beyond the
# last [INFO] line, leaving no clue what went wrong. This trap catches that
# and prints the actual error plus the tail of the log before exiting.
on_error() {
    local exit_code=$? line_no=$1
    echo ""
    echo -e "${RED}[ERROR]${NC} Installation failed (line $line_no, exit code $exit_code)."
    if [[ -f "$LOG_FILE" ]]; then
        echo -e "${YELLOW}Last lines of $LOG_FILE:${NC}"
        tail -n 20 "$LOG_FILE"
    fi
    echo ""
    echo -e "Full log: ${CYAN}$LOG_FILE${NC}"
    echo -e "Re-run this script after fixing the issue above — it's safe to run again."
    exit "$exit_code"
}
trap 'on_error $LINENO' ERR

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
    if [[ $EUID -ne 0 ]]; then
        error "Must be run as root. Use: sudo bash install.sh"
    fi
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
        # On freshly-created VPS instances, cloud-init or unattended-upgrades
        # is often still running its own apt/dpkg operations in the
        # background. If our apt-get runs while that's mid-flight (or if a
        # previous session got interrupted, e.g. by a reboot), dpkg ends up
        # in a broken state where EVERY subsequent apt-get call fails with:
        #   "E: dpkg was interrupted, you must manually run
        #    'dpkg --configure -a' to correct the problem."
        # Detect and fix both cases automatically instead of forcing the
        # admin to SSH back in and run this by hand.
        if command -v fuser &>/dev/null && [[ -f /var/lib/dpkg/lock-frontend ]]; then
            local waited=0
            while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do
                [[ "$waited" -eq 0 ]] && log "Another apt/dpkg process is running (e.g. automatic system updates) — waiting for it to finish..."
                waited=$((waited+5))
                if [[ "$waited" -gt 300 ]]; then
                    warn "Still locked after 5 minutes — continuing anyway."
                    break
                fi
                sleep 5
            done
        fi
        dpkg --configure -a >> "$LOG_FILE" 2>&1 || true
        apt-get update -qq >> "$LOG_FILE" 2>&1
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
    if [[ "$PY_OK" != "1" ]]; then
        error "Python $PYTHON_MIN+ required. Found: $PY_VER"
    fi
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
        if [[ -n "$BOT_TOKEN" && "$BOT_TOKEN" != "your_bot_token_here" ]]; then
            break
        fi
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

    # Catch a corrupted CARD_HOLDER (or any other field) NOW, with a clear
    # actionable message — instead of the bot crashing much later with a
    # confusing UnicodeDecodeError from deep inside python-dotenv the first
    # time it starts.
    if ! python3 -c "open('$INSTALL_DIR/.env', encoding='utf-8').read()" 2>/dev/null; then
        warn ".env contains invalid UTF-8 bytes (likely from a Persian/Arabic"
        warn "field typed at a prompt above getting mangled by the terminal)."
        warn "The bot WILL crash on startup until this is fixed. After install"
        warn "finishes, fix it with: manage.sh → option to change the card"
        warn "info, or edit $INSTALL_DIR/.env directly and re-save it as UTF-8."
    fi

    success "Bot .env file created."
}

create_data_dir() {
    mkdir -p "$INSTALL_DIR/data"
    chown -R root:root "$INSTALL_DIR"
    success "data/ directory ready."
}

init_database_schema() {
    log "Initializing database schema..."
    "$VENV_DIR/bin/python" "$INSTALL_DIR/db_schema.py" "$INSTALL_DIR/data/bot.db" >> "$LOG_FILE" 2>&1
    success "Database ready."
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

create_webhook_service() {
    log "Creating auto-payment webhook systemd service..."
    cat > "/etc/systemd/system/${WEBHOOK_SERVICE}.service" << EOF
[Unit]
Description=BananaBot — Auto-Payment Webhook (bank SMS)
After=network.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${VENV_DIR}/bin/python payment_webhook_server.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=${WEBHOOK_SERVICE}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "$WEBHOOK_SERVICE" >> "$LOG_FILE" 2>&1
    systemctl restart "$WEBHOOK_SERVICE"
    if systemctl is-active --quiet "$WEBHOOK_SERVICE"; then
        success "Auto-payment webhook service running (currently disabled until you turn it on and set a secret — see AUTO_PAYMENT_SETUP.md)."
    else
        warn "Webhook service failed to start. Check: journalctl -u ${WEBHOOK_SERVICE} -n 30"
    fi
}

# ── Web Panel Setup ────────────────────────────────────────────────────────────
setup_webapp() {
    if [[ "$SETUP_WEBAPP" != "yes" ]]; then
        log "Skipping web panel setup."
        return
    fi

    log "Setting up web panel..."
    source "$INSTALL_DIR/lib/webapp_lib.sh"
    webapp_deploy || SETUP_WEBAPP="no"
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
        [[ -n "$SSL_CERT" && -f "$SSL_CERT" ]] && PROTO="https"
        echo ""
        echo -e "  ${BOLD}Web Panel:${NC}"
        echo -e "    URL:    ${CYAN}${PROTO}://${WEB_DOMAIN}:${WEB_PORT}${WEB_PATH}/${NC}"
        echo -e "    Config: ${CYAN}$WEBAPP_DIR/.env${NC}"
        echo -e "    Start:  ${CYAN}systemctl start $WEBAPP_SERVICE${NC}"
        echo -e "    Logs:   ${CYAN}journalctl -u $WEBAPP_SERVICE -f${NC}"
        echo ""
        if [[ "$PROTO" == "https" ]]; then
            echo -e "  ${YELLOW}To open the panel as a Telegram Mini App (button inside the bot):${NC}"
            echo -e "  ${YELLOW}1. Open @BotFather → /mybots → your bot → Bot Settings → Menu Button /${NC}"
            echo -e "  ${YELLOW}   Configure Menu Button, and set it to: ${CYAN}${PROTO}://${WEB_DOMAIN}:${WEB_PORT}${WEB_PATH}/${NC}"
            echo -e "  ${YELLOW}   (BananaBot also sets this automatically on every bot restart.)${NC}"
            echo -e "  ${YELLOW}2. For the browser \"Log in with Telegram\" button to also work,${NC}"
            echo -e "  ${YELLOW}   set the same domain via @BotFather → /setdomain.${NC}"
        else
            echo -e "  ${RED}NOTE: No SSL configured — Telegram requires HTTPS for the in-chat${NC}"
            echo -e "  ${RED}Mini App button, so it will stay hidden until you add SSL (manage.sh → Web Panel).${NC}"
        fi
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
    init_database_schema
    create_systemd_service
    create_webhook_service
    setup_webapp
    start_bot
    print_summary
}

main "$@"
