import time
import asyncio
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
from mailbox_db import SessionLocal as MailboxSessionLocal, UserMonitoringPreference, MailboxStatus
from farmrpg_poller import poll_user_mailbox, MailboxStatusEnum
import mailbox_db


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

def scheduled_mailbox_polling():
    """
    Scheduled job to poll mailboxes of monitored users and update the database.
    """
    print("Running scheduled mailbox polling...")
    db = MailboxSessionLocal()
    try:
        # Get all unique usernames from UserMonitoringPreference
        usernames_to_poll = db.query(UserMonitoringPreference.username).distinct().all()
        usernames = [user[0] for user in usernames_to_poll]
        
        if not usernames:
            print("No monitored users to poll.")
            db.close()
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(asyncio.gather(*[poll_user_mailbox(db, u) for u in usernames]))
        finally:
            loop.close()

        for res in results:
            # print(res) # Keeping this for debugging during development, might remove later
            status_entry = db.query(MailboxStatus).filter(MailboxStatus.username == res["username"]).first()
            if not status_entry:
                status_entry = MailboxStatus(username=res["username"])
                db.add(status_entry)
            
            status_entry.status = res["status"].value if hasattr(res["status"], 'value') else res["status"] # Ensure enum value is stored
            status_entry.last_updated = datetime.utcnow()

            # Only update item counts and ratios if the status is a 'success' type
            if res["status"] in [MailboxStatusEnum.GREEN, MailboxStatusEnum.YELLOW, MailboxStatusEnum.RED]:
                status_entry.current_items = res.get("current_items", 0)
                status_entry.max_items = res.get("max_items", 0)
                status_entry.fill_ratio = res.get("fill_ratio", 0.0)
            else:
                # For error/info statuses, reset or set to default values
                status_entry.current_items = 0
                status_entry.max_items = 0
                status_entry.fill_ratio = 0.0
                print(f"Mailbox polling for user {res['username']} resulted in status: {status_entry.status}. Error: {res.get('error')}")


        db.commit()
        print(f"Mailbox polling complete for {len(usernames)} users.")

    except Exception as e:
        print(f"An error occurred during scheduled mailbox polling: {e}")
        db.rollback()
    finally:
        db.close()


def main():
    print("Initializing scheduler...")

    # Run startup tasks that were in the main app's startup
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)

    # Make sure mailbox DB and tables are created
    mailbox_db.create_db_and_tables()

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
    scheduler.add_job(scheduled_mailbox_polling, 'interval', minutes=1, max_instances=1, id="mailbox_polling")
    scheduler.add_job(archive_old_messages, 'interval', hours=1, max_instances=1, id="archive_messages")
    scheduler.add_job(cleanup_expired_persistent_sessions, 'interval', hours=1, max_instances=1, id="cleanup_sessions")
    # scheduler.add_job(deduplicate_messages, 'interval', seconds=60, max_instances=1, id="deduplicate_messages")
    scheduler.add_job(check_for_config_changes, 'interval', minutes=1, args=[scheduler], id="config_checker")

    # Schedule to run once immediately
    scheduler.add_job(scheduled_log_parsing, 'date', run_date=datetime.now() + timedelta(seconds=1), id="immediate_log_parsing")
    scheduler.add_job(scheduled_mailbox_polling, 'date', run_date=datetime.now() + timedelta(seconds=2), id="immediate_mailbox_polling")

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
