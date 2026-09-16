"""Game Service & Season Manager for Mors VPN Clicker Game.

Coordinates user game profiles, upgrades catalog, offline passive mining,
energy regeneration, anti-cheat validation, and Friday night season settlements.
"""

import math
import random
import string
import time
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from django.conf import settings
from . import db as bot_db
from . import telegram_api

logger = logging.getLogger(__name__)
TEHRAN_TZ = ZoneInfo("Asia/Tehran")

UPGRADES_CATALOG = {
    "multi_tap": {
        "id": "multi_tap",
        "title": "افزایش قدرت کلیک",
        "englishTitle": "Multi-Tap",
        "category": "tap",
        "icon": "⚡",
        "description": "با هر بار کلیک، امتیاز بیشتری دریافت کنید (+1)",
        "baseCost": 60,
        "costMultiplier": 1.8,
        "maxLevel": 30,
        "effectType": "tap_power",
        "effectValue": 1,
    },
    "max_energy": {
        "id": "max_energy",
        "title": "افزایش مخزن انرژی",
        "englishTitle": "Energy Boost",
        "category": "tap",
        "icon": "🔋",
        "description": "افزایش ظرفیت انرژی (+500) و سرعت پر شدن (+2 در ثانیه)",
        "baseCost": 100,
        "costMultiplier": 1.75,
        "maxLevel": 30,
        "effectType": "energy_capacity",
        "energyValue": 500,
        "recoveryValue": 2,
    },
    "server_finland": {
        "id": "server_finland",
        "title": "سرور فنلاند",
        "englishTitle": "Finland Server",
        "category": "server",
        "icon": "🇫🇮",
        "description": "دریافت خودکار +3 امتیاز در هر ثانیه",
        "baseCost": 250,
        "costMultiplier": 1.5,
        "maxLevel": 50,
        "effectType": "passive_rate",
        "passiveRate": 3,
    },
    "server_germany": {
        "id": "server_germany",
        "title": "سرور آلمان",
        "englishTitle": "Germany Server",
        "category": "server",
        "icon": "🇩🇪",
        "description": "دریافت خودکار +12 امتیاز در هر ثانیه",
        "baseCost": 1200,
        "costMultiplier": 1.55,
        "maxLevel": 50,
        "effectType": "passive_rate",
        "passiveRate": 12,
    },
    "server_netherlands": {
        "id": "server_netherlands",
        "title": "سرور هلند",
        "englishTitle": "Netherlands Server",
        "category": "server",
        "icon": "🇳🇱",
        "description": "دریافت خودکار +45 امتیاز در هر ثانیه",
        "baseCost": 6000,
        "costMultiplier": 1.6,
        "maxLevel": 50,
        "effectType": "passive_rate",
        "passiveRate": 45,
    },
    "server_switzerland": {
        "id": "server_switzerland",
        "title": "سرور سوئیس",
        "englishTitle": "Switzerland Server",
        "category": "server",
        "icon": "🇨🇭",
        "description": "دریافت خودکار +160 امتیاز در هر ثانیه",
        "baseCost": 28000,
        "costMultiplier": 1.65,
        "maxLevel": 50,
        "effectType": "passive_rate",
        "passiveRate": 160,
    },
    "server_usa": {
        "id": "server_usa",
        "title": "سرور آمریکا (VIP)",
        "englishTitle": "USA VIP Server",
        "category": "server",
        "icon": "🇺🇸",
        "description": "دریافت خودکار +650 امتیاز در هر ثانیه",
        "baseCost": 120000,
        "costMultiplier": 1.7,
        "maxLevel": 50,
        "effectType": "passive_rate",
        "passiveRate": 650,
    },
}


def calculate_cost(upgrade_id: str, current_level: int) -> int:
    item = UPGRADES_CATALOG.get(upgrade_id)
    if not item or current_level >= item["maxLevel"]:
        return 999999999
    return int(round(item["baseCost"] * (item["costMultiplier"] ** current_level)))


def get_next_friday_night(from_timestamp_ms: int | None = None) -> int:
    """Calculates Friday night at 23:59:59 (Asia/Tehran timezone) in milliseconds."""
    if from_timestamp_ms is None:
        from_timestamp_ms = int(time.time() * 1000)

    now_dt = datetime.fromtimestamp(from_timestamp_ms / 1000.0, tz=TEHRAN_TZ)
    # Python weekday: Monday is 0, Friday is 4
    days_until_friday = (4 - now_dt.weekday() + 7) % 7
    target = now_dt + timedelta(days=days_until_friday)
    target = target.replace(hour=23, minute=59, second=59, microsecond=999000)

    # If it's already Friday and past 23:59:59, jump to next Friday
    if target.timestamp() * 1000 <= from_timestamp_ms:
        target += timedelta(days=7)

    return int(target.timestamp() * 1000)


