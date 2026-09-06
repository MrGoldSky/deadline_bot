import datetime as dt
import html
import json
import locale
import logging
import os
import re
import time
import urllib.parse
import sys

import requests

# Modify the links and data below.
# Дедлайны хранятся в LOCAL_DEADLINES_FILE и наполняются командой /add.
# DEADLINES_URL и ADD_DEADLINE_LINK нужны, только если есть внешний список
# дедлайнов: тогда он будет подмешиваться к локальному. Пустая строка — выключено.
DEADLINES_URL = ""
ADD_DEADLINE_LINK = ""
BOT_NAME = "Дединсайдер M3310"
BOT_USERNAME = "m3310_dedinsiderbot"

# Environment variables that should be available:
API_URL = 'https://api.telegram.org/bot'
TOKEN = os.getenv("TOKEN")
MAIN_GROUP_ID = int(os.getenv("MAIN_GROUP_ID") or '0')
EDIT_MESSAGE_ID = int(os.getenv("EDIT_MESSAGE_ID") or '0')
ADD_CALENDAR_LINK = os.getenv("ADD_CALENDAR_LINK") != 'false'
LOCAL_DEADLINES_FILE = os.getenv("LOCAL_DEADLINES_FILE") or "data/deadlines.json"
# Прокси для запросов к Telegram, например socks5h://127.0.0.1:10808 или
# http://127.0.0.1:8080. Нужен там, где api.telegram.org недоступен напрямую.
PROXY = os.getenv("PROXY") or ""
PROXIES = {'http': PROXY, 'https': PROXY} if PROXY else None

assert TOKEN, "Missing token!"
assert MAIN_GROUP_ID, "Missing group ID!"

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

NUMBER_EMOJIS = ['0.', '1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']

MSK = dt.timezone(dt.timedelta(hours=3))
MONTHS_EN = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

MAX_NAME_LENGTH = 100  # максимальная длина названия дедлайна, добавленного командой
POLL_TIMEOUT = 25  # сколько секунд ждать новые команды в одном запросе getUpdates
REFRESH_INTERVAL = dt.timedelta(seconds=60)
PROCESS_START = time.time()


class TelegramException(Exception):
    def __init__(self, *, error_code: int, description: str, **_):
        super().__init__(f'Error {error_code}: {description}')
        self.error_code = error_code
        self.description = description


def telegram_request(method: str, args: dict, timeout: int = 30):
    try:
        data = requests.post(API_URL + f'{TOKEN}/{method}', json=args,
                             timeout=timeout, proxies=PROXIES).json()
        if not data['ok']:
            raise TelegramException(**data)
        return data
    except requests.exceptions.RequestException as e:
        logging.error(f"Network error in {method}: {e}")
        raise


def send_message(text: str, reply_to: int = 0) -> int:
    args = {
        'chat_id': MAIN_GROUP_ID,
        'parse_mode': 'HTML',
        'text': text,
        'link_preview_options': {
            'is_disabled': True
        }
    }
    if reply_to:
        args['reply_parameters'] = {
            'message_id': reply_to,
            'allow_sending_without_reply': True
        }
    return telegram_request('sendMessage', args)['result']['message_id']


def edit_message(message_id: int, text: str) -> int:
    return telegram_request('editMessageText', {
        'chat_id': MAIN_GROUP_ID,
        'parse_mode': 'HTML',
        'message_id': message_id,
        'text': text,
        'link_preview_options': {
            'is_disabled': True
        }
    })['result']['message_id']


def delete_message(message_id: int) -> bool:
    return telegram_request('deleteMessage', {
        'chat_id': MAIN_GROUP_ID,
        'message_id': message_id
    })['result']


def get_current_time() -> str:
    current_time = dt.datetime.now()
    current_time_hour = current_time.hour if current_time.hour >= 10 else "0" + str(current_time.hour)
    current_time_minute = current_time.minute if current_time.minute >= 10 else "0" + str(current_time.minute)
    return f"{current_time_hour}:{current_time_minute}"


