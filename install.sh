#!/usr/bin/env bash
# =============================================================================
#  BananaBot — Automatic Installation and Configuration Script
#  GitHub: https://github.com/mazyarzohdi/BananaBot
# =============================================================================

set -euo pipefail

# ------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ------------------------------------------------------------
REPO_URL="https://github.com/mazyarzohdi/BananaBot"
INSTALL_DIR="/opt/BananaBot"
SERVICE_NAME="bananabot"
PYTHON_MIN="3.11"
VENV_DIR="$INSTALL_DIR/.venv"
LOG_FILE="/var/log/bananabot-install.log"

# ------------------------------------------------------------
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

  Automatic Installation and Configuration — github.com/mazyarzohdi/BananaBot
EOF
echo ""
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        error "This script must be run as root.\nPlease run it again with sudo: sudo bash install.sh"
    fi
}

check_os() {
    log "Checking operating system..."
    if ! command -v apt-get &>/dev/null && ! command -v yum &>/dev/null; then
        error "Only Debian/Ubuntu and CentOS/RHEL are supported."
    fi
    success "Operating system detected."
}

install_system_deps() {
    log "Installing system dependencies..."
    if command -v apt-get &>/dev/null; then
        apt-get update -qq
        apt-get install -y -qq python3 python3-pip python3-venv git curl unzip >> "$LOG_FILE" 2>&1
    elif command -v yum &>/dev/null; then
        yum install -y python3 python3-pip git curl unzip >> "$LOG_FILE" 2>&1
    fi
    success "System dependencies installed."
}

check_python() {
    log "Checking Python version..."
    if ! command -v python3 &>/dev/null; then
        error "Python3 not found! Please install it."
    fi
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    PY_OK=$(python3 -c "import sys; print(1 if sys.version_info >= (3,11) else 0)")
    if [[ "$PY_OK" != "1" ]]; then
        error "Python $PYTHON_MIN+ is required. Current version: $PY_VER"
    fi
    success "Python $PY_VER detected."
}

clone_or_update_repo() {
    log "Fetching project source code..."
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        warn "Directory $INSTALL_DIR already exists. Updating..."
        git -C "$INSTALL_DIR" pull --ff-only >> "$LOG_FILE" 2>&1 || warn "Updating git failed — existing files will be used."
    else
        git clone "$REPO_URL" "$INSTALL_DIR" >> "$LOG_FILE" 2>&1
    fi
    success "Project code installed in $INSTALL_DIR created."
}

create_virtualenv() {
    log "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR" >> "$LOG_FILE" 2>&1
    "$VENV_DIR/bin/pip" install --upgrade pip --quiet >> "$LOG_FILE" 2>&1
    success "Virtual environment created."
}

install_python_deps() {
    log "Installing Python libraries (this may take a few minutes)..."
    "$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --quiet >> "$LOG_FILE" 2>&1
    success "Libraries installed."
}

