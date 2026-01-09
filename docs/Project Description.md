# Chat Logger Project

## 1. Overview

This project aims to create a web-based chat logger for the game Farm RPG. It will fetch chat data from the game's website, parse it, store it, and display it in a user-friendly interface. The application will provide features for tracking the general chat and highlighting messages that mention a specific user.

## 2. Data Source

-   **URL:** `http://farmrpg.com/chatlog.php?channel=<channel_name>`
-   The `channel_name` will be configurable in the application, with a default value of `trade`.

## 3. Core Components

The application will consist of two main parts: a backend service for data processing and a frontend UI for display and interaction.

### 3.1. Backend

The backend service will be responsible for periodically fetching, parsing, and storing chat data.

**Responsibilities:**
-   **Polling:** Automatically fetch the chat log HTML from the data source at a configurable interval (e.g., every 30 seconds).
-   **Parsing:** Parse the raw HTML to extract individual chat messages. Based on the source, each message contains:
    -   Timestamp (e.g., "Jan 9, 03:33:11 PM")
    -   Username (e.g., "yohijoey")
    -   Message Content (HTML format, including item links and mentions)
-   **Storage:** Store the parsed chat messages in a structured and persistent way. A local SQLite database is recommended. A suggested schema for a `messages` table would be:
    -   `id`: INTEGER PRIMARY KEY (unique identifier for each message)
    -   `timestamp`: DATETIME
    -   `username`: TEXT
    -   `message_html`: TEXT
    -   `channel`: TEXT

### 3.2. Frontend

The frontend will be a web interface served over HTTP, providing the user with a view of the chat and their personal mentions.

**UI Features:**
-   **Main Chat View:** Display the most recent chat messages, limited to a reasonable number (e.g., 200 lines) for performance. New messages should appear automatically as they are fetched.
-   **Mentions View:** Display a separate list of messages where the configured user's name is mentioned (e.g., `@username`).
    -   These mentions must be persisted in the browser's `localStorage`.
    -   The user must have the ability to clear the list of mentions.
-   **Alerts:** If the "Play Alert" setting is enabled, the UI should play an audible sound whenever a new message containing the user's mention arrives.

### 3.3. API Endpoints

The frontend and backend will communicate via a simple HTTP API.

-   `GET /api/messages`: Fetches the latest chat messages.
    -   Query Parameters: `?limit=200`, `?channel=trade`
-   `GET /api/mentions`: Fetches all messages that mention the configured user.
-   `DELETE /api/mentions`: Clears all stored mentions for the user.

## 4. Configuration

Application settings will be stored in the browser's `localStorage` for persistence.

-   **Username** (text): The user's Farm RPG name, used for highlighting mentions.
-   **Channel** (text): The chat channel to monitor (e.g., "trade", "help"). Defaults to `trade`.
-   **Play Alert** (boolean): If checked, an alert sound will play on new mentions. Defaults to `true`.
-   **Polling Interval** (number): The frequency in seconds at which to fetch new chat data. Defaults to `30`.