def get_dt_obj_from_string(time: str) -> dt.datetime:
    time = time.replace('GMT+3', '+0300')
    try:
        locale.setlocale(locale.LC_TIME, 'en_US.UTF-8')
    except locale.Error:
        locale.setlocale(locale.LC_TIME, 'C')
    return dt.datetime.strptime(time, "%d %b %Y %H:%M:%S %z")


def generate_link(event_name: str, event_time: str) -> str:
    dt_obj = get_dt_obj_from_string(event_time)
    formatted_time = dt_obj.strftime("%Y%m%dT%H%M%S%z")
    description = f"Дедлайн добавлен ботом {BOT_NAME} (https://t.me/{BOT_USERNAME})"
    link = f"https://calendar.google.com/calendar/u/0/r/eventedit?" \
           f"text={urllib.parse.quote(event_name)}&" \
           f"dates={formatted_time}/{formatted_time}"
    return link


def get_human_timedelta(time: str) -> str:
    dt_obj = get_dt_obj_from_string(time)
    dt_now = dt.datetime.now(dt_obj.tzinfo)
    delta = dt_obj - dt_now

    total_seconds = int(delta.total_seconds())
    days = total_seconds // (24 * 3600)
    hours = (total_seconds % (24 * 3600)) // 3600
    minutes = (total_seconds % 3600) // 60

    if days >= 5:
        return f"{days} дней"
    elif days >= 2:
        return f"{days} дня"
    elif days == 1:
        return f"1 день {hours}ч {minutes}м"
    else:
        return f"{hours}ч {minutes}м"


def get_human_time(time: str) -> str:
    dt_obj = get_dt_obj_from_string(time)
    try:
        locale.setlocale(locale.LC_TIME, 'ru_RU.UTF-8')
    except locale.Error:
        locale.setlocale(locale.LC_TIME, 'C')
    formatted_date = dt_obj.strftime("%a, %d %B в %H:%M")
    return formatted_date


def timestamp_func(a: dict) -> float:
    time = a["time"].replace('GMT+3', '+0300')
    try:
        locale.setlocale(locale.LC_TIME, 'en_US.UTF-8')
    except locale.Error:
        locale.setlocale(locale.LC_TIME, 'C')
    a_timestamp = dt.datetime.strptime(time, "%d %b %Y %H:%M:%S %z").timestamp()
    return a_timestamp


def relevant_filter_func(d: dict) -> bool:
    try:
        dt_obj = get_dt_obj_from_string(d["time"])
    except (KeyError, ValueError) as e:
        logging.warning(f"Skipping malformed deadline {d}: {e}")
        return False
    return not dt_obj < dt.datetime.now(dt_obj.tzinfo)


def deadline_type_filter_func(d: dict, dtype: str = '') -> bool:
    if not dtype:
        return not re.match(r'^\[.*\]', d['name'])

    return f"[{dtype.lower()}]" in d["name"].lower()


# ============================ Локальные дедлайны ============================
# Дедлайны, добавленные командой /add. Хранятся в том же формате, что и
# дедлайны из DEADLINES_URL, и подмешиваются к ним при сборке сообщения.

def load_local_deadlines() -> list:
    try:
        with open(LOCAL_DEADLINES_FILE, encoding='utf-8') as f:
            return json.load(f).get("deadlines", [])
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        logging.error(f"Failed to read {LOCAL_DEADLINES_FILE}: {e}")
        return []


def save_local_deadlines(deadlines: list) -> None:
    directory = os.path.dirname(LOCAL_DEADLINES_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)

    # Прошедшие дедлайны больше не нужны — чистим, чтобы файл не рос вечно
    deadlines = list(filter(relevant_filter_func, deadlines))

    tmp_file = LOCAL_DEADLINES_FILE + '.tmp'
    with open(tmp_file, 'w', encoding='utf-8') as f:
        json.dump({"deadlines": deadlines}, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, LOCAL_DEADLINES_FILE)


def sorted_local_deadlines(deadlines: list) -> list:
    return sorted(filter(relevant_filter_func, deadlines), key=timestamp_func)


def format_deadline_time(dt_obj: dt.datetime) -> str:
    dt_obj = dt_obj.astimezone(MSK)
    return f"{dt_obj.day:02d} {MONTHS_EN[dt_obj.month - 1]} {dt_obj.year} " \
           f"{dt_obj.hour:02d}:{dt_obj.minute:02d}:{dt_obj.second:02d} GMT+3"


