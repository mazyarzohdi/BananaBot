"""Purges expired API-replay nonces (and, optionally, old request logs).

Run periodically (e.g. hourly, via cron/systemd timer):
    python manage.py cleanup_api_security

This is a housekeeping task only — correctness of replay protection does
NOT depend on this ever running (a nonce is rejected purely by the
UNIQUE(api_key_id, nonce) constraint, regardless of age). Its only
purpose is to keep the `api_nonces` table from growing forever.
"""

from django.core.management.base import BaseCommand

from panel import db as bot_db
from panel.api import constants


class Command(BaseCommand):
    help = "Deletes expired api_nonces rows (and old api_request_log rows if --logs-days is given)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--logs-days", type=int, default=None,
            help="Also delete api_request_log rows older than this many days.",
        )

    def handle(self, *args, **options):
        bot_db.cleanup_old_nonces(constants.NONCE_RETENTION_SECONDS)
        self.stdout.write(self.style.SUCCESS("api_nonces cleaned up."))

        logs_days = options.get("logs_days")
        if logs_days:
            bot_db.cleanup_old_api_logs(logs_days * 86400)
            self.stdout.write(self.style.SUCCESS(f"api_request_log rows older than {logs_days} days deleted."))
