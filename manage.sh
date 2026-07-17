#!/usr/bin/env bash
# =============================================================================
#  BananaBot — Bot Management Script
#  GitHub: https://github.com/mazyarzohdi/BananaBot
# =============================================================================

set -euo pipefail

# ── Force a UTF-8 locale ──────────────────────────────────────────────────────
# See install.sh for the full explanation: without this, `read` can corrupt
# multi-byte Persian/Arabic text typed at a prompt on systems with no locale
# configured, silently writing broken bytes into .env.
for _candidate_locale in C.UTF-8 en_US.UTF-8; do
    if locale -a 2>/dev/null | grep -qi "^${_candidate_locale//./\\.}$"; then
        export LANG="$_candidate_locale" LC_ALL="$_candidate_locale"
        break
    fi
done
unset _candidate_locale

# ------------------------------------------------------------
INSTALL_DIR="/opt/BananaBot"
WEBAPP_DIR="$INSTALL_DIR/webapp"
SERVICE_NAME="bananabot"
WEBAPP_SERVICE="bananabot-web"
WEBHOOK_SERVICE="bananabot-webhook"
ENV_FILE="$INSTALL_DIR/.env"
WEBAPP_ENV="$WEBAPP_DIR/.env"
DB_PATH="$INSTALL_DIR/data/bot.db"
BACKUP_DIR="$INSTALL_DIR/data/backups"
# lib/webapp_lib.sh (sourced below via load_webapp_lib) requires these two
# to already be set by its caller. install.sh always set them, but manage.sh
# never did — any function here that sources the lib (webapp_deploy,
# webapp_sync_after_code_update, webapp_sync_db_schema, ...) would abort
# immediately with "unbound variable" under `set -u`, since neither name was
# defined anywhere in this file.
WEBAPP_VENV="$WEBAPP_DIR/.venv"
LOG_FILE="/var/log/bananabot-manage.log"

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
        echo -e "  Bot Status:        ${GREEN}● Running${NC}"
    else
        echo -e "  Bot Status:        ${RED}● Stopped${NC}"
    fi
}