def notify_admins_season_winners(season_number: int, winners: list[dict], next_season_start_ms: int):
    """Notifies all Telegram admins of the weekly season conclusion and top 3 winners."""
    admin_ids = list(getattr(settings, "ADMIN_TELEGRAM_IDS", []))
    if not admin_ids:
        raw_admin = os.environ.get("ADMIN_IDS", "[]")
        try:
            admin_ids = [int(x.strip()) for x in raw_admin.strip("[]").split(",") if x.strip().isdigit()]
        except Exception:
            admin_ids = []

    if not admin_ids:
        logger.warning("No ADMIN_TELEGRAM_IDS found to notify season winners.")
        return

    # Convert next start time to Tehran human-readable format
    next_start_dt = datetime.fromtimestamp(next_season_start_ms / 1000.0, tz=TEHRAN_TZ)
    next_start_str = next_start_dt.strftime("%Y-%m-%d ساعت %H:%M:%S")

    rank_emojis = {1: "🥇", 2: "🥈", 3: "🥉"}
    rank_titles = {1: "رتبه اول (طلا)", 2: "رتبه دوم (نقره)", 3: "رتبه سوم (برنز)"}

    winners_lines = []
    if not winners:
        winners_lines.append("<i>هیچ بازیکنی در این فصل امتیازی کسب نکرده است.</i>\n")
    else:
        for w in winners:
            r = w.get("rank", 1)
            emoji = rank_emojis.get(r, "🎖")
            title = rank_titles.get(r, f"رتبه {r}")
            name = w.get("nickname") or f"کاربر {w.get('telegram_id')}"
            uname = f"@{w['username']}" if w.get("username") else "ندارد"
            score = int(w.get("score", 0))
            prize = w.get("prize_title", "اشتراک")
            code = w.get("prize_code", "-")

            block = (
                f"{emoji} <b>{title}:</b>\n"
                f"👤 نام: <b>{name}</b>\n"
                f"🆔 چت آیدی: <code>{w.get('telegram_id')}</code>\n"
                f"🌐 نام کاربری: {uname}\n"
                f"⭐️ امتیاز نهایی: <b>{score:,}</b>\n"
                f"🎁 جایزه: <b>{prize}</b>\n"
                f"🎫 کد تحویل جایزه: <code>{code}</code>\n"
            )
            winners_lines.append(block)

    winners_text = "\n".join(winners_lines)

    msg = (
        f"🏆 <b>پایان مسابقه هفتگی — فصل {season_number} بازی کلیکر مورس</b>\n\n"
        f"لیست ۳ نفر برتر مسابقه و مشخصات اهدای جوایز به شرح زیر است:\n\n"
        f"{winners_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ <b>آغاز مسابقه فصل جدید ({season_number + 1}):</b>\n"
        f"مسابقه بعدی دقیقاً <b>۲۴ ساعت بعد</b> ({next_start_str}) آغاز خواهد شد.\n"
        f"در طول این ۲۴ ساعت، ویترین برندگان این دوره در صفحه بازی به نمایش درآمده است."
    )

    for admin_id in admin_ids:
        try:
            telegram_api.send_message(admin_id, msg, parse_mode="HTML")
            logger.info("Sent season %s winners alert to admin %s", season_number, admin_id)
        except Exception as e:
            logger.error("Failed to send season winners alert to admin %s: %s", admin_id, e)


