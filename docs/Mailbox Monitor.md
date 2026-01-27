# Mailbox Monitor

## Purpose

Monitor a set of mailboxes in the game FarmRPG and determine if there is space in them for new items, i.e. less than 50% full or at least 100 empty spaces, whichever is smaller.

## Which Mailboxes to monitor

Each user of the site will designate up to 5 mailbox they wish to monitor, they will be provided a text-box with each user placed in a line on the text-box, usernames are to be sanitized, with any leading '@' removed and traling ':' also removed.

If one user requests polling 'User A' and another used also requests polling 'User A', the users mailbox will be polled ONCE but both requesting users will get a notification.

## How to determine is a mailbox state

First load, where USERNAME is the urlencoded username:
* `https://farmrpg.com/profile.php?user_name=USERNAME`

Then search for the following a tag, we are interested in the number MBOXID of the URL, the MBOXID should be cached as it never changes:
* `<a href="mailbox.php?id=MBOXID" style="cursor:pointer"><img src="/img/mailboxes/mailbox89.png" style="max-width:80px;width:100%;vertical-align: bottom"></a>`

Then load, please use the cookies provided here:
* `https://farmrpg.com/mailbox.php?id=MBOXID`
    * Cookies
        * farmrpg_token=ms4va20ulqi5eqi3d3u8cd0fjdq510patjg81ibn
        * HighwindFRPG	jpsauB751C4suBlUfV%2B9x%2F0JiYSOhMFIongLB%2BNjT9k%3D%3Cstrip%3E%24argon2id%24v%3D19%24m%3D7168%2Ct%3D4%2Cp%3D1%24UmJQdHdKeXNTN3dEL0lOTw%24PI3%2FFhpSH1WuoYzXBivw2DWHChpYsUdwCWCJcBtLgLU
        * pac_ocean=43F8CA30

Look for the following tag and find the numbers corresponding to CURRENT_ITEMS and MAX_ITEMS:
* `<strong><span id="1399-inmailbox">CURRENT_ITEMS</span> / MAX_ITEMS</strong>`

The mailbox is considered open if one of the following is true, otherwise its closed
* MAX_ITEMS - CURRENT_ITEMS > 100
* CURRENT_ITEMS / MAX_ITEMS <= 0.5

## How to display results

Display a table with the usernames and RED/YELLOW/GREEN for status
* RED - closed
* YELLOW - open but more than 10% full
* GREEN - less than 10% full