webapp_status_line() {
    if systemctl is-active --quiet "$WEBAPP_SERVICE" 2>/dev/null; then
        echo -e "  Web Panel Status:  ${GREEN}● Running${NC}"
    elif [[ -f "$WEBAPP_ENV" ]]; then
        echo -e "  Web Panel Status:  ${RED}● Stopped${NC}"
    else
        echo -e "  Web Panel Status:  ${YELLOW}● Not configured${NC}"
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
    webapp_status_line
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
    echo -e "  ${BOLD}━━━ Database ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "   [18] 💾 Backup Database"
    echo "   [19] ♻️  Restore Database from Backup"
    echo "   [20] 🩺 Check / Repair Database Schema"
    echo ""
    echo -e "  ${BOLD}━━━ Web Panel (Telegram Mini App) ━━━━━━━━━━━━━${NC}"
    echo "   [13] ℹ️  Web Panel Status & Info"
    echo "   [14] ▶  Start Web Panel"
    echo "   [15] ■  Stop Web Panel"
    echo "   [16] ↺  Restart Web Panel"
    echo "   [17] ⚙️  Setup / Reconfigure Web Panel (domain, port, path, SSL)"
    echo ""
    echo -e "  ${BOLD}━━━ Auto-Payment Webhook (Bank SMS) ━━━━━━━━━━━${NC}"
    echo "   [21] ℹ️  Webhook Status & Info"
    echo "   [22] ↺  Restart Webhook Service"
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

    # The web panel (if installed) keeps its own copy of BOT_TOKEN in
    # webapp/.env to verify Telegram Mini App initData (HMAC signed with the
    # bot token). If we don't sync it here too, the panel keeps validating
    # against the OLD token forever and Mini App auto-login breaks silently
    # with no obvious error pointing back to "you changed the token" —
    # it just looks like a generic "connection error" to the end user.
    if [[ -f "$WEBAPP_ENV" ]]; then
        if grep -qE '^BOT_TOKEN=' "$WEBAPP_ENV" 2>/dev/null; then
            sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=${NEW_TOKEN}|" "$WEBAPP_ENV"
        else
            echo "BOT_TOKEN=${NEW_TOKEN}" >> "$WEBAPP_ENV"
        fi
        success "Web panel token synced too."
        if systemctl is-active --quiet "$WEBAPP_SERVICE" 2>/dev/null; then
            log "Restarting web panel so it picks up the new token..."
            systemctl restart "$WEBAPP_SERVICE"
            sleep 1
            if systemctl is-active --quiet "$WEBAPP_SERVICE"; then
                success "Web panel restarted."
            else
                error "Web panel failed to restart. Check: journalctl -u $WEBAPP_SERVICE -n 50"
            fi
        fi
    fi

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
    echo -e "${YELLOW}Example: 123456789 or 123456789,987654321${NC}"
    read -rp "  ADMIN_IDS: " NEW_ADMIN
    # Remove all spaces and strip any brackets the user may have typed
    NEW_ADMIN="${NEW_ADMIN// /}"
    NEW_ADMIN="${NEW_ADMIN#[}"
    NEW_ADMIN="${NEW_ADMIN%]}"
    if [[ ! "$NEW_ADMIN" =~ ^[0-9]+(,[0-9]+)*$ ]]; then
        warn "Invalid format. Only numbers and commas are allowed."
        return
    fi
    # Wrap in brackets automatically
    NEW_ADMIN="[${NEW_ADMIN}]"
    set_env_value "ADMIN_IDS" "$NEW_ADMIN"
    success "Admin ID saved: $NEW_ADMIN"
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
        if ! python3 -c "open('$ENV_FILE', encoding='utf-8').read()" 2>/dev/null; then
            error ".env now contains invalid UTF-8 bytes — the bot will crash on restart. Try entering the card holder name again."
        fi
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
    echo -e "  PANEL_URL:         ${CYAN}$(get_env_value 'PANEL_URL')${NC}"
    echo ""
    if [[ -f "$DB_PATH" ]] && command -v sqlite3 >/dev/null 2>&1; then
        local ap_enabled ap_port
        ap_enabled=$(sqlite3 "$DB_PATH" "SELECT value FROM settings WHERE key='auto_payment_enabled'" 2>/dev/null)
        ap_port=$(sqlite3 "$DB_PATH" "SELECT value FROM settings WHERE key='auto_payment_port'" 2>/dev/null)
        echo -e "  AUTO_PAYMENT:      ${CYAN}$([[ "$ap_enabled" == "1" ]] && echo enabled || echo disabled)${NC}"
        echo -e "  AUTO_PAYMENT_PORT: ${CYAN}${ap_port:-8100}${NC}"
        echo ""
    fi
    read -rp "  Press Enter to return..."
}

# ------------------------------------------------------------
action_webhook_info() {
    echo ""
    if systemctl is-active --quiet "$WEBHOOK_SERVICE" 2>/dev/null; then
        success "Webhook service is running."
    else
        warn "Webhook service is NOT running."
    fi
    if [[ -f "$DB_PATH" ]] && command -v sqlite3 >/dev/null 2>&1; then
        local ap_enabled ap_port ap_secret
        ap_enabled=$(sqlite3 "$DB_PATH" "SELECT value FROM settings WHERE key='auto_payment_enabled'" 2>/dev/null)
        ap_port=$(sqlite3 "$DB_PATH" "SELECT value FROM settings WHERE key='auto_payment_port'" 2>/dev/null)
        ap_secret=$(sqlite3 "$DB_PATH" "SELECT value FROM settings WHERE key='auto_payment_secret'" 2>/dev/null)
        echo -e "  Auto-payment enabled: ${CYAN}$([[ "$ap_enabled" == "1" ]] && echo yes || echo no)${NC}"
        echo -e "  Listening port:       ${CYAN}${ap_port:-8100}${NC}"
        echo -e "  Secret configured:    ${CYAN}$([[ -n "$ap_secret" ]] && echo yes || echo no)${NC}"
    fi
    echo ""
    echo -e "  Both the enable/disable toggle and the port are changed from inside the bot itself:"
    echo -e "  ${CYAN}Admin menu → ⚙️ Bot Settings → 🤖 Auto Payment / 🔑 Webhook Secret / 🔌 Webhook Port${NC}"
    echo -e "  Changing the port automatically restarts this service."
    echo ""
    echo -e "  Recent logs:"
    journalctl -u "$WEBHOOK_SERVICE" -n 15 --no-pager 2>/dev/null
    echo ""
    read -rp "  Press Enter to return..."
}