def check_and_settle_season() -> dict:
    """Checks if the current active weekly season has expired. If so, settles
    winners for Friday night, records prizes, notifies admins via Telegram,
    resets scores, and starts the 24-hour intermission before the next season.
    """
    now_ms = int(time.time() * 1000)
    current_season = bot_db.get_active_season()

    if not current_season:
        end_time = get_next_friday_night(now_ms)
        return bot_db.create_game_season(1, now_ms, end_time)

    # Check if Friday night has passed
    if now_ms >= current_season["end_time"]:
        season_num = current_season["season_number"]

        # 1. Fetch top 3 players by weekly score
        top_players = bot_db.get_top_season_players(3)

        prize_rank1 = bot_db.get_setting("game_prize_rank1", "کانفیگ اختصاصی ۳ ماهه نامحدود VIP")
        prize_rank2 = bot_db.get_setting("game_prize_rank2", "کانفیگ اختصاصی ۲ ماهه Pro")
        prize_rank3 = bot_db.get_setting("game_prize_rank3", "کانفیگ اختصاصی ۱ ماهه Basic")

        prize_configs = [
            {"rank": 1, "title": prize_rank1, "prefix": "MORS-GOLD"},
            {"rank": 2, "title": prize_rank2, "prefix": "MORS-SILVER"},
            {"rank": 3, "title": prize_rank3, "prefix": "MORS-BRONZE"},
        ]

        recorded_winners = []
        for i, player in enumerate(top_players):
            cfg = prize_configs[i]
            rand_code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
            voucher = f"{cfg['prefix']}-{rand_code}"
            bot_db.record_game_winner(
                season_number=season_num,
                telegram_id=player["telegram_id"],
                nickname=player.get("nickname") or f"Player_{player['telegram_id']}",
                rank=cfg["rank"],
                score=player["total_score"],
                prize_title=cfg["title"],
                prize_code=voucher,
            )
            recorded_winners.append({
                "telegram_id": player["telegram_id"],
                "username": player.get("username"),
                "nickname": player.get("nickname") or f"Player_{player['telegram_id']}",
                "rank": cfg["rank"],
                "score": player["total_score"],
                "prize_title": cfg["title"],
                "prize_code": voucher,
            })

        # 2. Close current season
        bot_db.close_game_season(current_season["id"])

        # 3. Reset all players' total_score for the new week (keeps balance & upgrades intact)
        bot_db.reset_season_scores()

        # 4. Next season start is exactly 24 hours after Friday night (Saturday night 23:59:59)
        friday_end_ms = current_season["end_time"]
        intermission_duration_ms = 24 * 60 * 60 * 1000  # 24 hours
        next_season_start = friday_end_ms + intermission_duration_ms
        next_season_end = get_next_friday_night(next_season_start + 1000)

        # 5. Notify all Telegram admins with top 3 winner details
        try:
            notify_admins_season_winners(season_num, recorded_winners, next_season_start)
        except Exception as exc:
            logger.error("Error sending admin notifications: %s", exc)

        # 6. Create next season record
        new_season = bot_db.create_game_season(season_num + 1, next_season_start, next_season_end)
        _season_cache["season"] = None
        _lb_cache["data"] = None
        return new_season

    return current_season


_season_cache = {"season": None, "expires_at": 0.0}
_prizes_cache = {"prizes": None, "expires_at": 0.0}
_lb_cache = {"data": None, "expires_at": 0.0}


def get_current_season() -> dict:
    now_ts = time.time()
    now_ms = int(now_ts * 1000)

    season = _season_cache.get("season")
    if not season or now_ts >= _season_cache.get("expires_at", 0) or now_ms >= season.get("end_time", 0):
        season = check_and_settle_season()
        _season_cache["season"] = season
        _season_cache["expires_at"] = now_ts + 10.0

    is_intermission = (now_ms < season["start_time"])
    if is_intermission:
        # During 24h intermission: countdown is to Saturday night 23:59:59
        time_left_ms = max(0, season["start_time"] - now_ms)
        prev_num = season["season_number"] - 1
        intermission_winners = bot_db.get_season_winners(prev_num)
    else:
        # Active competition: countdown is to Friday night 23:59:59
        time_left_ms = max(0, season["end_time"] - now_ms)
        intermission_winners = []

    return {
        "id": season["id"],
        "season_number": season["season_number"],
        "start_time": season["start_time"],
        "end_time": season["end_time"],
        "time_left_ms": time_left_ms,
        "is_intermission": is_intermission,
        "intermission_winners": intermission_winners,
        "previous_season_number": season["season_number"] - 1 if is_intermission else None,
    }


def calculate_catchup(user: dict, now_ms: int | None = None, is_intermission: bool = False) -> dict:
    if now_ms is None:
        now_ms = int(time.time() * 1000)

    last_active = user.get("last_active_time") or now_ms
    elapsed_sec = max(0.0, min(28800.0, (now_ms - last_active) / 1000.0))  # Cap at 8 hours

    # Passive energy recovery
    regen_energy = int(elapsed_sec * user.get("energy_recovery_rate", 4))
    new_energy = min(user.get("max_energy", 1000), user.get("energy", 1000) + regen_energy)

    # Passive server income
    passive_mined = int(elapsed_sec * user.get("passive_rate", 0))
    new_balance = user.get("balance", 0) + passive_mined
    if is_intermission:
        new_total_score = 0
    else:
        new_total_score = user.get("total_score", 0) + passive_mined

    return {
        "elapsed_sec": elapsed_sec,
        "new_energy": new_energy,
        "passive_mined": passive_mined,
        "new_balance": new_balance,
        "new_total_score": new_total_score,
    }


