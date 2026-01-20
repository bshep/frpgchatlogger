import requests
from bs4 import BeautifulSoup
import sqlite3
import os

def fetch_staff_names():
    """
    Fetches the list of staff members from farmrpg.com.

    Returns:
        list: A list of staff member usernames, or an empty list if fetching fails.
    """
    url = 'https://farmrpg.com/members.php?type=staff'
    print(f"Fetching staff list from {url}...")
    
    # try:
    #     response = requests.get(url, timeout=15, headers={
    #         'User-Agent': 'curl/8.7.1'
    #     })
    #     response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
    # except requests.exceptions.RequestException as e:
    #     print(f"Error fetching URL: {e}")
    #     return []

    # soup = BeautifulSoup(response.content, 'html.parser')
    
    file_contents = ""
    with open('../sample_data/staff.html', 'r', encoding="utf-8") as fp:
        file_contents = fp.read()

    soup = BeautifulSoup(file_contents, 'html.parser')
    
    # Staff names are in links that point to their profile page.
    # e.g., <a href="profile.php?user_name=Username">Username</a>
    staff_links = soup.find_all('a', href=lambda href: href and 'profile.php?user_name=' in href)
    print(staff_links)
    
    staff_names = [link.find('span').get_text(strip=True) for link in staff_links]
    
    print(f"Found {len(staff_names)} staff members.")
    return staff_names

def update_database(staff_names):
    """
    Connects to the database and inserts the list of staff names into the
    chat_mods table.
    """
    if not staff_names:
        print("No staff names to update.")
        return

    # The script is in /scripts, so the db is at ../backend/chatlog.db
    db_path = os.path.join(os.path.dirname(__file__), '..', 'backend', 'chatlog.db')
    print(f"Connecting to database at {db_path}...")
    
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        # Create the table if it doesn't exist.
        # TEXT UNIQUE will prevent duplicate usernames.
        c.execute('''
            CREATE TABLE IF NOT EXISTS chat_mods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL
            )
        ''')
        print("Table 'chat_mods' ensured to exist.")

        # Insert names, ignoring any that are already present
        c.executemany("INSERT OR IGNORE INTO chat_mods (username) VALUES (?)", [(name,) for name in staff_names])
        
        # We can find out how many rows were actually changed
        changes = conn.total_changes
        
        conn.commit()
        conn.close()

        print(f"Database update complete. Added or updated {changes} records.")

    except sqlite3.Error as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    names = fetch_staff_names()
    update_database(names)