USER_DATE_RE = re.compile(
    r'^(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?'
    r'(?:[\s,]+(\d{1,2})[:.](\d{2}))?$'
)


def parse_user_datetime(text: str) -> dt.datetime:
    match = USER_DATE_RE.match(text.strip())
    if not match:
        raise ValueError("Не понял дату")

    day, month, year, hour, minute = match.groups()
    hour = int(hour) if hour is not None else 23
    minute = int(minute) if minute is not None else 59

    now = dt.datetime.now(MSK)
    if year is None:
        year_value = now.year
    elif len(year) == 2:
        year_value = 2000 + int(year)
    else:
        year_value = int(year)

    try:
        result = dt.datetime(year_value, int(month), int(day), hour, minute, tzinfo=MSK)
    except ValueError:
        raise ValueError("Такой даты не существует")

    # Год не указан, а дата уже прошла — значит, имеется в виду следующий год
    if year is None and result < now:
        try:
            result = result.replace(year=year_value + 1)
        except ValueError:  # 29 февраля в невисокосном году
            raise ValueError("Укажите год явно")

    return result


def describe_user(user: dict) -> str:
    if user.get('username'):
        return '@' + user['username']
    name = ' '.join(filter(None, [user.get('first_name'), user.get('last_name')]))
    return name or str(user.get('id', '?'))


# ================================= Команды =================================

USAGE_ADD = (
    "<code>/add Название | ДД.ММ.ГГГГ ЧЧ:ММ | ссылка</code>\n\n"
    "Ссылка не обязательна, время тоже (по умолчанию 23:59), "
    "год можно не писать — возьмётся ближайший.\n\n"
    "Примеры:\n"
    "<code>/add Матан: ДЗ №3 | 15.05</code>\n"
    "<code>/add [Тест] ОСи: Тест | 3.03.2026 10:00</code>\n"
    "<code>/add ПБД: 7 этап | 10.05 23:59 | https://info.sqlwars.ru/</code>\n\n"
    "Префикс <code>[Тест]</code>, <code>[Защита]</code>, <code>[Лекция]</code>, "
    "<code>[Экзамен]</code> или <code>[Консультация]</code> кладёт дедлайн "
    "в соответствующий раздел."
)

HELP_TEXT = (
    f"🤖 <b>{BOT_NAME}</b>\n\n"
    "<b>/add</b> — добавить дедлайн:\n"
    f"{USAGE_ADD}\n\n"
    "<b>/list</b> — список добавленных командами дедлайнов с номерами\n"
    "<b>/del номер</b> или <b>/del часть названия</b> — удалить такой дедлайн\n"
    "<b>/help</b> — эта справка\n\n"
    "Все дедлайны хранятся в одном файле на сервере и добавляются только отсюда."
)


def reply(message: dict, text: str) -> None:
    try:
        send_message(text, reply_to=message['message_id'])
    except Exception as e:
        logging.error(f"Failed to reply: {e}")


def cmd_add(args: str, message: dict) -> bool:
    parts = [part.strip() for part in args.split('|')]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        reply(message, f"📝 <b>Как добавить дедлайн:</b>\n{USAGE_ADD}")
        return False

    name, raw_time = parts[0], parts[1]
    url = parts[2] if len(parts) > 2 and parts[2] else None

    if len(name) > MAX_NAME_LENGTH:
        reply(message, f"❌ Название длиннее {MAX_NAME_LENGTH} символов")
        return False

    if url and not re.match(r'^https?://\S+$', url):
        reply(message, "❌ Ссылка должна начинаться с http:// или https://")
        return False

    try:
        deadline_dt = parse_user_datetime(raw_time)
    except ValueError as e:
        reply(message, f"❌ {e}\n\n{USAGE_ADD}")
        return False

    if deadline_dt <= dt.datetime.now(MSK):
        reply(message, "❌ Эта дата уже прошла")
        return False

    deadline = {"name": name, "time": format_deadline_time(deadline_dt)}
    if url:
        deadline["url"] = url
    deadline["added_by"] = describe_user(message.get('from', {}))
    deadline["added_at"] = format_deadline_time(dt.datetime.now(MSK))

    deadlines = load_local_deadlines()
    deadlines.append(deadline)
    save_local_deadlines(deadlines)
    logging.info(f"Deadline added by {deadline['added_by']}: {name} ({deadline['time']})")

    reply(message, f"✅ <b>{html.escape(name)}</b>\n"
                   f"{get_human_time(deadline['time'])} — через {get_human_timedelta(deadline['time'])}")
    return True


