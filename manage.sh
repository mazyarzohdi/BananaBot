#!/usr/bin/env bash
# =============================================================================
#  BananaBot — Bot Management Script
#  GitHub: https://github.com/mazyarzohdi/BananaBot
# =============================================================================

set -euo pipefail

# ------------------------------------------------------------
INSTALL_DIR="/opt/BananaBot"
SERVICE_NAME="bananabot"
ENV_FILE="$INSTALL_DIR/.env"

# ------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

# ------------------------------------------------------------
log()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success(){ echo -e "${GREEN}[OK]${NC}    $*"; }
warn()   { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()  { echo -e "${RED}[ERROR]${NC} $*"; }

check_root() {
    if [[ $EUID -ne 0 ]]; then
        error "This script must be run as root."
        echo "    sudo bash manage.sh"
        exit 1
    fi
}

check_installed() {
    if [[ ! -d "$INSTALL_DIR" ]]; then
        error "BananaBot is not installed. Run install.sh first."
        exit 1
    fi
}

get_env_value() {
    local key="$1"
    grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- || echo ""
}

set_env_value() {
    local key="$1"
    local value="$2"
    if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    else
        echo "${key}=${value}" >> "$ENV_FILE"
    fi
}

bot_status() {
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        echo -e "  Status: ${GREEN}● Running${NC}"
    else
        echo -e "  Status: ${RED}● Stopped${NC}"
    fi
}

print_header() {
    clear
    echo -e "${BOLD}${BLUE}"
    echo "  ╔══════════════════════════════════════════╗"
    echo "  ║       BananaBot — Bot Management Panel       ║"
    echo "  ╚══════════════════════════════════════════╝"
    echo -e "${NC}"
    bot_status
    echo ""
}

# ------------------------------------------------------------
main_menu() {
    print_header
    echo -e "  ${BOLD}━━━ Bot Control ━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "   [1] ▶  Start Bot"
    echo "   [2] ■  Stop Bot"
    echo "   [3] ↺  Restart Bot"
    echo "   [4] 📜 View Live Logs"
    echo "   [5] 📋 View Last 50 Log Lines"
    echo ""
    echo -e "  ${BOLD}━━━ Settings ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "   [6] 🔑 Change Bot Token"
    echo "   [7] 👤 Change Admin ID"
    echo "   [8] 💳 Change Card Number"
    echo "   [9] 📢 Change Required Channel"
    echo "   [10] ⚙️  View Current Settings"
    echo ""
    echo -e "  ${BOLD}━━━ Advanced Operations ━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "   [11] 🔄 Update Bot from GitHub"
    echo "   [12] 🗑️  Completely Remove Bot"
    echo ""
    echo "   [0] 🚪 Exit"
    echo ""
    echo -e "  ${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -n "  Choose an option: "
}

# ------------------------------------------------------------
action_start() {
    log "Starting bot..."
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        warn "Bot is already running."
    else
        systemctl start "$SERVICE_NAME"
        sleep 1
        if systemctl is-active --quiet "$SERVICE_NAME"; then
            success "Bot started successfully. ✅"
        else
            error "Bot failed to start! Check the logs."
        fi
    fi
}

# ------------------------------------------------------------
action_stop() {
    log "Stopping bot..."
    if ! systemctl is-active --quiet "$SERVICE_NAME"; then
        warn "Bot is already stopped."
    else
        systemctl stop "$SERVICE_NAME"
        success "Bot stopped. ■"
    fi
}

# ------------------------------------------------------------
action_restart() {
    log "Restart Bot..."
    systemctl restart "$SERVICE_NAME"
    sleep 1
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        success "Bot restarted. ↺"
    else
        error "Bot failed to start after restart!"
    fi
}

# ------------------------------------------------------------
action_live_log() {
    echo -e "${YELLOW}Press Ctrl+C to exit the logs.${NC}"
    echo ""
    journalctl -u "$SERVICE_NAME" -f --no-pager
}

# ------------------------------------------------------------
action_last_logs() {
    echo ""
    journalctl -u "$SERVICE_NAME" -n 50 --no-pager
    echo ""
    read -rp "Press Enter to return..."
}

# ------------------------------------------------------------
action_change_token() {
    echo ""
    echo -e "${CYAN}Current token:${NC} $(get_env_value 'BOT_TOKEN')"
    echo ""
    echo -e "${CYAN}Enter new token (from @BotFather):${NC}"
    read -rp "  BOT_TOKEN: " NEW_TOKEN
    NEW_TOKEN="${NEW_TOKEN// /}"
    if [[ -z "$NEW_TOKEN" || "$NEW_TOKEN" == "your_bot_token_here" ]]; then
        warn "Invalid token. No changes made."
        return
    fi
    set_env_value "BOT_TOKEN" "$NEW_TOKEN"
    success "Token saved."
    echo -n "  Restart the bot? [y/N]: "
    read -r RESTART_CHOICE
    if [[ "$RESTART_CHOICE" =~ ^[yY]$ ]]; then
        action_restart
    fi
}

# ------------------------------------------------------------
action_change_admin() {
    echo ""
    echo -e "${CYAN}Current admin IDs:${NC} $(get_env_value 'ADMIN_IDS')"
    echo ""
    echo -e "${CYAN}Enter new admin ID(s) (comma-separated):${NC}"
    echo -e "${YELLOW}Example: 123456789 یا 123456789,987654321${NC}"
    read -rp "  ADMIN_IDS: " NEW_ADMIN
    NEW_ADMIN="${NEW_ADMIN// /}"
    if [[ ! "$NEW_ADMIN" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
        warn "Invalid format. Only numbers and commas are allowed."
        return
    fi
    set_env_value "ADMIN_IDS" "$NEW_ADMIN"
    success "Admin ID saved."
    echo -n "  Restart the bot? [y/N]: "
    read -r RESTART_CHOICE
    if [[ "$RESTART_CHOICE" =~ ^[yY]$ ]]; then
        action_restart
    fi
}

# ------------------------------------------------------------
action_change_card() {
    echo ""
    echo -e "${CYAN}Current card number:${NC} $(get_env_value 'CARD_NUMBER')"
    echo -e "${CYAN}Current card holder:${NC} $(get_env_value 'CARD_HOLDER')"
    echo ""
    echo -e "${CYAN}New card number (Enter to skip):${NC}"
    read -rp "  CARD_NUMBER: " NEW_CARD
    NEW_CARD="${NEW_CARD// /}"
    if [[ -n "$NEW_CARD" ]]; then
        set_env_value "CARD_NUMBER" "$NEW_CARD"
        echo -e "${CYAN}New card holder:${NC}"
        read -rp "  CARD_HOLDER: " NEW_HOLDER
        set_env_value "CARD_HOLDER" "$NEW_HOLDER"
        success "Card information saved."
        echo -n "  Restart the bot? [y/N]: "
        read -r RESTART_CHOICE
        if [[ "$RESTART_CHOICE" =~ ^[yY]$ ]]; then
            action_restart
        fi
    else
        warn "No changes made."
    fi
}

# ------------------------------------------------------------
action_change_channel() {
    echo ""
    echo -e "${CYAN}Current required channel:${NC} $(get_env_value 'REQUIRED_CHANNEL')"
    echo ""
    echo -e "${CYAN}New channel address (Example: @mychannel — leave blank to remove):${NC}"
    read -rp "  REQUIRED_CHANNEL: " NEW_CHANNEL
    NEW_CHANNEL="${NEW_CHANNEL// /}"
    set_env_value "REQUIRED_CHANNEL" "$NEW_CHANNEL"
    if [[ -z "$NEW_CHANNEL" ]]; then
        success "Required channel removed."
    else
        success "Required channel changed to «$NEW_CHANNEL» updated."
    fi
    echo -n "  Restart the bot? [y/N]: "
    read -r RESTART_CHOICE
    if [[ "$RESTART_CHOICE" =~ ^[yY]$ ]]; then
        action_restart
    fi
}

# ------------------------------------------------------------
action_show_config() {
    echo ""
    echo -e "${BOLD}  ═══ Settings Current ═══${NC}"
    echo ""
    # نمایش توکن با مخفی‌سازی وسط
    TOKEN=$(get_env_value 'BOT_TOKEN')
    if [[ ${#TOKEN} -gt 10 ]]; then
        MASKED_TOKEN="${TOKEN:0:6}****${TOKEN: -4}"
    else
        MASKED_TOKEN="$TOKEN"
    fi
    echo -e "  BOT_TOKEN:         ${CYAN}$MASKED_TOKEN${NC}"
    echo -e "  ADMIN_IDS:         ${CYAN}$(get_env_value 'ADMIN_IDS')${NC}"
    echo -e "  DATABASE_PATH:     ${CYAN}$(get_env_value 'DATABASE_PATH')${NC}"
    echo -e "  DEFAULT_LANG:      ${CYAN}$(get_env_value 'DEFAULT_LANG')${NC}"
    echo -e "  CARD_NUMBER:       ${CYAN}$(get_env_value 'CARD_NUMBER')${NC}"
    echo -e "  CARD_HOLDER:       ${CYAN}$(get_env_value 'CARD_HOLDER')${NC}"
    echo -e "  REQUIRED_CHANNEL:  ${CYAN}$(get_env_value 'REQUIRED_CHANNEL')${NC}"
    echo ""
    read -rp "  Press Enter to return..."
}

# ------------------------------------------------------------
action_update() {
    echo ""
    warn "Updating will not modify the .env file."
    echo -n "  Are you sure? [y/N]: "
    read -r CONFIRM
    if [[ ! "$CONFIRM" =~ ^[yY]$ ]]; then
        return
    fi
    log "Fetching latest version from GitHub..."
    # پشتیبان از .env
    cp "$ENV_FILE" "/tmp/.env.bananabot.bak"
    git -C "$INSTALL_DIR" fetch origin >> /dev/null 2>&1
    git -C "$INSTALL_DIR" reset --hard origin/main >> /dev/null 2>&1
    # بازگرداندن .env
    cp "/tmp/.env.bananabot.bak" "$ENV_FILE"
    # به‌روزرسانی کتابخانه‌ها
    log "Updating Python libraries..."
    "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" --quiet
    success "Update completed."
    echo -n "  Restart the bot? [y/N]: "
    read -r RESTART_CHOICE
    if [[ "$RESTART_CHOICE" =~ ^[yY]$ ]]; then
        action_restart
    fi
}

# ------------------------------------------------------------
action_uninstall() {
    echo ""
    echo -e "${RED}${BOLD}  ⚠️  Warning: This action cannot be undone!${NC}"
    echo -e "${RED}  ربات، configuration files and database will be removed.${NC}"
    echo ""
    echo -n "  Type 'DELETE' to confirm: "
    read -r CONFIRM_TEXT
    if [[ "$CONFIRM_TEXT" != "حذف" ]]; then
        warn "Operation cancelled."
        return
    fi

    log "Stopping service..."
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true

    log "Removing systemd service file..."
    rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    systemctl daemon-reload

    log "Removing project files..."
    rm -rf "$INSTALL_DIR"

    success "BananaBot completely removed."
    echo ""
    exit 0
}

# ------------------------------------------------------------
run() {
    check_root
    check_installed

    while true; do
        main_menu
        read -r CHOICE
        echo ""

        case "$CHOICE" in
            1)  action_start ;;
            2)  action_stop ;;
            3)  action_restart ;;
            4)  action_live_log ;;
            5)  action_last_logs ;;
            6)  action_change_token ;;
            7)  action_change_admin ;;
            8)  action_change_card ;;
            9)  action_change_channel ;;
            10) action_show_config ;;
            11) action_update ;;
            12) action_uninstall ;;
            0)  echo "Goodbye! 👋"; exit 0 ;;
            *)  warn "Invalid selection." ;;
        esac

        if [[ "$CHOICE" != "4" && "$CHOICE" != "5" && "$CHOICE" != "10" ]]; then
            echo ""
            read -rp "  Press Enter to return to menu..."
        fi
    done
}

run "$@"
