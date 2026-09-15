"""Game Service & Season Manager for Mors VPN Clicker Game.

Coordinates user game profiles, upgrades catalog, offline passive mining,
energy regeneration, anti-cheat validation, and Friday night season settlements.
"""

import math
import random
import string
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from . import db as bot_db

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


def check_and_settle_season() -> dict:
    """Checks if the current active weekly season has expired. If so, settles

    winners for Friday night, records prizes, resets scores, and starts a new
    season.
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

        # 2. Close current season
        bot_db.close_game_season(current_season["id"])

        # 3. Reset all players' total_score for the new week (keeps balance & upgrades intact)
        bot_db.reset_season_scores()

        # 4. Start next season
        next_end = get_next_friday_night(now_ms + 1000)
        new_season = bot_db.create_game_season(season_num + 1, now_ms, next_end)
        return new_season

    return current_season


def get_current_season() -> dict:
    season = check_and_settle_season()
    now_ms = int(time.time() * 1000)
    time_left_ms = max(0, season["end_time"] - now_ms)
    return {
        "id": season["id"],
        "season_number": season["season_number"],
        "start_time": season["start_time"],
        "end_time": season["end_time"],
        "time_left_ms": time_left_ms,
    }


def calculate_catchup(user: dict, now_ms: int | None = None) -> dict:
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
    new_total_score = user.get("total_score", 0) + passive_mined

    return {
        "elapsed_sec": elapsed_sec,
        "new_energy": new_energy,
        "passive_mined": passive_mined,
        "new_balance": new_balance,
        "new_total_score": new_total_score,
    }


def get_user_game_state(telegram_id: int, tg_user: dict | None = None) -> dict:
    season = check_and_settle_season()
    now_ms = int(time.time() * 1000)

    user_row = bot_db.get_user_by_telegram_id(telegram_id)
    user_id = user_row["id"] if user_row else None

    # Determine canonical Telegram display name
    tg_name = None
    if tg_user:
        first = (tg_user.get("first_name") or "").strip()
        last = (tg_user.get("last_name") or "").strip()
        full = f"{first} {last}".strip()
        if full:
            tg_name = full
        elif tg_user.get("username"):
            tg_name = f"@{tg_user['username']}"
    if not tg_name and user_row:
        if user_row.get("full_name") and user_row["full_name"].strip():
            tg_name = user_row["full_name"].strip()
        elif user_row.get("username") and user_row["username"].strip():
            tg_name = f"@{user_row['username']}"
    if not tg_name:
        tg_name = f"کاربر {telegram_id}"

    profile = bot_db.create_or_get_game_profile(telegram_id, user_id=user_id, nickname=tg_name)
    if profile.get("nickname") != tg_name:
        bot_db.update_game_profile(telegram_id, nickname=tg_name)
        profile["nickname"] = tg_name

    # Calculate catch-up
    catchup = calculate_catchup(profile, now_ms)
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
        "season": get_current_season(),
    }


def process_tap_batch(telegram_id: int, tap_count: int, combo_boost: bool = False) -> dict:
    profile = bot_db.get_game_profile(telegram_id)
    if not profile:
        profile = bot_db.create_or_get_game_profile(telegram_id)

    now_ms = int(time.time() * 1000)
    catchup = calculate_catchup(profile, now_ms)

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

    # Apply any pending offline passive income and energy recovery before purchase
    now_ms = int(time.time() * 1000)
    catchup = calculate_catchup(profile, now_ms)
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


def get_leaderboard_data() -> dict:
    season = check_and_settle_season()
    leaderboard = bot_db.get_game_leaderboard(50)
    past_winners = bot_db.get_past_game_winners(15)

    prize_rank1 = bot_db.get_setting("game_prize_rank1", "کانفیگ اختصاصی ۳ ماهه نامحدود VIP")
    prize_rank2 = bot_db.get_setting("game_prize_rank2", "کانفیگ اختصاصی ۲ ماهه Pro")
    prize_rank3 = bot_db.get_setting("game_prize_rank3", "کانفیگ اختصاصی ۱ ماهه Basic")

    return {
        "success": True,
        "season": get_current_season(),
        "leaderboard": leaderboard,
        "pastWinners": past_winners,
        "prizes": [
            {"rank": 1, "title": prize_rank1, "icon": "🥇", "tag": "طلایی"},
            {"rank": 2, "title": prize_rank2, "icon": "🥈", "tag": "نقره‌ای"},
            {"rank": 3, "title": prize_rank3, "icon": "🥉", "tag": "برنزی"},
        ],
    }