def cmd_list(args: str, message: dict) -> bool:
    deadlines = sorted_local_deadlines(load_local_deadlines())
    if not deadlines:
        reply(message, "Дедлайнов пока нет.\n\n"
                       f"📝 <b>Как добавить дедлайн:</b>\n{USAGE_ADD}")
        return False

    text = "📌 <b>Добавленные командой дедлайны:</b>\n\n"
    for i, deadline in enumerate(deadlines, start=1):
        text += f"{i}. <b>{html.escape(deadline['name'])}</b> — {get_human_time(deadline['time'])}"
        if deadline.get('added_by'):
            text += f" (от {html.escape(deadline['added_by'])})"
        text += "\n"
    text += "\nУдалить: <code>/del номер</code>"

    reply(message, text)
    return False


def cmd_del(args: str, message: dict) -> bool:
    query = args.strip()
    if not query:
        reply(message, "Укажите номер из /list или часть названия: <code>/del 2</code>")
        return False

    stored = load_local_deadlines()
    deadlines = sorted_local_deadlines(stored)
    if not deadlines:
        reply(message, "Дедлайнов пока нет, удалять нечего")
        return False

    if query.isdigit():
        number = int(query)
        if not 1 <= number <= len(deadlines):
            reply(message, f"❌ Нет дедлайна с номером {number}. Список — /list")
            return False
        targets = [deadlines[number - 1]]
    else:
        targets = [d for d in deadlines if query.lower() in d['name'].lower()]

    if not targets:
        reply(message, "❌ Не нашёл такой дедлайн. Список — /list")
        return False

    if len(targets) > 1:
        names = "\n".join(f"• {html.escape(d['name'])}" for d in targets)
        reply(message, f"❌ Под запрос подходит несколько дедлайнов:\n{names}\n\n"
                       "Уточните запрос или удалите по номеру из /list")
        return False

    stored.remove(targets[0])
    save_local_deadlines(stored)
    logging.info(f"Deadline removed by {describe_user(message.get('from', {}))}: {targets[0]['name']}")

    reply(message, f"🗑 Удалено: <b>{html.escape(targets[0]['name'])}</b>")
    return True


def cmd_help(args: str, message: dict) -> bool:
    reply(message, HELP_TEXT)
    return False


COMMANDS = {
    'add': cmd_add,
    'del': cmd_del,
    'delete': cmd_del,
    'list': cmd_list,
    'help': cmd_help,
    'start': cmd_help,
}

COMMAND_RE = re.compile(r'^/(\w+)(?:@(\S+))?(?:\s+([\s\S]+))?$')


def handle_command(message: dict, bot_username: str) -> bool:
    """Обрабатывает команду. Возвращает True, если список дедлайнов изменился."""
    match = COMMAND_RE.match((message.get('text') or '').strip())
    if not match:
        return False

    command, mention, args = match.groups()
    if mention and mention.lower() != bot_username.lower():
        return False  # команда адресована другому боту

    handler = COMMANDS.get(command.lower())
    if not handler:
        return False

    try:
        return handler(args or '', message)
    except Exception as e:
        logging.error(f"Failed to handle /{command}: {e}")
        reply(message, "❌ Что-то пошло не так, попробуйте ещё раз")
        return False


def get_updates(offset: int, timeout: int) -> list:
    args = {'timeout': timeout, 'allowed_updates': ['message']}
    if offset:
        args['offset'] = offset
    return telegram_request('getUpdates', args, timeout=timeout + 10)['result']


def skip_pending_updates() -> int:
    """Пропускает команды, накопившиеся пока бот не работал."""
    try:
        updates = get_updates(-1, 0)
    except Exception as e:
        logging.warning(f"Failed to skip pending updates: {e}")
        return 0
    return updates[-1]['update_id'] + 1 if updates else 0


