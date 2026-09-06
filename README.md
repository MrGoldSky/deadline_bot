# Deadline reminder bot for M3310 group @ ITMO University

This bot is made for Telegram. It keeps a list of deadlines and upcoming tests in a JSON file on the server, posts it to a groupchat as a reminder and refreshes the remaining time every minute. After 1 day, the message is deleted as it is expected that the new message is sent.

Deadlines are added straight from the groupchat with the `/add` command — see [Chat commands](#chat-commands).

# Before first run
Please ensure the following data is relevant for you and modify it at the top of the `main.py` file if needed:

```python
DEADLINES_URL = ""  # optional external deadlines list, merged into the local one; "" disables it
ADD_DEADLINE_LINK = ""  # optional URL of the webpage explaining how to edit that external list
BOT_NAME = "Дединсайдер M3310"
BOT_USERNAME = "m3310_dedinsiderbot"  # username of the bot as it appears in Telegram
```

Also add the following environment variables:

```python
# Environment variables that should be available:
TOKEN = os.getenv("TOKEN")  # Bot token from t.me/botfather
MAIN_GROUP_ID = int(os.getenv("MAIN_GROUP_ID"))  # ID of the group the bot is expected to send deadlines to
```

Optional environment variables:

```python
EDIT_MESSAGE_ID  # edit this existing message instead of sending a new one; single run, no chat commands
ADD_CALENDAR_LINK  # set to "false" to drop the "add to Google Calendar" links
LOCAL_DEADLINES_FILE  # where the deadlines are stored (default: data/deadlines.json)
```

To get `MAIN_GROUP_ID`: add the bot to the group, post any message there and run
`curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool | grep -A4 '"chat"'`.
Do this **before** starting the bot — two clients polling the same token conflict with each other.

# How to run
Run it with `docker compose up -d --build`, or start `main.py` directly. The script sends the message and then keeps running for 24 hours: it refreshes the message every minute and listens for chat commands. After 24 hours it deletes the message and exits, so it is expected to be restarted — either by `restart: unless-stopped` in `compose.yml` or by a cron job.

Set the server timezone to the one your deadlines are written in (`sudo timedatectl set-timezone Europe/Moscow`). `compose.yml` passes it into the container, and the "обновлено в" clock in the message header follows it.

# Where the deadlines live
Everything is stored in `LOCAL_DEADLINES_FILE` (`data/deadlines.json` by default), which `compose.yml` mounts from `./data` so it survives restarts and redeploys. **Back this file up — it is the only copy.**

The format is the same one the upstream bot fetches over HTTP:

```json
{
  "deadlines": [
    {"name": "Джава: Лаба №4", "time": "07 May 2026 23:59:00 GMT+3"},
    {"name": "[Тест] ОСи: Тест", "time": "04 Mar 2026 23:59:00 GMT+3", "url": "https://example.com/"}
  ]
}
```

The file may be edited by hand while the bot is running — it is re-read on every refresh, and commands never overwrite changes made behind their back. Deadlines that have already passed are dropped the next time the file is written. Entries with an unparsable `time` are skipped with a warning instead of breaking the message.

If your group does have an external deadlines list, put its URL into `DEADLINES_URL` and it will be merged with the local one.

# Chat commands
The bot only accepts commands in `MAIN_GROUP_ID`, from anyone in that group. Commands work with the default BotFather privacy settings, since Telegram delivers messages starting with a slash to bots regardless of privacy mode. The bot does not need to be an admin.

| Command | What it does |
| --- | --- |
| `/add Название \| ДД.ММ.ГГГГ ЧЧ:ММ \| ссылка` | Adds a deadline. The link is optional; the time is optional too (defaults to 23:59), and so is the year (the nearest future one is picked). |
| `/list` | Lists the deadlines, numbered. |
| `/del номер` or `/del часть названия` | Removes one. |
| `/help` | Prints the syntax. |

Examples:

```
/add Матан: ДЗ №3 | 15.05
/add [Тест] ОСи: Тест | 3.03.2026 10:00
/add ПБД: 7 этап | 10.05 23:59 | https://info.sqlwars.ru/
```

A `[Тест]`, `[Защита]`, `[Лекция]`, `[Экзамен]` or `[Консультация]` prefix in the name puts the deadline into the matching section of the message.

# Running where Telegram is blocked
Some hosts (Russian datacenters, for instance) cannot reach `api.telegram.org` at all, while the rest of the internet works. Check with `curl -m 10 https://api.telegram.org/`; a timeout means you need a proxy.

Run a local client for your VPN key — [Xray-core](https://github.com/XTLS/Xray-install) with a `socks` inbound on `127.0.0.1:10808` works — and point the bot at it:

```
PROXY=socks5h://127.0.0.1:10808
```

`socks5h` makes the proxy resolve DNS too, which matters when the name itself is poisoned. The bot runs in a container, where `127.0.0.1` is the container rather than the host, so give it the host network in `compose.override.yml` (git-ignored, applied automatically):

```yaml
services:
  deadline_bot:
    network_mode: host
```

Only Telegram traffic goes through the proxy — the bot talks to nothing else.

# Deploy
`.github/workflows/deploy.yml` rsyncs the repo to a server on every push to `main` and restarts the container there. It needs these repository secrets: `SERVER_IP`, `SSH_PORT`, `USERNAME`, `PROJECT_PATH` and `SSH_PRIVATE_KEY` (a deploy key whose public half is in `~/.ssh/authorized_keys` on the server).

`.env` and `data/` are excluded from the rsync, so deploying never overwrites the token or the stored deadlines.