# ------------------------------------------------------------
collect_config() {
    echo ""
    echo -e "${BOLD}════════════════════════════════════════════${NC}"
    echo -e "${BOLD}   Bot Configuration — Please enter the required information${NC}"
    echo -e "${BOLD}════════════════════════════════════════════${NC}"
    echo ""

    # توکن ربات
    while true; do
        echo -e "${CYAN}1) Telegram bot token (from @BotFather):${NC}"
        read -rp "   BOT_TOKEN: " BOT_TOKEN
        BOT_TOKEN="${BOT_TOKEN// /}"
        if [[ -n "$BOT_TOKEN" && "$BOT_TOKEN" != "your_bot_token_here" ]]; then
            break
        fi
        warn "Invalid token. Please try again."
    done

    # Admin numeric ID
    echo ""
    echo -e "${CYAN}2) Admin numeric ID (one or more IDs, comma-separated):${NC}"
    echo -e "   ${YELLOW}Example: 123456789 or 123456789,987654321${NC}"
    while true; do
        read -rp "   ADMIN_IDS: " ADMIN_IDS
        ADMIN_IDS="${ADMIN_IDS// /}"
        if [[ "$ADMIN_IDS" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
            break
        fi
        warn "Invalid ID format. Only numbers and commas are allowed."
    done

    # شماره کارت (اختorری)
    echo ""
    echo -e "${CYAN}3) Card number for payments (optional — press Enter to skip):${NC}"
    echo -e "   ${YELLOW}Example: 6037-1234-5678-9012${NC}"
    read -rp "   CARD_NUMBER: " CARD_NUMBER
    CARD_NUMBER="${CARD_NUMBER// /}"

    # Card holder name
    if [[ -n "$CARD_NUMBER" ]]; then
        echo ""
        echo -e "${CYAN}4) Card holder name:${NC}"
        read -rp "   CARD_HOLDER: " CARD_HOLDER
    else
        CARD_HOLDER=""
    fi

    # کانال اجباری (اختorری)
    echo ""
    echo -e "${CYAN}5) Required channel for purchasing services (optional — press Enter to skip):${NC}"
    echo -e "   ${YELLOW}Example: @mychannel${NC}"
    read -rp "   REQUIRED_CHANNEL: " REQUIRED_CHANNEL
    REQUIRED_CHANNEL="${REQUIRED_CHANNEL// /}"

    # زبان Default
    echo ""
    echo -e "${CYAN}6) Default bot language:${NC}"
    echo "   [1] Persian (fa) — Default"
    echo "   [2] English (en)"
    read -rp "   Select [1/2]: " LANG_CHOICE
    case "$LANG_CHOICE" in
        2) DEFAULT_LANG="en" ;;
        *) DEFAULT_LANG="fa" ;;
    esac

    echo ""
    success "Configuration information collected."
}

write_env_file() {
    log "Creating .env file..."
    cat > "$INSTALL_DIR/.env" <<EOF
# Generated by install.sh — $(date)
BOT_TOKEN=${BOT_TOKEN}
ADMIN_IDS=${ADMIN_IDS}
DATABASE_PATH=data/bot.db
DEFAULT_LANG=${DEFAULT_LANG}
CARD_NUMBER=${CARD_NUMBER}
CARD_HOLDER=${CARD_HOLDER}
REQUIRED_CHANNEL=${REQUIRED_CHANNEL}
EOF
    chmod 600 "$INSTALL_DIR/.env"
    success ".env file created."
}

create_data_dir() {
    mkdir -p "$INSTALL_DIR/data"
    chown -R root:root "$INSTALL_DIR"
    success "data/ directory is ready."
}

create_systemd_service() {
    log "Creating systemd service..."
    cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
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
    success "systemd service created and enabled."
}

start_bot() {
    log "Starting bot..."
    systemctl start "$SERVICE_NAME"
    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        success "Bot started successfully! ✅"
    else
        warn "Bot failed to start. Check the logs:"
        echo "    journalctl -u $SERVICE_NAME -n 30 --no-pager"
    fi
}

print_summary() {
    echo ""
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${GREEN}   Installation completed successfully! 🎉${NC}"
    echo -e "${BOLD}${GREEN}════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  📁 Installation path:      ${CYAN}$INSTALL_DIR${NC}"
    echo -e "  ⚙️  Configuration file:  ${CYAN}$INSTALL_DIR/.env${NC}"
    echo -e "  📋 Installation log:        ${CYAN}$LOG_FILE${NC}"
    echo ""
    echo -e "  ${BOLD}Bot management:${NC}"
    echo -e "  🔧 Management script:  ${CYAN}sudo bash $INSTALL_DIR/manage.sh${NC}"
    echo ""
    echo -e "  ${BOLD}Quick commands:${NC}"
    echo -e "  ▶  Start:   ${CYAN}systemctl start $SERVICE_NAME${NC}"
    echo -e "  ■  Stop:   ${CYAN}systemctl stop $SERVICE_NAME${NC}"
    echo -e "  ↺  Restart: ${CYAN}systemctl restart $SERVICE_NAME${NC}"
    echo -e "  📜 Logs:    ${CYAN}journalctl -u $SERVICE_NAME -f${NC}"
    echo ""
}

# ------------------------------------------------------------
main() {
    print_banner
    touch "$LOG_FILE"
    log "Installation started — $(date)"

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
    start_bot
    print_summary
}

main "$@"
