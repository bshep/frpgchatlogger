# Chat Logger Project

## Data Source
The data source for this project is:
- http://farmrpg.com/chatlog.php?channel=trade
- the channel should be configurable in the application config but the default should be trade

## Configuration
- The configuration should be stored in localstorage
- At minimum the application should store the following configuration
    - Username: text
    - Channel: text
    - Play Alert: boolean

## Objectives
- Store the chat in a log in a structured manner, mysql, sqlite or flat files are options
- The UI should be served by HTTP
    - The UI should display the current chat with a limit of 200 lines
    - The UI should display a list of messages in which a user has been tagged, a user is tagged when their name is in a chat message with an @ sign preceding it, @username.
    - The list of message should be persisted in localstorage, there should be an option to delete them
- The backend of the app should take care of retrieving the chatlog and saving it so the frontend can easily display it.