def get_user_game_state(telegram_id: int, tg_user: dict | None = None) -> dict:
    season = get_current_season()
    is_intermission = season.get("is_intermission", False)
    now_ms = int(time.time() * 1000)

    user_row = bot_db.get_user_by_telegram_id(telegram_id)
    user_id = user_row["id"] if user_row else None

    # Determine canonical Telegram display name (Full name only, never username)
    tg_name = None
    if tg_user:
        first = (tg_user.get("first_name") or "").strip()
        last = (tg_user.get("last_name") or "").strip()
        full = f"{first} {last}".strip()
        if full:
            tg_name = full
    if not tg_name and user_row:
        if user_row.get("full_name") and user_row["full_name"].strip():
            tg_name = user_row["full_name"].strip()
    if not tg_name:
        tg_name = f"کاربر {telegram_id}"

    profile = bot_db.create_or_get_game_profile(telegram_id, user_id=user_id, nickname=tg_name)
    if profile.get("nickname") != tg_name:
        bot_db.update_game_profile(telegram_id, nickname=tg_name)
        profile["nickname"] = tg_name

    # Calculate catch-up
    catchup = calculate_catchup(profile, now_ms, is_intermission=is_intermission)
    if catchup["elapsed_sec"] > 1:
        bot_db.update_game_profile(
            telegram_id,
            energy=catchup["new_energy"],
            balance=catchup["new_balance"],
            total_score=catchup["new_total_score"],
            last_active_time=now_ms,
        )
        profile["energy"] = catchup["new_energy"]
        profile["balance"] = catchup["new_balance"]
        profile["total_score"] = catchup["new_total_score"]
        profile["last_active_time"] = now_ms

    # Upgrades map
    upgrades_map = bot_db.get_game_upgrades(telegram_id)

    # Populate upgrades catalog with user status
    catalog_list = []
    for item in UPGRADES_CATALOG.values():
        lvl = upgrades_map.get(item["id"], 0)
        cost = calculate_cost(item["id"], lvl)
        catalog_list.append({
            **item,
            "currentLevel": lvl,
            "nextCost": cost,
            "canAfford": profile["balance"] >= cost,
            "isMaxLevel": lvl >= item["maxLevel"],
        })

    user_rank = bot_db.get_game_user_rank(profile["total_score"])

    return {
        "user": {
            **profile,
            "user_rank": user_rank,
            "upgrades": catalog_list,
            "upgradesMap": upgrades_map,
        },
        "season": season,
    }


def process_tap_batch(telegram_id: int, tap_count: int, combo_boost: bool = False) -> dict:
    season = get_current_season()
    is_intermission = season.get("is_intermission", False)

    profile = bot_db.get_game_profile(telegram_id)
    if not profile:
        profile = bot_db.create_or_get_game_profile(telegram_id)

    now_ms = int(time.time() * 1000)
    catchup = calculate_catchup(profile, now_ms, is_intermission=is_intermission)

    safe_taps = max(0, int(tap_count or 0))

    # Anti-cheat: max 20 taps per second
    max_possible_taps = max(25, int(math.ceil((catchup["elapsed_sec"] + 1) * 20)))
    bounded_taps = min(safe_taps, max_possible_taps)

    # Consume energy
    actual_taps = min(bounded_taps, catchup["new_energy"])
    multiplier = 3 if combo_boost else 1
    tap_score = actual_taps * profile.get("tap_power", 1) * multiplier

    final_energy = max(0, catchup["new_energy"] - actual_taps)
    final_balance = catchup["new_balance"] + tap_score
    if is_intermission:
        final_total_score = 0
    else:
        final_total_score = catchup["new_total_score"] + tap_score

    bot_db.update_game_profile(
        telegram_id,
        energy=final_energy,
        balance=final_balance,
        total_score=final_total_score,
        last_active_time=now_ms,
    )

    return get_user_game_state(telegram_id)