action_webhook_restart() {
    echo ""
    log "Restarting webhook service..."
    systemctl restart "$WEBHOOK_SERVICE"
    sleep 1
    if systemctl is-active --quiet "$WEBHOOK_SERVICE"; then
        success "Webhook service restarted."
    else
        error "Webhook service failed to restart. Check: journalctl -u $WEBHOOK_SERVICE -n 30"
    fi
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
    log "Checking/repairing database schema..."
    "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/db_schema.py" "$DB_PATH"

    # A code update can bring new webapp dependencies, new Django-level
    # schema (auth/session tables db_schema.py doesn't own), or new static
    # assets. Skipped entirely if the web panel was never set up.
    if [[ -f "$WEBAPP_ENV" ]]; then
        load_webapp_lib
        webapp_sync_after_code_update
        if systemctl is-active --quiet "$WEBAPP_SERVICE" 2>/dev/null; then
            log "Restarting web panel so it picks up the update..."
            systemctl restart "$WEBAPP_SERVICE"
            sleep 1
            if systemctl is-active --quiet "$WEBAPP_SERVICE"; then
                success "Web panel restarted."
            else
                error "Web panel failed to restart after update. Check: journalctl -u $WEBAPP_SERVICE -n 50"
            fi
        fi
    fi

    if [[ ! -f "/etc/systemd/system/${WEBHOOK_SERVICE}.service" ]]; then
        log "Setting up the auto-payment webhook service (new since your last install)..."
        cat > "/etc/systemd/system/${WEBHOOK_SERVICE}.service" << EOF
[Unit]
Description=BananaBot — Auto-Payment Webhook (bank SMS)
After=network.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/.venv/bin/python payment_webhook_server.py
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
        systemctl enable "$WEBHOOK_SERVICE"
        systemctl start "$WEBHOOK_SERVICE"
        success "Auto-payment webhook service created (see menu option 21 for status, and AUTO_PAYMENT_SETUP.md to configure)."
    fi

    success "Update completed."
    echo -n "  Restart the bot? [y/N]: "
    read -r RESTART_CHOICE
    if [[ "$RESTART_CHOICE" =~ ^[yY]$ ]]; then
        action_restart
    fi
    if systemctl list-unit-files "${WEBHOOK_SERVICE}.service" >/dev/null 2>&1; then
        echo -n "  Restart the auto-payment webhook service too? [y/N]: "
        read -r WEBHOOK_RESTART_CHOICE
        if [[ "$WEBHOOK_RESTART_CHOICE" =~ ^[yY]$ ]]; then
            action_webhook_restart
        fi
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
    if [[ "$CONFIRM_TEXT" != "DELETE" ]]; then
        warn "Operation cancelled."
        return
    fi

    log "Stopping services..."
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    systemctl stop "$WEBHOOK_SERVICE" 2>/dev/null || true
    systemctl disable "$WEBHOOK_SERVICE" 2>/dev/null || true
    systemctl stop "$WEBAPP_SERVICE" 2>/dev/null || true
    systemctl disable "$WEBAPP_SERVICE" 2>/dev/null || true

    log "Removing systemd service files..."
    rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    rm -f "/etc/systemd/system/${WEBHOOK_SERVICE}.service"
    rm -f "/etc/systemd/system/${WEBAPP_SERVICE}.service"
    systemctl daemon-reload

    log "Removing project files..."
    rm -rf "$INSTALL_DIR"

    success "BananaBot completely removed."
    echo ""
    exit 0
}