def set_bot_commands() -> None:
    """Регистрирует команды, чтобы Telegram подсказывал их при вводе."""
    commands = [
        {'command': 'add', 'description': 'Добавить дедлайн: Название | ДД.ММ.ГГГГ ЧЧ:ММ'},
        {'command': 'list', 'description': 'Дедлайны, добавленные командой'},
        {'command': 'del', 'description': 'Удалить добавленный командой дедлайн'},
        {'command': 'help', 'description': 'Справка по командам'},
    ]
    try:
        telegram_request('setMyCommands', {
            'commands': commands,
            'scope': {'type': 'chat', 'chat_id': MAIN_GROUP_ID}
        })
    except Exception as e:
        logging.warning(f"Failed to register commands: {e}")


def get_bot_username() -> str:
    try:
        return telegram_request('getMe', {})['result']['username']
    except Exception as e:
        logging.warning(f"Failed to get bot username ({e}), assuming {BOT_USERNAME}")
        return BOT_USERNAME


def handle_updates(updates: list, bot_username: str) -> bool:
    changed = False
    for update in updates:
        message = update.get('message')
        if not message or message.get('chat', {}).get('id') != MAIN_GROUP_ID:
            continue
        if message.get('date', 0) < PROCESS_START - 60:
            continue  # старая команда, отправленная до запуска бота
        if handle_command(message, bot_username):
            changed = True
    return changed


# ================================ Сообщение ================================

def fetch_remote_deadlines():
    """Возвращает список дедлайнов из DEADLINES_URL или None, если получить не удалось."""
    if not DEADLINES_URL:
        return []

    try:
        response = requests.get(DEADLINES_URL, timeout=30, proxies=PROXIES).json()
    except Exception as e:
        logging.error(f"Failed to fetch deadlines: {e}")
        return None
    return response.get("deadlines", [])


def get_message_text():
    """Текст сообщения, "" если дедлайнов нет и None если их не удалось получить."""
    remote_deadlines = fetch_remote_deadlines()
    if remote_deadlines is None:
        return None

    all_deadlines = remote_deadlines + load_local_deadlines()

    # Фильтруем только актуальные дедлайны
    relevant_deadlines = list(filter(relevant_filter_func, all_deadlines))

    # Если вообще нет актуальных дедлайнов - возвращаем пустую строку
    if not relevant_deadlines:
        logging.info("No relevant deadlines found")
        return ""

    types = [
        ('', ''),  # deadlines без типа
        ('🧑‍💻 Тесты', 'тест'),
        ('🛡 Защиты', 'защита'),
        ('🎓 Лекции', 'лекция'),
        ('🤓 Экзамены', 'экзамен'),
        ('👞 Консультации', 'консультация'),
    ]

    assignments = []
    for x in types:
        filtered = list(filter(lambda t: deadline_type_filter_func(t, x[1]), relevant_deadlines))
        assignments.append((sorted(filtered, key=lambda z: timestamp_func(z)), x[0], x[1]))

    text = f"🔥️️ <b>Дедлайны</b> (<i>Обновлено в {get_current_time()} 🔄</i>):\n\n"

    def add_items(items: list, category_name: str = '', replace_name: str = ''):
        if len(items) == 0:
            return

        nonlocal text
        REPLACE_PATTERN = re.compile(rf'^\[{replace_name}\] ', flags=re.IGNORECASE)

        if category_name:
            text += f"\n<b>{category_name}</b>:\n\n"

        for i, item in enumerate(items):
            no = i + 1
            if no <= 10:
                no = NUMBER_EMOJIS[no] + " "
            else:
                no = str(no) + ". "

            text += no + "<b>"

            name = re.sub(REPLACE_PATTERN, '', item['name'])
            url = item.get('url')

            if url:
                text += f"<a href=\"{html.escape(url)}\">{html.escape(name)}</a>"
            else:
                text += html.escape(name)

            text += "</b> — "
            text += get_human_timedelta(item["time"])
            if ADD_CALENDAR_LINK:
                text += f"\n(<a href=\"{generate_link(name, item['time'])}\">"
                text += get_human_time(item["time"]) + "</a>)\n\n"
            else:
                text += f'\n({get_human_time(item["time"])})\n\n'

    # Добавляем все категории
    for assignment_type in assignments:
        add_items(*assignment_type)

    if ADD_DEADLINE_LINK:
        text += (
            f"\n🆕 <a href=\"{ADD_DEADLINE_LINK}\">"
            f"Добавить дедлайн</a> или командой /add (подробнее — /help)"
        )
    else:
        text += "\n🆕 Добавить дедлайн: /add (подробнее — /help)"

    return text


