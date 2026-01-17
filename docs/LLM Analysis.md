# Project Description

## Purpose

To use an LLM to analyze trades recorded from a trade chat stream from an online game.

We should return a list of offers to sell or buy goods and completed transactions, it should show the:
* seller
* items traded and their prices
* timestamp of the transaction
* buyer ( best effort in finding the buyer but not essential )

## Data Source
The data will be provided in a database, chatlog.db, with the messages in two tables:
* messages - messaged received < 2hrs ago
* messages_archive - messages >2hrs old

The tables have the same structure and contain:
* id - unique id assigned by the DB for the message
* timestamp - the time the message was sent
* sender - the username of the sender
* message_text - the text of the message, html formatted

## Trade Description

### Trade message types
* Sales - usually preceded by: WTS, Selling, LTS, For Sale or equivalents
* Buys - usually preceded by: WTB, Buying, LTB, LF, Want or equivalents
* Trades - usually preceded by: WTT, Trading, Want to trade
* Price Cheks - usually preceded by: PC, Price Check, whats the price of

### Buy/Sell Messages
Examples:
  * WTB - 1k ((Feathers)) 4apk -> The sender wants to BUY 1k ( 1000 ) of the item inside the '(( ))' in this case 'Feathers' and the price is 4ap per k (1000)
  * WTS - 1k ((Feathers)) 4apk -> The sender wants to SELL 1k ( 1000 ) of the item inside the '(( ))' in this case 'Feathers' and the price is 4ap per k (1000)
  * ...more examples with gold, ac, etc 

### Price Check Messages
Examples:
  * PC - ((Feathers)) -> Sender want to know the price of an item named 'Feathers'

### Trades 
Examples:
  * WTT - 1k ((Feathers)) for 2k((Mushroom)) -> Sender wants to trade their 1000 'Feathers' for another persons 2000 'Mushrooms' in the specified quantities

### Combined Messages
There may be messages that combine the above types of messages, for example a user may want to sell some items but also wants to buy a different set of items.

Example:
  * WTS - 10k ((Mushroom)) 5apk, 12k ((Aquamarine)) 3apk; WTB - 15k ((Snowball)) 5apk -> The user wants to sell 10000 'Mushroom' at 5apk and 12000 'Aquamarine' at 3apk AND also is buying 15000 'Snowball' at 5apk

### Transactions
Here we describe a trade transaction and what is considered a completed trade.

Flow:
* Transactions start with an offer as above
* An accepting buyer replying with one of the following:
  * the name of the offering user -> this means the person wants to buy or is selling all the items the original sender posted for
  * the name of the offering user and a quantity and optionally an item name -> this means the person wants to buy or is selling a certain quantity the original sender posted
* Optionally the original sender will again mention the buyer as confirmation with an otherwise empty message
* Optionally the buyer and seller both send a thank you message:
  *  'ty'
  *  'tysm'
  *  'tyvm'
  *  emojis that mean thanks

## Output Format
Data should be output by the LLM in json format and the stored in a new database, chat_analysis.db.

## Tasks
* Create a new directory 'analysis' to contain the new scripts, update deployment scripts to include this directory in the deployment
* Create an LLM prompt suitable to perform the needed analysis and place it the analysis directory for review
* Create the script to perform the analysis
 * plan is to call this script from a new page in the frontend 'analysis.html'
 * plan out the page so it has relevant inputs to the script to filter the data to be analyzed
 * update backend as needed to support the script
 * the script will user an openai api key to perform the LLM analysis
 * include a data viewer in analysis.html to view the generated LLM data