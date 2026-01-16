import time
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

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

def check_for_config_changes(scheduler):
    """
    Checks the database for a new polling interval and reschedules the
    log_parsing job if the interval has changed.
    """
    with SessionLocal() as db:
        new_interval_str = get_config(db, "scheduler_polling_interval", "5")
        try:
            new_interval = int(new_interval_str)
            if new_interval < 3: # Enforce a minimum
                new_interval = 3
        except (ValueError, TypeError):
            new_interval = 5
    
    job = scheduler.get_job("log_parsing")
    # The job trigger might not be an IntervalTrigger if it has run its course and is rescheduled
    # This check is to prevent errors in that case
    if job and isinstance(job.trigger, IntervalTrigger) and job.trigger.interval.total_seconds() != new_interval:
        print(f"Polling interval changed. Modifying log_parsing job to run every {new_interval} seconds.")
        # Use modify_job to change the trigger of the existing job
        scheduler.modify_job("log_parsing", trigger=IntervalTrigger(seconds=new_interval))

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
    if not get_config(db, "admin_users"):
        set_config(db, "admin_users", "")
    if not get_config(db, "scheduler_polling_interval"):
        set_config(db, "scheduler_polling_interval", "5")
        
    # Get polling interval
    polling_interval_str = get_config(db, "scheduler_polling_interval", "5")
    try:
        polling_interval = int(polling_interval_str)
        if polling_interval < 3: # Enforce a minimum
            polling_interval = 3
    except (ValueError, TypeError):
        polling_interval = 5
    print(f"Using polling interval of {polling_interval} seconds.")

    db.close()

    # Run these once at startup
    print("Performing initial archive and deduplication...")
    archive_old_messages()
    deduplicate_messages()
    print("Initial tasks complete.")

    scheduler = BackgroundScheduler()
    # Add jobs
    scheduler.add_job(scheduled_log_parsing, 'interval', seconds=polling_interval, max_instances=1, id="log_parsing")
    scheduler.add_job(archive_old_messages, 'interval', hours=1, max_instances=1, id="archive_messages")
    scheduler.add_job(cleanup_expired_persistent_sessions, 'interval', hours=1, max_instances=1, id="cleanup_sessions")
    scheduler.add_job(deduplicate_messages, 'interval', seconds=60, max_instances=1, id="deduplicate_messages")
    scheduler.add_job(check_for_config_changes, 'interval', minutes=1, args=[scheduler], id="config_checker")

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