def sync_message(msg_id, text):
    """Приводит сообщение в чате в соответствие с актуальными дедлайнами."""
    new_text = get_message_text()

    if new_text is None:
        # Дедлайны получить не удалось — оставляем сообщение как есть
        return msg_id, text

    if not new_text:
        if msg_id:
            logging.info("No more deadlines. Deleting message.")
            delete_message(msg_id)
        return None, None

    if msg_id is None:
        msg_id = send_message(new_text)
        logging.info(f"New message sent. Msg id: {msg_id}")
        return msg_id, new_text

    if new_text != text:
        edit_message(msg_id, new_text)
        logging.info(f"Message updated. Msg id: {msg_id}")
        return msg_id, new_text

    logging.debug(f"Message update skipped (no changes). Msg id: {msg_id}")
    return msg_id, text


def run_edit_mode() -> None:
    """Режим обновления существующего сообщения: один проход, команды не читаются."""
    text = get_message_text()
    if not text:
        logging.info("No deadlines to display. Exiting.")
        return

    try:
        edit_message(EDIT_MESSAGE_ID, text)
        logging.info(f"Message updated successfully. Msg id: {EDIT_MESSAGE_ID}")
    except TelegramException as e:
        if e.error_code == 400:  # Message not found
            logging.warning(f"Message {EDIT_MESSAGE_ID} not found, creating new")
            msg_id = send_message(text)
            logging.info(f"New message created. Msg id: {msg_id}")
        else:
            logging.error(f"Failed to update message: {e}")


def main() -> None:
    if EDIT_MESSAGE_ID:
        run_edit_mode()
        return

    # Режим создания нового сообщения (работает 24 часа) с приёмом команд
    if PROXY:
        logging.info(f"Using proxy {PROXY}")
    bot_username = get_bot_username()
    set_bot_commands()
    offset = skip_pending_updates()
    logging.info(f"Listening for commands as @{bot_username} in chat {MAIN_GROUP_ID}")

    msg_id = None
    text = None
    started_updating = dt.datetime.now()
    next_refresh = started_updating

    while dt.datetime.now() - started_updating < dt.timedelta(days=1):
        if dt.datetime.now() >= next_refresh:
            next_refresh = dt.datetime.now() + REFRESH_INTERVAL
            try:
                msg_id, text = sync_message(msg_id, text)
            except TelegramException as e:
                if e.error_code == 400:  # Message not found (удалено)
                    logging.warning(f"Message {msg_id} was deleted, will post a new one")
                    msg_id, text = None, None
                elif e.error_code == 429:  # Too Many Requests
                    logging.warning(f"Rate limited, waiting 60s")
                    time.sleep(60)
                else:
                    logging.error(f"Error updating message: {e}")
            except Exception as e:
                logging.error(f"Unexpected error: {e}")

        # Ждём команды. Запрос висит до POLL_TIMEOUT секунд и заодно
        # задаёт паузу между обновлениями сообщения
        try:
            updates = get_updates(offset, POLL_TIMEOUT)
            if updates:
                offset = updates[-1]['update_id'] + 1
            if handle_updates(updates, bot_username):
                next_refresh = dt.datetime.now()  # сразу показываем изменения
        except Exception as e:
            logging.error(f"Failed to get updates: {e}")
            time.sleep(5)

    # Удаляем сообщение после 24 часов, если оно еще существует
    if msg_id:
        try:
            delete_message(msg_id)
            logging.info(f"Message deleted after 24 hours. Msg id: {msg_id}")
        except Exception as e:
            logging.error(f"Failed to delete message: {e}")


if __name__ == '__main__':
    main()
