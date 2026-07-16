"""Template context processors for the panel app."""

from . import db as bot_db
from .auth import get_current_user


def reseller_context(request):
    """Exposes `is_reseller` to every template so the sidebar can show/hide
    the "پنل نمایندگی" nav item without every single view needing to look
    it up manually. Cheap (one indexed lookup) and only runs for logged-in,
    non-admin requests."""
    tg_user = get_current_user(request)
    if not tg_user:
        return {}
    try:
        telegram_id = int(tg_user["id"])
    except (KeyError, TypeError, ValueError):
        return {}
    db_user = bot_db.get_user_by_telegram_id(telegram_id)
    if not db_user:
        return {}
    reseller = bot_db.get_reseller_by_user_id(db_user["id"])
    return {"is_reseller": bool(reseller)}