# ------------------------------------------------------------
# Runs a single sqlite3 ".backup" (a proper hot-backup: safe even while the
# bot has the DB open, unlike a plain file copy which could grab it
# mid-write) if the sqlite3 CLI is available, otherwise falls back to cp.
_sqlite_backup_file() {
    local src="$1" dest="$2"
    if command -v sqlite3 >/dev/null 2>&1; then
        sqlite3 "$src" ".backup '$dest'"
    else
        cp "$src" "$dest"
    fi
}

action_backup_db() {
    echo ""
    if [[ ! -f "$DB_PATH" ]]; then
        error "No database found at $DB_PATH yet."
        return
    fi
    mkdir -p "$BACKUP_DIR"
    local ts dest
    ts=$(date +%Y%m%d_%H%M%S)
    dest="$BACKUP_DIR/bot_${ts}.db"

    log "Backing up database..."
    if _sqlite_backup_file "$DB_PATH" "$dest"; then
        success "Backup saved: $dest ($(du -h "$dest" | cut -f1))"
    else
        error "Backup failed."
        return
    fi

    # Keep the last 15 backups only, so this directory doesn't grow forever.
    local count
    count=$(ls -1 "$BACKUP_DIR"/bot_*.db 2>/dev/null | wc -l)
    if [[ "$count" -gt 15 ]]; then
        ls -1t "$BACKUP_DIR"/bot_*.db | tail -n +16 | xargs -r rm -f
        log "Older backups trimmed (keeping the 15 most recent)."
    fi
}

