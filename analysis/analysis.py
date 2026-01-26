import os
import argparse
import sqlite3
import json
import openai
from bs4 import BeautifulSoup
import time
from dotenv import load_dotenv

def get_config_value(db, key, default):
    """Fetches a specific config value from the database."""
    if not db:
        return None
    
    conn = sqlite3.connect(db)
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key = ?", (key,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else default

def get_messages(db, start_date=None, end_date=None, channel=None):
    """Fetches all messages from the chatlog.db database based on filters."""
    if not db:
        return []
    
    conn = sqlite3.connect(db)
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

def extract_transaction_details_with_llm(price_str, quantity_int, item_name, transaction_id=None):
    """
    Parses a price string, quantity, and item name using an LLM to extract
    price value, currency, and confirmed quantity for Stage 3 normalization.
    Returns (parsed_quantity, parsed_price_value, parsed_price_currency) or (None, None, None) if parsing fails.
    """
    load_dotenv('analysis.env')
    openai.api_key = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")
    if openai.api_key == "YOUR_OPENAI_API_KEY":
        print(f"Warning: OpenAI API key is not set. Please set the OPENAI_API_KEY environment variable. (Transaction ID: {transaction_id})")
        return None, None, None

    with open('llm_prompt_stage3_parse_transaction.txt', 'r', encoding="utf-8") as f:
        prompt_template = f.read()

    user_content = f"Item: {item_name}\nPrice: \"{price_str}\"\nQuantity: {quantity_int}"

    try:
        response = openai.chat.completions.create(
            model="gpt-4.1-mini", # Use gpt-4 for robust parsing in Stage 3
            messages=[
                {"role": "system", "content": prompt_template},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"},
            temperature=0 # For deterministic parsing
        )
        
        llm_response = json.loads(response.choices[0].message.content)
        
        parsed_quantity = llm_response.get('quantity')
        parsed_price_value = llm_response.get('price_value')
        parsed_price_currency = llm_response.get('price_currency')

        # Validate types and values
        if (isinstance(parsed_quantity, int) and parsed_quantity > 0 and
            isinstance(parsed_price_value, (int, float)) and
            isinstance(parsed_price_currency, str)):
            return parsed_quantity, float(parsed_price_value), parsed_price_currency
        else:
            print(f"LLM returned invalid parse for Transaction ID: {transaction_id}, Item: '{item_name}', Price: '{price_str}', Quantity: {quantity_int}. Response: {llm_response}")
            return None, None, None
            
    except Exception as e:
        print(f"Error calling LLM for price parsing (Transaction ID: {transaction_id}, Item: '{item_name}', Price: '{price_str}', Quantity: {quantity_int}): {e}")
        return None, None, None

def parse_price_and_quantity(price_str, quantity_int):
    """
    Parses a price string and quantity using an LLM to extract total value and confirmed quantity.
    Returns (parsed_total_value, parsed_quantity) or (None, None) if parsing fails.
    """
    load_dotenv('analysis.env')
    openai.api_key = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")
    if openai.api_key == "YOUR_OPENAI_API_KEY":
        print("Warning: OpenAI API key is not set. Please set the OPENAI_API_KEY environment variable.")
        return None, None

    with open('llm_prompt_parse_transaction.txt', 'r', encoding="utf-8") as f:
        prompt_template = f.read()

    user_content = f"Price: \"{price_str}\"\nQuantity: {quantity_int}"

    try:
        response = openai.chat.completions.create(
            model="gpt-4.1-mini", # Use gpt-4 for robust parsing
            messages=[
                {"role": "system", "content": prompt_template},
                {"role": "user", "content": user_content}
            ],
            response_format={"type": "json_object"},
            temperature=0 # For deterministic parsing
        )
        
        llm_response = json.loads(response.choices[0].message.content)
        
        parsed_total_value = llm_response.get('parsed_total_value')
        parsed_quantity = llm_response.get('parsed_quantity')

        # Validate types and values
        if isinstance(parsed_total_value, (int, float)) and isinstance(parsed_quantity, int) and parsed_quantity > 0:
            return float(parsed_total_value), parsed_quantity
        else:
            # print(f"LLM returned invalid parse for Price: '{price_str}', Quantity: {quantity_int}. Response: {llm_response}")
            return None, None
            
    except Exception as e:
        print(f"Error calling LLM for price parsing (Price: '{price_str}', Quantity: {quantity_int}): {e}")
        return None, None

def analyze_messages(message_chunk_str):
    """
    Analyzes a chunk of pre-formatted messages using an LLM.

    Args:
        message_chunk_str (str): A string containing a chunk of formatted messages.

    Returns:
        dict: The analysis from the LLM.
    """
    with open('llm_prompt.txt', 'r', encoding="utf-8") as f:
        prompt_template = f.read()

    # IMPORTANT: Replace with your actual OpenAI API key, preferably from an environment variable
    load_dotenv('analysis.env')
    
    openai.api_key = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY")
    if openai.api_key == "YOUR_OPENAI_API_KEY":
        print("Warning: OpenAI API key is not set. Please set the OPENAI_API_KEY environment variable.")
        # Return dummy data for development without a key
        raise Exception("OPENAI_API_KEY Not set")

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

def store_analysis(db, analysis):
    """
    Stores the aggregated analysis in the chat_analysis.db database.
    It adds new entries if they don't already exist, rather than clearing the table.
    """
    if not db:
        return
    
    conn = sqlite3.connect('../chat_analysis.db')
    c = conn.cursor()
    
    # Create tables if they don't exist
    c.execute('''
        CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, sender TEXT, item TEXT, quantity INTEGER, price TEXT, timestamp TEXT)
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, seller TEXT, buyer TEXT, item TEXT, quantity INTEGER, price TEXT, timestamp TEXT)
    ''')
    
    # Process trades
    for trade in analysis.get('trades', []):
        items = trade.get('item')
        if isinstance(items, list):
            for item_name in items:
                # Check for existing trade to avoid duplicates
                c.execute("SELECT id FROM trades WHERE type = ? AND sender = ? AND item = ? AND quantity = ? AND price = ? AND timestamp = ?",
                          (trade.get('type'), trade.get('sender'), item_name, trade.get('quantity'), trade.get('price'), trade.get('timestamp')))
                if c.fetchone() is None:
                    c.execute("INSERT INTO trades (type, sender, item, quantity, price, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                              (trade.get('type'), trade.get('sender'), item_name, trade.get('quantity'), trade.get('price'), trade.get('timestamp')))
        else: # item is a single string or None
            c.execute("SELECT id FROM trades WHERE type = ? AND sender = ? AND item = ? AND quantity = ? AND price = ? AND timestamp = ?",
                      (trade.get('type'), trade.get('sender'), items, trade.get('quantity'), trade.get('price'), trade.get('timestamp')))
            if c.fetchone() is None:
                c.execute("INSERT INTO trades (type, sender, item, quantity, price, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                          (trade.get('type'), trade.get('sender'), items, trade.get('quantity'), trade.get('price'), trade.get('timestamp')))

    # Process transactions
    for transaction in analysis.get('transactions', []):
        items = transaction.get('item')
        if isinstance(items, list):
            for item_name in items:
                # Check for existing transaction to avoid duplicates
                c.execute("SELECT id FROM transactions WHERE seller = ? AND buyer = ? AND item = ? AND quantity = ? AND price = ? AND timestamp = ?",
                          (transaction.get('seller'), transaction.get('buyer'), item_name, transaction.get('quantity'), transaction.get('price'), transaction.get('timestamp')))
                if c.fetchone() is None:
                    c.execute("INSERT INTO transactions (seller, buyer, item, quantity, price, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                              (transaction.get('seller'), transaction.get('buyer'), item_name, transaction.get('quantity'), transaction.get('price'), transaction.get('timestamp')))
        else: # item is a single string or None
            c.execute("SELECT id FROM transactions WHERE seller = ? AND buyer = ? AND item = ? AND quantity = ? AND price = ? AND timestamp = ?",
                      (transaction.get('seller'), transaction.get('buyer'), items, transaction.get('quantity'), transaction.get('price'), transaction.get('timestamp')))
            if c.fetchone() is None:
                c.execute("INSERT INTO transactions (seller, buyer, item, quantity, price, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                          (transaction.get('seller'), transaction.get('buyer'), items, transaction.get('quantity'), transaction.get('price'), transaction.get('timestamp')))
        
    conn.commit()
    conn.close()

def migrate_schema(db_path):
    """
    Migrates the schema of chat_analysis.db to ensure all necessary columns exist.
    """
    print("--- Running Schema Migration ---")
    conn = sqlite3.connect('../chat_analysis.db')
    c = conn.cursor()

    # Add normalized_price to trades table if it doesn't exist
    c.execute("PRAGMA table_info(trades)")
    columns = [col[1] for col in c.fetchall()]
    if 'normalized_price' not in columns:
        c.execute("ALTER TABLE trades ADD COLUMN normalized_price REAL")
        print("Added 'normalized_price' column to 'trades' table.")
    
    # Add normalized_price to transactions table if it doesn't exist
    c.execute("PRAGMA table_info(transactions)")
    columns = [col[1] for col in c.fetchall()]
    if 'normalized_price' not in columns:
        c.execute("ALTER TABLE transactions ADD COLUMN normalized_price REAL")
        print("Added 'normalized_price' column to 'transactions' table.")
    
    conn.commit()
    conn.close()
    print("--- Schema Migration Complete ---")

def run_stage_1(db_path, start_date, end_date, channel):
    """
    Stage 1: Extracts trade offers and completed transactions from raw chat messages.
    """
    print("--- Running Stage 1: Trade and Transaction Extraction ---")
    
    # 1. Fetch all messages
    all_messages = get_messages(db_path, start_date, end_date, channel)
    
    # 2. Clean and format all messages
    cleaned_messages = []
    for msg in all_messages:
        cleaned_text = cleanup_message(msg[3]).replace(msg[2] + ": ","")
        cleaned_messages.append(f"- {msg[2]} ({msg[1].replace('.000000', '')}): {cleaned_text}")

    # 3. Get chunk size from config
    try:
        chunk_size = int(get_config_value(db_path, 'analysis_chunk_size', 50))
    except (ValueError, TypeError):
        chunk_size = 50
    print(f"Using chunk size: {chunk_size}")

    # 4. Process messages in chunks
    aggregated_analysis = {"trades": [], "transactions": []}
    for i in range(0, len(cleaned_messages), chunk_size):
        chunk = cleaned_messages[i:i + chunk_size]
        message_chunk_str = "\n".join(chunk)

        print(f"Analyzing chunk {i // chunk_size + 1}/{(len(cleaned_messages) + chunk_size - 1) // chunk_size}...\r")
        analysis_result = analyze_messages(message_chunk_str)
        if analysis_result.get('trades'):
            aggregated_analysis['trades'].extend(analysis_result['trades'])
        if analysis_result.get('transactions'):
            aggregated_analysis['transactions'].extend(analysis_result['transactions'])
        print(analysis_result.get('transactions'))
        return
    
    # 5. Store the final aggregated results
    store_analysis(db_path, aggregated_analysis)
    
    print("--- Stage 1 Complete ---")

def run_stage_2(db_path):
    """
    Stage 2: Calculates the average price for a set of base items using LLM-parsed transaction data
    and stores it.
    """
    print("\n--- Running Stage 2: Average Price Calculation ---")
    migrate_schema(db_path) # Ensure schema is up-to-date

    conn = sqlite3.connect('../chat_analysis.db')
    c = conn.cursor()

    # Create a table to store the average prices of base items
    c.execute('''
        CREATE TABLE IF NOT EXISTS item_average_prices (
            item_name TEXT PRIMARY KEY,
            average_price REAL
        )
    ''')

    base_items = ['Arnold Palmer', 'Orange Juice', 'Apple Cider', 'Large Net']

    for item_name in base_items:
        c.execute("SELECT quantity, price FROM transactions WHERE item = ?", (item_name,))
        raw_transactions = c.fetchall()
        
        total_sum_values = 0
        total_sum_quantities = 0
        valid_transaction_count = 0

        print(f"Processing transactions for '{item_name}'...")
        for raw_quantity, raw_price in raw_transactions:
            parsed_total_value, parsed_quantity = parse_price_and_quantity(raw_price, raw_quantity)
            # print(f"- Text {raw_quantity}/{raw_price} -> {parsed_quantity}/{parsed_total_value}")
            
            if parsed_total_value is not None and parsed_quantity is not None and parsed_quantity > 100:
                total_sum_values += parsed_total_value
                total_sum_quantities += parsed_quantity
                valid_transaction_count += 1
            else:
                # print(f"  Skipping invalid transaction: Price='{raw_price}', Quantity='{raw_quantity}'")
                pass

        average_price = 0
        if total_sum_quantities > 0:
            average_price = total_sum_values / (total_sum_quantities/1000)
            c.execute("INSERT OR REPLACE INTO item_average_prices (item_name, average_price) VALUES (?, ?)", (item_name, average_price))
            print(f"Average price for '{item_name}' (from {valid_transaction_count} valid transactions): {average_price:.2f}")
            # break
        else:
            print(f"No valid transactions found for '{item_name}' after parsing, or total quantity is zero. Average price set to 0.")
            # Ensure an entry exists even if average is 0
            c.execute("INSERT OR REPLACE INTO item_average_prices (item_name, average_price) VALUES (?, ?)", (item_name, 0.0))

    conn.commit()
    conn.close()
    print("--- Stage 2 Complete ---")

def run_stage_3(db_path):
    """
    Stage 3: Normalizes prices in the trades and transactions tables based on the
    average prices calculated in Stage 2.
    """
    print("\n--- Running Stage 3: Price Normalization ---")
    print("This stage will normalize prices based on the data from Stage 2.")
    
    conn = sqlite3.connect('../chat_analysis.db')
    c = conn.cursor()

    # Fetch average prices for base items from Stage 2
    c.execute("SELECT item_name, average_price FROM item_average_prices")
    average_prices_map = {row[0]: row[1] for row in c.fetchall()}

    if not average_prices_map:
        print("No average prices found from Stage 2. Please run Stage 2 first.")
        conn.close()
        return

    # base_price_for_normalization = average_prices_map.get(base_item_for_normalization)

    # Define currency conversion rates relative to a common unit (e.g., 'gold')
    # These would ideally be dynamic or configurable, but hardcoding for now.
    currency_conversion_to_gold = {
        'gold': 1.0,
        'arnold palmer': average_prices_map.get("Arnold Palmer"),
        'orange juice': average_prices_map.get("Orange Juice"),
        'apple cider': average_prices_map.get("Apple Cider"),
        'large net': average_prices_map.get("Large Net")
    }

    print(currency_conversion_to_gold)
    # Process transactions
    print("Normalizing transactions...")
    c.execute("SELECT id, item, quantity, price FROM transactions WHERE price ")
    transactions_to_normalize = c.fetchall()

    base_items = ['Arnold Palmer', 'Orange Juice', 'Apple Cider', 'Large Net']

    count = 0
    for trans_id, item, raw_quantity, raw_price in transactions_to_normalize:
        print(f"  Transaction {trans_id}:")
        print(f" - RawQ = {raw_quantity}, RawP = {raw_price}")
        if item in base_items:
            normalized_price = average_prices_map.get(item)
        else:
            parsed_quantity, price_value, price_currency = extract_transaction_details_with_llm(raw_price, raw_quantity, item, trans_id)
            print(f" - ParQ = {parsed_quantity}, ParV = {price_value}, ParC = {price_currency}")

            normalized_price = None
            if parsed_quantity is not None and price_value is not None and price_currency is not None:
                # Convert the price_value to a common unit (e.g., 'gold')
                conversion_factor = currency_conversion_to_gold.get(price_currency.lower(), 1.0) # Default to 1 if currency unknown
                print(f" - Conversion Factor = {conversion_factor}")
                price_in_gold_units = price_value * 1/conversion_factor
                
                # Calculate price per item in gold units
                normalized_price = price_in_gold_units / (parsed_quantity/1000)

        if normalized_price is not None:
            c.execute("UPDATE transactions SET normalized_price = ? WHERE id = ?", (normalized_price, trans_id))
            print(f"Normalized Price = {normalized_price:.4f}")
        else:
            print(f"  Could not normalize transaction {trans_id}: Item='{item}', Price='{raw_price}', Quantity='{raw_quantity}'")
            # Optionally set to NULL or 0 if normalization fails
            c.execute("UPDATE transactions SET normalized_price = NULL WHERE id = ?", (trans_id,))
            count -=1

        count += 1
        if count> 5:
            break        
    # For now, it just updates normalized_price to NULL for trades
    c.execute("UPDATE trades SET normalized_price = NULL WHERE normalized_price IS NULL")


    conn.commit()
    conn.close()
    print("--- Stage 3 Complete ---")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Analyze chat logs in stages.')
    parser.add_argument('--start-date', help='Start date for filtering messages (YYYY-MM-DD) for Stage 1.')
    parser.add_argument('--end-date', help='End date for filtering messages (YYYY-MM-DD) for Stage 1.')
    parser.add_argument('--channel', default="trade", help="The channel to analyze for Stage 1, 'trade' if not provided.")
    parser.add_argument('--db', default="../backend/chatlog.db", help="The path for the db file (Default: ../backend/chatlog.db)")
    parser.add_argument('--stage', default='all', choices=['1', '2', '3', 'all'], help="Which analysis stage to run.")
    
    args = parser.parse_args()
    
    if args.stage == '1' or args.stage == 'all':
        run_stage_1(args.db, args.start_date, args.end_date, args.channel)
    
    if args.stage == '2' or args.stage == 'all':
        run_stage_2(args.db)
        
    if args.stage == '3' or args.stage == 'all':
        run_stage_3(args.db)
        
    print("\nAnalysis pipeline finished.")