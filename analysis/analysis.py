import os
import argparse
import sqlite3
import json
import openai
from bs4 import BeautifulSoup
import time

def get_config_value(key, default=None):
    """Fetches a specific config value from the database."""
    conn = sqlite3.connect('backend/chatlog.db')
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key = ?", (key,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else default

def get_messages(start_date=None, end_date=None, channel=None):
    """Fetches all messages from the chatlog.db database based on filters."""
    conn = sqlite3.connect('backend/chatlog.db')
    c = conn.cursor()
    
    query = "SELECT id, timestamp, username, message_html FROM messages"
    params = []
    conditions = []

    if start_date:
        conditions.append("timestamp >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("timestamp <= ?")
        params.append(end_date)
    if channel:
        conditions.append("channel = ?")
        params.append(channel)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
        
    query += " ORDER BY timestamp ASC"
    
    c.execute(query, params)
    messages = c.fetchall()
    
    query = query.replace('messages', 'messages_archive')
    c.execute(query, params)
    messages.extend(c.fetchall())
    
    conn.close()
    print(f"Retrieved {len(messages)} total messages from database.")
    return messages

def cleanup_message(messsage_html) -> str:
    # Clean HTML from messages and format them

    cleaned_message = ""
    # Turn img tags into item names surrounded by (( ))
    message_soup = BeautifulSoup(messsage_html, 'html.parser')
    for img in message_soup.find_all('img'):
        parent = img.find_parent()
        parent.find_next_sibling().replace_with("")
        parent.replace_with(f"(({img['alt']}))")

    return message_soup.get_text()

def analyze_messages(message_chunk_str):
    """
    Analyzes a chunk of pre-formatted messages using an LLM.

    Args:
        message_chunk_str (str): A string containing a chunk of formatted messages.

    Returns:
        dict: The analysis from the LLM.
    """
    with open('analysis/llm_prompt.txt', 'r', encoding="utf-8") as f:
        prompt_template = f.read()

    # IMPORTANT: Replace with your actual OpenAI API key, preferably from an environment variable
    openai.api_key = os.getenv("OPENAI_API_KEY", "OPENAI_API_KEY")
    if openai.api_key == "YOUR_OPENAI_API_KEY":
        print("Warning: OpenAI API key is not set. Please set the OPENAI_API_KEY environment variable.")
        # Return dummy data for development without a key
        return {"trades": [], "transactions": []}

    try:
        response = openai.chat.completions.create(
            model="gpt-4.1", # Or another suitable model like gpt-3.5-turbo
            messages=[
                {"role": "system", "content": prompt_template},
                {"role": "user", "content": f"Analyze the following messages:\n{message_chunk_str}"}
            ],
            response_format={"type": "json_object"} # Use JSON mode for reliable output
        )
        
        return json.loads(response.choices[0].message.content)
    
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        # Return empty structure on error
        return {"trades": [], "transactions": []}

def store_analysis(analysis):
    """Stores the aggregated analysis in the chat_analysis.db database."""
    conn = sqlite3.connect('chat_analysis.db')
    c = conn.cursor()
    
    # Clear existing data
    c.execute('DROP TABLE IF EXISTS trades')
    c.execute('DROP TABLE IF EXISTS transactions')
    
    c.execute('''
        CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, sender TEXT, item TEXT, quantity INTEGER, price TEXT, timestamp TEXT)
    ''')
    c.execute('''
        CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, seller TEXT, buyer TEXT, item TEXT, quantity INTEGER, price TEXT, timestamp TEXT)
    ''')
    
    # Process trades
    for trade in analysis.get('trades', []):
        items = trade.get('item')
        if isinstance(items, list):
            for item_name in items:
                c.execute("INSERT INTO trades (type, sender, item, quantity, price, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                          (trade.get('type'), trade.get('sender'), item_name, trade.get('quantity'), trade.get('price'), trade.get('timestamp')))
        else: # item is a single string or None
            c.execute("INSERT INTO trades (type, sender, item, quantity, price, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                      (trade.get('type'), trade.get('sender'), items, trade.get('quantity'), trade.get('price'), trade.get('timestamp')))

    # Process transactions
    for transaction in analysis.get('transactions', []):
        items = transaction.get('item')
        if isinstance(items, list):
            for item_name in items:
                c.execute("INSERT INTO transactions (seller, buyer, item, quantity, price, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                          (transaction.get('seller'), transaction.get('buyer'), item_name, transaction.get('quantity'), transaction.get('price'), transaction.get('timestamp')))
        else: # item is a single string or None
            c.execute("INSERT INTO transactions (seller, buyer, item, quantity, price, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                      (transaction.get('seller'), transaction.get('buyer'), items, transaction.get('quantity'), transaction.get('price'), transaction.get('timestamp')))
        
    conn.commit()
    conn.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Analyze chat logs.')
    parser.add_argument('--start-date', help='Start date for filtering messages (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date for filtering messages (YYYY-MM-DD)')
    parser.add_argument('--channel', default="trade", help="The channel to analyze, 'trade' if not provided")
    args = parser.parse_args()
    
    os.chdir("..")
    
    # 1. Fetch all messages
    all_messages = get_messages(args.start_date, args.end_date, args.channel)
    
    # 2. Clean and format all messages
    cleaned_messages = []
    for msg in all_messages:
        # This simplified cleaning preserves the ((item)) format if it exists
        cleaned_text = cleanup_message(msg[3]).replace(msg[2] + ": ","")
        # Format: "- username (timestamp): message"
        cleaned_messages.append(f"- {msg[2]} ({msg[1].replace('.000000', '')}): {cleaned_text}")

    # 3. Get chunk size from config
    try:
        chunk_size = int(get_config_value('analysis_chunk_size', 50))
    except (ValueError, TypeError):
        chunk_size = 50
    print(f"Using chunk size: {chunk_size}")

    # 4. Process messages in chunks
    aggregated_analysis = {"trades": [], "transactions": []}
    
    for i in range(0, len(cleaned_messages), chunk_size):
        chunk = cleaned_messages[i:i + chunk_size]
        message_chunk_str = "\n".join(chunk)
        
        print(f"Analyzing chunk {i // chunk_size + 1}/{(len(cleaned_messages) + chunk_size - 1) // chunk_size}...")
        analysis_result = analyze_messages(message_chunk_str)
        print(f"===========\n{message_chunk_str}\n==========")
        if analysis_result.get('trades'):
            aggregated_analysis['trades'].extend(analysis_result['trades'])
        if analysis_result.get('transactions'):
            aggregated_analysis['transactions'].extend(analysis_result['transactions'])
        # Optional: sleep to avoid hitting rate limits
        if i > chunk_size:
            break

    # 5. Store the final aggregated results
    store_analysis(aggregated_analysis)
    
    print("Analysis complete and stored in chat_analysis.db")