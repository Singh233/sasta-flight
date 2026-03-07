import logging
from datetime import time as dt_time
from zoneinfo import ZoneInfo

from telegram.ext import Application, CommandHandler

from bot.config import BOT_TOKEN, TIMEZONE
from bot.db import Database
from bot import handlers

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DAILY_JOB_NAME = "daily_scan"


async def schedule_daily_job(application: Application):
    """Schedule or reschedule the daily scan job."""
    # Remove existing daily job
    existing = application.job_queue.get_jobs_by_name(DAILY_JOB_NAME)
    for job in existing:
        job.schedule_removal()

    notify_time = await handlers.db.get_config("notify_time")
    hour, minute = map(int, notify_time.split(":"))
    tz = ZoneInfo(TIMEZONE)

    application.job_queue.run_daily(
        handlers.daily_scan_job,
        time=dt_time(hour=hour, minute=minute, tzinfo=tz),
        name=DAILY_JOB_NAME,
    )
    logger.info(f"Daily scan scheduled at {notify_time} {TIMEZONE}")


async def post_init(application: Application):
    """Called after bot is initialized."""
    db = Database()
    await db.init()
    handlers.db = db
    await schedule_daily_job(application)
    logger.info("SastaFlight bot started")


async def post_shutdown(application: Application):
    """Called on shutdown."""
    if handlers.db:
        await handlers.db.close()


def main():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.add_handler(CommandHandler("start", handlers.start_command))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("add", handlers.add_command))
    application.add_handler(CommandHandler("remove", handlers.remove_command))
    application.add_handler(CommandHandler("routes", handlers.routes_command))
    application.add_handler(CommandHandler("check", handlers.check_command))
    application.add_handler(CommandHandler("time", handlers.time_command))
    application.add_handler(CommandHandler("history", handlers.history_command))
    application.add_handler(CommandHandler("pause", handlers.pause_command))
    application.add_handler(CommandHandler("resume", handlers.resume_command))

    application.run_polling()


if __name__ == "__main__":
    main()