def purchase_upgrade(telegram_id: int, upgrade_id: str) -> dict:
    item = UPGRADES_CATALOG.get(upgrade_id)
    if not item:
        raise ValueError("شناسه ارتقا نامعتبر است.")

    profile = bot_db.get_game_profile(telegram_id)
    if not profile:
        profile = bot_db.create_or_get_game_profile(telegram_id)

    season = get_current_season()
    is_intermission = season.get("is_intermission", False)
    now_ms = int(time.time() * 1000)
    catchup = calculate_catchup(profile, now_ms, is_intermission=is_intermission)
    if catchup["elapsed_sec"] > 1:
        bot_db.update_game_profile(
            telegram_id,
            energy=catchup["new_energy"],
            balance=catchup["new_balance"],
            total_score=catchup["new_total_score"],
            last_active_time=now_ms,
        )
        profile["energy"] = catchup["new_energy"]
        profile["balance"] = catchup["new_balance"]
        profile["total_score"] = catchup["new_total_score"]
        profile["last_active_time"] = now_ms

    upgrades_map = bot_db.get_game_upgrades(telegram_id)
    current_level = upgrades_map.get(upgrade_id, 0)

    if current_level >= item["maxLevel"]:
        raise ValueError("این ارتقا به حداکثر سطح ممکن رسیده است.")

    cost = calculate_cost(upgrade_id, current_level)
    if profile["balance"] < cost:
        raise ValueError("امتیاز و بالانس شما برای این ارتقا کافی نیست.")

    # 1. Deduct balance and increment level
    new_balance = profile["balance"] - cost
    next_level = current_level + 1
    bot_db.set_game_upgrade(telegram_id, upgrade_id, next_level)

    # 2. Update user attributes
    new_tap_power = profile.get("tap_power", 1)
    new_max_energy = profile.get("max_energy", 1000)
    new_energy_rec = profile.get("energy_recovery_rate", 4)
    new_passive_rate = profile.get("passive_rate", 0)

    if item["effectType"] == "tap_power":
        new_tap_power += item["effectValue"]
    elif item["effectType"] == "energy_capacity":
        new_max_energy += item["energyValue"]
        new_energy_rec += item["recoveryValue"]
    elif item["effectType"] == "passive_rate":
        new_passive_rate += item["passiveRate"]

    bot_db.update_game_profile(
        telegram_id,
        balance=new_balance,
        tap_power=new_tap_power,
        max_energy=new_max_energy,
        energy_recovery_rate=new_energy_rec,
        passive_rate=new_passive_rate,
    )

    return get_user_game_state(telegram_id)


def get_prizes_list() -> list[dict]:
    now_ts = time.time()
    if _prizes_cache["prizes"] and now_ts < _prizes_cache["expires_at"]:
        return _prizes_cache["prizes"]

    prize_rank1 = bot_db.get_setting("game_prize_rank1", "کانفیگ اختصاصی ۳ ماهه نامحدود VIP")
    prize_rank2 = bot_db.get_setting("game_prize_rank2", "کانفیگ اختصاصی ۲ ماهه Pro")
    prize_rank3 = bot_db.get_setting("game_prize_rank3", "کانفیگ اختصاصی ۱ ماهه Basic")

    prizes = [
        {"rank": 1, "title": prize_rank1, "icon": "🥇", "tag": "طلایی"},
        {"rank": 2, "title": prize_rank2, "icon": "🥈", "tag": "نقره‌ای"},
        {"rank": 3, "title": prize_rank3, "icon": "🥉", "tag": "برنزی"},
    ]
    _prizes_cache["prizes"] = prizes
    _prizes_cache["expires_at"] = now_ts + 60.0  # 60s cache
    return prizes


def invalidate_prizes_cache():
    """Invalidates the prizes cache and leaderboard cache so changes take effect immediately."""
    _prizes_cache["prizes"] = None
    _prizes_cache["expires_at"] = 0.0
    _lb_cache["data"] = None
    _lb_cache["expires_at"] = 0.0


def get_leaderboard_data() -> dict:
    now_ts = time.time()
    season = get_current_season()

    if _lb_cache["data"] and now_ts < _lb_cache["expires_at"]:
        cached = _lb_cache["data"]
        return {
            "success": True,
            "season": season,
            "leaderboard": cached["leaderboard"],
            "pastWinners": cached["pastWinners"],
            "prizes": cached["prizes"],
        }

    leaderboard = bot_db.get_game_leaderboard(50)
    past_winners = bot_db.get_past_game_winners(15)
    prizes = get_prizes_list()

    _lb_cache["data"] = {
        "leaderboard": leaderboard,
        "pastWinners": past_winners,
        "prizes": prizes,
    }
    _lb_cache["expires_at"] = now_ts + 4.0  # 4s cache to avoid redundant db queries during high traffic

    return {
        "success": True,
        "season": season,
        "leaderboard": leaderboard,
        "pastWinners": past_winners,
        "prizes": prizes,
    }