action_restore_db() {
    echo ""
    mkdir -p "$BACKUP_DIR"
    local backups=()
    while IFS= read -r f; do backups+=("$f"); done < <(ls -1t "$BACKUP_DIR"/bot_*.db 2>/dev/null)

    if [[ ${#backups[@]} -eq 0 ]]; then
        warn "No backups found in $BACKUP_DIR yet. Use 'Backup Database' first,"
        warn "or copy an older bot.db file into that folder before restoring."
        return
    fi

    echo -e "  ${BOLD}Available backups:${NC}"
    local i=1
    for f in "${backups[@]}"; do
        echo "   [$i] $(basename "$f")  ($(du -h "$f" | cut -f1))"
        i=$((i+1))
    done
    echo ""
    echo -n "  Select a backup to restore (0 to cancel): "
    read -r SEL
    if [[ ! "$SEL" =~ ^[0-9]+$ ]] || [[ "$SEL" -lt 1 ]] || [[ "$SEL" -gt ${#backups[@]} ]]; then
        warn "Cancelled."
        return
    fi
    local chosen="${backups[$((SEL-1))]}"

    echo ""
    warn "This will REPLACE the current database with: $(basename "$chosen")"
    warn "A safety copy of the CURRENT database is taken first, just in case."
    echo -n "  Type 'RESTORE' to confirm: "
    read -r CONFIRM_TEXT
    if [[ "$CONFIRM_TEXT" != "RESTORE" ]]; then
        warn "Cancelled."
        return
    fi

    local bot_was_running=0 web_was_running=0 webhook_was_running=0
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        bot_was_running=1
        log "Stopping bot..."
        systemctl stop "$SERVICE_NAME"
    fi
    if systemctl is-active --quiet "$WEBAPP_SERVICE" 2>/dev/null; then
        web_was_running=1
        log "Stopping web panel..."
        systemctl stop "$WEBAPP_SERVICE"
    fi
    # payment_webhook_server.py (bananabot-webhook) is a THIRD process that
    # opens its own connections straight to bot.db (see get_conn() there) —
    # independent of the bot and web panel. Leaving it running while we
    # swap the database file out from under it is exactly what causes
    # "database is locked" moments later, when reconcile()/migrate try to
    # grab a brief exclusive lock to fix up the schema.
    if systemctl is-active --quiet "$WEBHOOK_SERVICE" 2>/dev/null; then
        webhook_was_running=1
        log "Stopping auto-payment webhook service..."
        systemctl stop "$WEBHOOK_SERVICE"
    fi

    if [[ -f "$DB_PATH" ]]; then
        mkdir -p "$BACKUP_DIR"
        local safety_ts safety_dest
        safety_ts=$(date +%Y%m%d_%H%M%S)
        safety_dest="$BACKUP_DIR/bot_${safety_ts}_before-restore.db"
        _sqlite_backup_file "$DB_PATH" "$safety_dest" \
            && log "Current database saved to: $safety_dest"
    fi

    log "Restoring $(basename "$chosen")..."
    # reconcile() always turns on WAL mode (see db_schema.py), so the live
    # DB almost always has live.db-wal/-shm sidecar files next to it. If the
    # bot/webapp were killed (systemctl stop -> SIGTERM) without a chance to
    # cleanly checkpoint, those sidecars can be left on disk holding frames
    # that belong to the database we're about to REPLACE. A plain `cp` only
    # overwrites the main file — the stale -wal/-shm are still sitting there
    # afterwards, and SQLite will try to replay them onto the new file on
    # next open. Depending on how the page layouts happen to line up, that
    # either silently resurrects old (pre-restore) data or corrupts the file
    # outright ("database disk image is malformed"). Since we've got a
    # confirmed-good chosen backup file, it's always correct to drop these
    # before copying it in.
    rm -f "${DB_PATH}-wal" "${DB_PATH}-shm"
    cp "$chosen" "$DB_PATH"
    success "Database file restored."

    log "Verifying restored database integrity..."
    integrity_result=$("$INSTALL_DIR/.venv/bin/python" -c "
import sqlite3
con = sqlite3.connect('$DB_PATH')
try:
    print(con.execute('PRAGMA integrity_check').fetchone()[0])
finally:
    con.close()
" 2>&1) || integrity_result="check failed to run: $integrity_result"
    if [[ "$integrity_result" == "ok" ]]; then
        success "Integrity check passed."
    else
        error "Integrity check FAILED: $integrity_result"
        error "The restored file may be corrupt. Your pre-restore database was saved to:"
        error "  ${safety_dest:-$BACKUP_DIR (see above)}"
        error "Consider restoring a different backup, or copying that safety file back manually:"
        error "  cp \"${safety_dest:-<safety file>}\" \"$DB_PATH\""
    fi

    # This is the step that matters most: the backup may be from an older
    # version of the bot, so its schema could be missing tables/columns
    # the CURRENT code expects. Reconcile brings it up to date automatically.
    log "Checking/repairing database schema against the current code..."
    "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/db_schema.py" "$DB_PATH"

    # The restored backup may predate the web panel entirely (or predate a
    # Django app being added), in which case Django's own auth_*/
    # django_session tables — a completely separate schema that
    # db_schema.py knows nothing about — would be missing from it. Those
    # get queried on EVERY web panel request, so without this the panel
    # would 500 immediately on restart. Run this BEFORE starting it back up.
    if [[ -f "$WEBAPP_ENV" ]]; then
        load_webapp_lib
        webapp_sync_db_schema
    fi

    if [[ "$bot_was_running" -eq 1 ]]; then
        log "Starting bot..."
        systemctl start "$SERVICE_NAME"
    fi
    if [[ "$web_was_running" -eq 1 ]]; then
        log "Starting web panel..."
        systemctl start "$WEBAPP_SERVICE"
    fi
    if [[ "$webhook_was_running" -eq 1 ]]; then
        log "Starting auto-payment webhook service..."
        systemctl start "$WEBHOOK_SERVICE"
    fi
    success "Restore complete."
}

action_check_db_schema() {
    echo ""
    if [[ ! -f "$DB_PATH" ]]; then
        error "No database found at $DB_PATH yet."
        return
    fi
    log "Checking database schema against the current code..."
    "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/db_schema.py" "$DB_PATH"
    if [[ -f "$WEBAPP_ENV" ]]; then
        load_webapp_lib
        webapp_sync_db_schema
    fi
    success "Done. Safe to run any time — e.g. right after 'Update Bot from GitHub'."
}

# ------------------------------------------------------------
webapp_lib_loaded="no"
load_webapp_lib() {
    if [[ "$webapp_lib_loaded" != "yes" ]]; then
        # shellcheck source=/dev/null
        source "$INSTALL_DIR/lib/webapp_lib.sh"
        webapp_lib_loaded="yes"
    fi
}

action_webapp_info() {
    echo ""
    echo -e "${BOLD}  ═══ Web Panel ═══${NC}"
    echo ""
    if [[ ! -f "$WEBAPP_ENV" ]]; then
        warn "Web panel is not configured yet. Use option [17] to set it up."
        echo ""
        read -rp "  Press Enter to return..."
        return
    fi

    load_webapp_lib
    local domain port path_ cert
    domain=$(webapp_get_env_value "WEB_DOMAIN")
    port=$(webapp_get_env_value "WEB_PORT")
    path_=$(webapp_get_env_value "WEB_PATH")
    cert=$(webapp_get_env_value "SSL_CERT")
    local proto="http"
    [[ -n "$cert" && -f "$cert" ]] && proto="https"

    echo -e "  Domain:     ${CYAN}${domain}${NC}"
    echo -e "  Port:       ${CYAN}${port}${NC}"
    echo -e "  Path:       ${CYAN}${path_}${NC}"
    echo -e "  URL:        ${CYAN}${proto}://${domain}:${port}${path_}/${NC}"
    echo -e "  SSL:        ${CYAN}$([[ "$proto" == "https" ]] && echo "Enabled" || echo "Disabled")${NC}"
    echo -e "  PANEL_URL in bot .env: ${CYAN}$(get_env_value 'PANEL_URL')${NC}"
    if [[ "$proto" != "https" ]]; then
        warn "Telegram requires HTTPS for the in-chat Mini App button — it's hidden until SSL is set."
    fi
    echo ""
    if systemctl is-active --quiet "$WEBAPP_SERVICE" 2>/dev/null; then
        success "Service status: running"
    else
        error "Service status: stopped"
    fi
    echo ""
    read -rp "  Press Enter to return..."
}

action_webapp_start() {
    if [[ ! -f "$WEBAPP_ENV" ]]; then
        warn "Web panel is not configured yet. Use option [17] to set it up first."
        return
    fi
    log "Starting web panel..."
    systemctl start "$WEBAPP_SERVICE"
    sleep 1
    if systemctl is-active --quiet "$WEBAPP_SERVICE"; then
        success "Web panel started."
    else
        error "Web panel failed to start. Check: journalctl -u $WEBAPP_SERVICE -n 50"
    fi
}

action_webapp_stop() {
    if ! systemctl is-active --quiet "$WEBAPP_SERVICE" 2>/dev/null; then
        warn "Web panel is already stopped."
        return
    fi
    log "Stopping web panel..."
    systemctl stop "$WEBAPP_SERVICE"
    success "Web panel stopped."
}

action_webapp_restart() {
    if [[ ! -f "$WEBAPP_ENV" ]]; then
        warn "Web panel is not configured yet. Use option [17] to set it up first."
        return
    fi
    log "Restarting web panel..."
    systemctl restart "$WEBAPP_SERVICE"
    sleep 1
    if systemctl is-active --quiet "$WEBAPP_SERVICE"; then
        success "Web panel restarted."
    else
        error "Web panel failed to start after restart. Check: journalctl -u $WEBAPP_SERVICE -n 50"
    fi
}

action_webapp_configure() {
    load_webapp_lib
    echo ""
    echo -e "${BOLD}  ═══ Web Panel Setup / Reconfigure ═══${NC}"
    echo ""

    local cur_domain cur_port cur_path cur_cert cur_key
    cur_domain=$(webapp_get_env_value "WEB_DOMAIN")
    cur_port=$(webapp_get_env_value "WEB_PORT"); cur_port="${cur_port:-8080}"
    cur_path=$(webapp_get_env_value "WEB_PATH"); cur_path="${cur_path:-/panel}"
    cur_cert=$(webapp_get_env_value "SSL_CERT")
    cur_key=$(webapp_get_env_value "SSL_KEY")

    echo -e "${CYAN}Domain or IP for the web panel [current: ${cur_domain:-none}]:${NC}"
    read -rp "  DOMAIN: " WEB_DOMAIN
    WEB_DOMAIN="${WEB_DOMAIN// /}"
    WEB_DOMAIN="${WEB_DOMAIN:-$cur_domain}"
    if [[ -z "$WEB_DOMAIN" ]]; then
        warn "A domain/IP is required. Cancelled."
        return
    fi

    echo -e "${CYAN}Port [current: ${cur_port}]:${NC}"
    read -rp "  PORT: " WEB_PORT
    WEB_PORT="${WEB_PORT// /}"
    WEB_PORT="${WEB_PORT:-$cur_port}"

    echo -e "${CYAN}URL path [current: ${cur_path}]:${NC}"
    read -rp "  WEB_PATH: " WEB_PATH
    WEB_PATH="${WEB_PATH// /}"
    WEB_PATH="${WEB_PATH:-$cur_path}"
    [[ "${WEB_PATH:0:1}" != "/" ]] && WEB_PATH="/${WEB_PATH}"

    echo -e "${CYAN}SSL certificate path (Enter to keep current: ${cur_cert:-none}):${NC}"
    read -rp "  SSL_CERT: " SSL_CERT
    SSL_CERT="${SSL_CERT// /}"
    SSL_CERT="${SSL_CERT:-$cur_cert}"

    if [[ -n "$SSL_CERT" ]]; then
        echo -e "${CYAN}SSL private key path (Enter to keep current: ${cur_key:-none}):${NC}"
        read -rp "  SSL_KEY: " SSL_KEY
        SSL_KEY="${SSL_KEY// /}"
        SSL_KEY="${SSL_KEY:-$cur_key}"
    else
        SSL_KEY=""
    fi

    if [[ -n "$SSL_CERT" && ! -f "$SSL_CERT" ]]; then
        warn "Certificate file not found at that path — continuing without SSL for now."
        SSL_CERT=""
        SSL_KEY=""
    fi

    # webapp_deploy (from lib) needs these bot-side values too.
    BOT_TOKEN=$(get_env_value "BOT_TOKEN")
    ADMIN_IDS=$(get_env_value "ADMIN_IDS")

    echo ""
    webapp_deploy
    echo ""
    echo -n "  Restart the bot now so it picks up the new panel URL? [y/N]: "
    read -r RESTART_CHOICE
    if [[ "$RESTART_CHOICE" =~ ^[yY]$ ]]; then
        action_restart
    fi
    echo ""
    read -rp "  Press Enter to return..."
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
            18) action_backup_db ;;
            19) action_restore_db ;;
            20) action_check_db_schema ;;
            13) action_webapp_info ;;
            14) action_webapp_start ;;
            15) action_webapp_stop ;;
            16) action_webapp_restart ;;
            17) action_webapp_configure ;;
            21) action_webhook_info ;;
            22) action_webhook_restart ;;
            0)  echo "Goodbye! 👋"; exit 0 ;;
            *)  warn "Invalid selection." ;;
        esac

        if [[ "$CHOICE" != "4" && "$CHOICE" != "5" && "$CHOICE" != "10" && "$CHOICE" != "13" && "$CHOICE" != "17" && "$CHOICE" != "21" ]]; then
            echo ""
            read -rp "  Press Enter to return to menu..."
        fi
    done
}

run "$@"
