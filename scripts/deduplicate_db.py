import sys
import os
from sqlalchemy import func

# Add the parent directory to the path to allow importing from 'backend'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from backend.main import SessionLocal, Message, MessageArchive
except ImportError as e:
    print("Error: Could not import from 'backend.main'.")
    print("Please ensure you run this script from the project's root directory.")
    print(f"Details: {e}")
    sys.exit(1)

def deduplicate_table(db_session, model):
    """
    Finds and deletes duplicate entries in a given table based on
    (timestamp, username, channel) composite key.
    """
    table_name = model.__tablename__
    print(f"Checking for duplicates in '{table_name}' table...")
    
    # 1. Find groups of rows that are duplicates
    duplicate_groups = db_session.query(
        model.timestamp,
        model.username,
        model.channel,
        func.count(model.id).label('count')
    ).group_by(
        model.timestamp,
        model.username,
        model.channel
    ).having(func.count(model.id) > 1).all()

    total_deleted = 0
    if not duplicate_groups:
        print(f"No duplicates found in '{table_name}'.")
        return

    print(f"Found {len(duplicate_groups)} groups of duplicate messages in '{table_name}'. Processing...")

    # 2. For each group, find all IDs, then delete all but the one with the minimum ID
    for group in duplicate_groups:
        # Get all rows for the current duplicate group, ordered by ID
        all_duplicate_rows = db_session.query(model).filter(
            model.timestamp == group.timestamp,
            model.username == group.username,
            model.channel == group.channel
        ).order_by(model.id).all()

        # The first one in the list is the one we keep; the rest are to be deleted
        rows_to_delete = all_duplicate_rows[1:]
        
        for row in rows_to_delete:
            db_session.delete(row)
        
        num_deleted_for_group = len(rows_to_delete)
        total_deleted += num_deleted_for_group
        print(f"  - Deleting {num_deleted_for_group} extra entries for user '{group.username}' at {group.timestamp} in channel '{group.channel}'.")

    # 3. Commit the transaction
    db_session.commit()
    print(f"\nTotal duplicate entries deleted from '{table_name}': {total_deleted}")


if __name__ == "__main__":
    print("--- Starting Database Deduplication Script ---")
    db = SessionLocal()
    try:
        deduplicate_table(db, Message)
        print("-" * 20)
        deduplicate_table(db, MessageArchive)
        print("\nProcess complete. Your database should now be free of duplicates in the message tables.")
    except Exception as e:
        print(f"An error occurred: {e}")
        print("Rolling back changes.")
        db.rollback()
    finally:
        db.close()
