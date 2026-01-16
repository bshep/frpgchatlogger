import time
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

from main import (
    Base,
    engine,
    SessionLocal,
    get_config,
    set_config,
    scheduled_log_parsing,
    archive_old_messages,
    cleanup_expired_persistent_sessions,
    deduplicate_messages,
    run_migrations
)

def main():
    print("Initializing scheduler...")

    # Run startup tasks that were in the main app's startup
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)

    db = SessionLocal()
    if not get_config(db, "channels_to_track"):
        set_config(db, "channels_to_track", "trade,giveaways")
    if not get_config(db, "allowed_users"):
        set_config(db, "allowed_users", "")
    if not get_config(db, "allowed_guilds"):
        set_config(db, "allowed_guilds", "")
    db.close()

    # Run these once at startup
    print("Performing initial archive and deduplication...")
    archive_old_messages()
    deduplicate_messages()
    print("Initial tasks complete.")

    scheduler = BackgroundScheduler()
    # Add jobs
    scheduler.add_job(scheduled_log_parsing, 'interval', seconds=5, max_instances=1, id="log_parsing")
    scheduler.add_job(archive_old_messages, 'interval', hours=1, max_instances=1, id="archive_messages")
    scheduler.add_job(cleanup_expired_persistent_sessions, 'interval', hours=1, max_instances=1, id="cleanup_sessions")
    scheduler.add_job(deduplicate_messages, 'interval', seconds=60, max_instances=1, id="deduplicate_messages")

    # Schedule to run once immediately
    scheduler.add_job(scheduled_log_parsing, 'date', run_date=datetime.now() + timedelta(seconds=1), id="immediate_log_parsing")

    scheduler.start()
    print("Scheduler started. Press Ctrl+C to exit.")

    try:
        # Keep the script running
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("Scheduler shut down.")

if __name__ == "__main__":
    main()
