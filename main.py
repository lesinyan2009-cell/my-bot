import random
import time
import json
import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# ─── Flask — keep-alive для Render + UptimeRobot ─────────────────────────────
app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

Thread(target=run_flask, daemon=True).start()

# ─── Пассивная регенерация HP и MP (каждые 5 минут +10) ──────────────────────

def regen_loop():
    while True:
        time.sleep(300)  # 5 минут
        changed = False
        for uid, p in list(user_data.items()):
            if p.get("race"):
                p["hp"] = min(p["max_hp"], p["hp"] + 10)
                p["mp"] = min(p["max_mp"], p["mp"] + 10)
                changed = True
        if changed:
            save_data()

# ─── Бот ──────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv('BOT_TOKEN')

# ─── MongoDB ──────────────────────────────────────────────────────────────────
_mongo_client = MongoClient(os.getenv('MONGO_URL'))
_db = _mongo_client["gamebot"]

bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=4)

user_data = {}
chat_members = {}  # chat_id -> set of uid — кто играл в этом чате
active_pvp = {}   # одиночные дуэли
active_brawl = {} # многопользовательские битвы
callback_spam = {}  # антиспам: uid -> timestamp

RACE_STATS = {
    # Ловкач: средний HP, средний MP, высокая ловкость — сила в физатаках
    "Томатная эльфийка": {"hp": 100, "mp": 60,  "dex": 14, "emoji": "🍅"},
    # Боец: высокий HP, низкий MP, средняя ловкость — баланс физ/маг
    "Брокен боб":         {"hp": 120, "mp": 40,  "dex": 11, "emoji": "🫘"},
    # Танк: очень высокий HP, минимум MP и ловкости — только физ, но живучий
    "Какашливый гусеница":{"hp": 140, "mp": 20,  "dex": 8,  "emoji": "🐛"},
    # Маг: низкий HP, очень высокий MP, средняя ловкость — сила в магии
    "Данилость":          {"hp": 95,  "mp": 110, "dex": 10, "emoji": "✨"},
    # Командир: выше среднего HP и MP, низкая ловкость — универсал
    "Ютуки величайший":   {"hp": 115, "mp": 70,  "dex": 7,  "emoji": "👑"},
}

RACE_KEYS = list(RACE_STATS.keys())

RACE_COMBAT = {
    "Томатная эльфийка":  {"phys": "швыряет острый томатный кинжал",    "magic": "кастует взрывной томатный сок"},
    "Брокен боб":          {"phys": "таранит врага титановой кожурой",    "magic": "призывает бобовый взрыв"},
    "Какашливый гусеница": {"phys": "падает всей массой прямо на врага",  "magic": "выпускает удушающий туман"},
    "Данилость":           {"phys": "резко бьет волшебным посохом",       "magic": "выпускает луч космической данилости"},
    "Ютуки величайший":    {"phys": "бьет врага золотой перчаткой",       "magic": "использует магию грозного приказа"},
}

MONSTERS_DB = {
    # Лёгкие (бонус 6–8) — хороши для старта
    "Томатость 🍅":  {"type": "всё",  "bonus": 6,  "desc": "выглядит нелепо, но кусается"},
    "Пузырь 🫧":    {"type": "лёд",  "bonus": 8,  "desc": "надувается и взрывается"},
    # Средние (бонус 10–11) — основной контент
    "Мекзость 🧠":  {"type": "ум",   "bonus": 10, "desc": "хитрит мыслями"},
    "Грязнюха 🪣":  {"type": "яд",   "bonus": 11, "desc": "брызгается мусором"},
    # Сложные (бонус 13–15) — вызов для прокачанных
    "Чорность 🔮":  {"type": "маг",  "bonus": 13, "desc": "бьет темной магией"},
    "Размезность 💪":{"type": "сила","bonus": 15, "desc": "бьет кулачищами"},
}

ITEMS_DB = {
    "sword":   {"name": "Сломанный меч 🗡️",    "desc": "+3 боевой бонус навсегда"},
    "juice":   {"name": "Томатный сок 🥤",       "desc": "Полное восстановление HP и MP"},
    "crown":   {"name": "Корона Ютуки 👑",        "desc": "+5 боевой бонус навсегда"},
    "boots":   {"name": "Дырявые сапоги 👞",      "desc": "+3 ловкость навсегда"},
    "potion":  {"name": "Странное зелье 🧪",      "desc": "50/50: +30 HP или -20 HP"},
    "shield":  {"name": "Титановый щит 🛡️",       "desc": "+20 к максимальному HP"},
    "tome":    {"name": "Мистический том 📖",     "desc": "+20 к максимальному MP"},
    "amulet":  {"name": "Амулет удачи 🍀",        "desc": "Следующий бросок гарантированно 15+"},
    "fishrod": {"name": "Удочка Тьмы 🎣",         "desc": "Может поймать 1 случайный предмет"},
    "cactus":  {"name": "Карманный кактус 🌵",    "desc": "+2 к ловкости, но -5 HP при экипировке"},
    "cheese":  {"name": "Сыр Судьбы 🧀",          "desc": "Полное восстановление HP, но -10 MP"},
}

ITEM_KEYS = list(ITEMS_DB.keys())

# ─── Случайные действия ───────────────────────────────────────────────────────
FUNNY_ACTIONS = [
    "случайно ломает стол в таверне 🪑",
    "спотыкается о жирную гусеницу 🐛",
    "кричит, что Ютуки — величайший 👑",
    "пытается сделать сальто в грязь 💩",
    "обнимает случайного крестьянина и плачет 😭",
    "пытается продать монстру страховку 📋",
    "застрял в собственном плаще на 3 минуты 🧥",
    "объявляет себя торговцем редкими камушками 💎",
    "танцует лезгинку без причины 💃",
    "пробует на вкус магический пыльник 🌸 и ничего не происходит",
    "делает вид, что умеет летать, и прыгает с бревна 🪵",
    "созывает совет мудрецов, но приходит только один боб 🫘",
]

# Случайные события при битве (флейвор)
BATTLE_EVENTS = [
    "Внезапный ветер сбивает с толку обоих! 🌪️",
    "Мимо проходит курица и игнорирует всех 🐔",
    "Земля слегка трясётся — наверное кто-то упал 💥",
    "",  # пусто = обычная битва
    "",
    "",
]

DROP_CHANCE = 0.10  # 10% шанс дропа


# ─── сохранение / загрузка ────────────────────────────────────────────────────

def load_data():
    global user_data, chat_members
    try:
        doc = _db.users.find_one({"_id": "gamestate"})
        if doc:
            user_data = {int(k): v for k, v in doc["users"].items()}
            chat_members = {int(cid): set(uids) for cid, uids in doc.get("chat_members", {}).items()}
            for uid, p in user_data.items():
                p.setdefault("lucky_amulet", False)
                p.setdefault("wins", 0)
                p.setdefault("losses", 0)
                p.setdefault("pvp_wins", 0)
                p.setdefault("pvp_win_dates", [])
            print("Данные загружены из MongoDB: " + str(len(user_data)) + " игроков")
        else:
            user_data = {}
            chat_members = {}
            print("MongoDB: новая база данных")
    except Exception as e:
        print("Ошибка загрузки из MongoDB: " + str(e))
        user_data = {}
        chat_members = {}


def save_data():
    try:
        serializable_users = {str(uid): p for uid, p in user_data.items()}
        serializable_chat_members = {str(cid): list(uids) for cid, uids in chat_members.items()}
        _db.users.replace_one(
            {"_id": "gamestate"},
            {"_id": "gamestate", "users": serializable_users, "chat_members": serializable_chat_members},
            upsert=True
        )
    except Exception as e:
        print("Ошибка сохранения в MongoDB: " + str(e))


# ─── вспомогательные функции ──────────────────────────────────────────────────

def init_user(uid, name=None, chat_id=None):
    if uid not in user_data:
        user_data[uid] = {
            "race": None, "max_hp": 100, "hp": 100,
            "max_mp": 50,  "mp": 50,  "dexterity": 10,
            "combat_bonus": 0, "inventory": [],
            "last_loot_time": 0, "last_action_time": 0,
            "roll_buff": 0, "roll_buff_time": 0,
            "lucky_amulet": False,
            "wins": 0, "losses": 0, "pvp_wins": 0, "pvp_win_dates": [],
            "name": name or "Герой",
        }
        save_data()
    elif name:
        user_data[uid]["name"] = name
        save_data()
    # Регистрируем игрока в чате
    if chat_id and chat_id < 0:  # только группы (chat_id < 0)
        if chat_id not in chat_members:
            chat_members[chat_id] = set()
        chat_members[chat_id].add(uid)


def get_name(uid):
    """Возвращает имя игрока."""
    return user_data.get(uid, {}).get("name", "Герой")


def get_race_display(race_key):
    st = RACE_STATS[race_key]
    return st["emoji"] + " " + race_key


def make_bar(cur, max_v, emoji):
    """Полоса прогресса 8 блоков."""
    if max_v <= 0:
        return "░░░░░░░░"
    n = max(0, min(8, round((cur / max_v) * 8)))
    return emoji * n + "░" * (8 - n)

def hp_bar(cur, max_v):
    pct = cur / max_v if max_v > 0 else 0
    if pct > 0.5: block = "🟥"
    elif pct > 0.25: block = "🟧"
    else: block = "💀"
    n = max(0, min(8, round(pct * 8)))
    return block * n + "⬛" * (8 - n)

def mp_bar(cur, max_v):
    pct = cur / max_v if max_v > 0 else 0
    n = max(0, min(8, round(pct * 8)))
    return "🟦" * n + "⬛" * (8 - n)


def get_active_roll_buff(uid):
    p = user_data.get(uid)
    if p is None:
        return 0
    if time.time() - p["roll_buff_time"] < 300:
        return p["roll_buff"]
    return 0


def item_name(it_id):
    return ITEMS_DB.get(it_id, {}).get("name", "Предмет 📦")


def item_desc(it_id):
    return ITEMS_DB.get(it_id, {}).get("desc", "")



# ─── Хелперы для отправки с HTML-форматированием ─────────────────────────────
def _send(chat_id, text, **kwargs):
    kwargs.setdefault("parse_mode", "HTML")
    return _send(chat_id, text, **kwargs)

def _edit(chat_id, message_id, text, **kwargs):
    kwargs.setdefault("parse_mode", "HTML")
    return _edit_raw(text, chat_id=chat_id, message_id=message_id, **kwargs)

def back_to_menu_markup(page=0):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("◀️ Назад в меню", callback_data="mpage_" + str(page)))
    return markup


ANTISPAM_DELAY = 0.5  # глобальный кулдаун между любыми нажатиями одного юзера

def check_spam(uid, cb_data=None):
    """Возвращает True если это спам. Кулдаун per-uid (не per-кнопка)."""
    now = time.time()
    last = callback_spam.get(uid, 0)
    if now - last < ANTISPAM_DELAY:
        return True
    callback_spam[uid] = now
    return False


def _send_top10(chat_id, edit_msg=None):
    """Топ-10 игроков по pvp_wins — только для этой группы."""
    group_uids = chat_members.get(chat_id, set())
    if group_uids:
        players = [(uid, p) for uid, p in user_data.items() if uid in group_uids and p.get("race")]
        scope_label = "ЭТОЙ ГРУППЫ"
    else:
        # Личный чат — показываем всех (или только самого пользователя)
        players = [(uid, p) for uid, p in user_data.items() if p.get("race")]
        scope_label = "СЕРВЕРА"
    players.sort(key=lambda x: x[1].get("pvp_wins", 0), reverse=True)
    top = players[:10]
    if not top:
        text = "<b>🥇 ТОП ПУСТ</b>\n──────────────────\n\nНикто ещё не победил в PvP!"
    else:
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        lines = []
        for i, (uid, p) in enumerate(top):
            pvp_w = p.get("pvp_wins", 0)
            losses = p.get("losses", 0)
            total = pvp_w + losses
            wr = str(round(pvp_w / total * 100)) + "%" if total > 0 else "—"
            lines.append(
                medals[i] + " " + get_name(uid) + " — " + get_race_display(p["race"]) + "\n"
                "    🏅 " + str(pvp_w) + "  💀 " + str(losses) + "  📈 " + wr
            )
        text = "<b>🏆 ТОП-10 " + scope_label + "</b>\n──────────────────\n\n" + "\n\n".join(lines)
    if edit_msg:
        _edit(chat_id, edit_msg.message_id, text,
            reply_markup=back_to_menu_markup(0)
        )
    else:
        _send(chat_id, text)


# ─── Страничное меню ──────────────────────────────────────────────────────────
# Каждая страница — список (label, callback_data).
# Кнопки идут попарно, внизу стрелки навигации.

MENU_PAGES = [
    [   # Единственная страница — всё меню
        ("👤 Герой",              "menu_hero"),
        ("🎒 Инвентарь",          "menu_bag"),
        ("⚔️ Битва с монстром",   "menu_fight"),
        ("⚔️⚔️ Групповая битва",  "menu_brawl"),
        ("🎲 Кубик d20",           "menu_roll"),
        ("📦 Открыть сундук",      "menu_loot"),
        ("🎪 Случайное действие",  "menu_action"),
        ("🏆 Статистика",          "menu_stats"),
        ("🥇 Топ-10 группы",       "menu_top"),
        ("🎭 Сменить класс",       "menu_race"),
        ("📋 Все предметы",        "menu_items"),
    ],
]

PAGE_TITLES = [
    "🎮 Главное меню",
]


def menu_inline_page(page: int):
    page = max(0, min(page, len(MENU_PAGES) - 1))
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [InlineKeyboardButton(label, callback_data=cb) for label, cb in MENU_PAGES[page]]
    markup.add(*buttons)
    # Навигация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data="mpage_" + str(page - 1)))
    nav.append(InlineKeyboardButton(
        PAGE_TITLES[page] + "  " + str(page + 1) + "/" + str(len(MENU_PAGES)),
        callback_data="mpage_noop"
    ))
    if page < len(MENU_PAGES) - 1:
        nav.append(InlineKeyboardButton("▶️", callback_data="mpage_" + str(page + 1)))
    markup.row(*nav)
    return markup


def menu_header(uid):
    p = user_data[uid]
    if p["race"]:
        return (
            "<b>🎮 ГЛАВНОЕ МЕНЮ</b>\n"
            "──────────────────\n"
            "<b>" + get_race_display(p["race"]) + "</b>\n\n"
            "❤️ " + hp_bar(p["hp"], p["max_hp"]) + " <code>" + str(p["hp"]) + "/" + str(p["max_hp"]) + "</code>\n"
            "💙 " + mp_bar(p["mp"], p["max_mp"]) + " <code>" + str(p["mp"]) + "/" + str(p["max_mp"]) + "</code>\n\n"
            "🎒 <b>" + str(len(p["inventory"])) + "</b> пред.   🏆 <b>" + str(p.get("wins", 0)) + "</b> побед\n"
            "──────────────────\n"
            "Выбери действие:"
        )
    return "<b>🎮 ГЛАВНОЕ МЕНЮ</b>\n──────────────────\n\n⚠️ <b>Герой не создан!</b>\nВыбери класс → 🎭 <i>Сменить класс</i>\n\nВыбери действие:"


@bot.callback_query_handler(func=lambda call: call.data.startswith("mpage_"))
def handle_menu_page(call):
    uid = call.from_user.id
    init_user(uid, call.from_user.first_name, chat_id=call.message.chat.id)
    arg = call.data[6:]
    if arg == "noop":
        bot.answer_callback_query(call.id)
        return
    page = int(arg)
    _edit(call.message.chat.id, call.message.message_id, menu_header(uid),
        reply_markup=menu_inline_page(page)
    )
    bot.answer_callback_query(call.id)


# ─── /start и /help ───────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    uid = message.from_user.id
    init_user(uid, message.from_user.first_name, chat_id=message.chat.id)
    txt = (
        "<b>⚔️ ДОБРО ПОЖАЛОВАТЬ В АРЕНУ ⚔️</b>\n"
        "──────────────────────────\n\n"
        "Выбери класс и вступай в бой!\n\n"
        "<b>📜 КОМАНДЫ</b>\n"
        "┌ /race     — выбрать / сменить класс\n"
        "├ /fight    — битва с монстром (PvE)\n"
        "├ /pvp      — дуэль (ответом на сообщение)\n"
        "├ /brawl    — групповая битва до 10 игроков\n"
        "├ /loot     — сундук с добычей (кд 2 ч)\n"
        "├ /action   — случайное действие (кд 3 мин)\n"
        "├ /roll     — кубик d20\n"
        "├ /my_hero  — карточка героя\n"
        "├ /bag      — инвентарь\n"
        "├ /stats    — статистика\n"
        "├ /items    — все предметы\n"
        "└ /top      — топ-10 группы\n\n"
        "──────────────────────────\n"
        "Используй /race чтобы начать!"
    )
    _send(message.chat.id, txt, reply_markup=ReplyKeyboardRemove())


# ─── /items ───────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["items"])
def show_items_list(message):
    txt = "<b>📦 ВСЕ ПРЕДМЕТЫ</b>\n──────────────────\n\n"
    for it_id, info in ITEMS_DB.items():
        txt += info["name"] + "\n  └ " + info["desc"] + "\n\n"
    _send(message.chat.id, txt)


# ─── Обработка кнопок меню ────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_"))
def handle_menu_action(call):
    action = call.data[5:]
    uid = call.from_user.id
    init_user(uid, call.from_user.first_name, chat_id=call.message.chat.id)

    # Антиспам для кнопок меню
    if check_spam(uid):
        bot.answer_callback_query(call.id, "⚡ Вы уже нажали эту кнопку, подождите немного!", show_alert=False)
        return

    if action == "hero":
        _send_hero_info(call.message.chat.id, uid, edit_msg=call.message)

    elif action == "bag":
        _send_bag(call.message.chat.id, uid, edit_msg=call.message)

    elif action == "fight":
        p = user_data[uid]
        if p["race"] is None:
            bot.answer_callback_query(call.id, "Сначала выбери расу!")
            return
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("Физ. удар ⚔️",     callback_data="pvep"),
            InlineKeyboardButton("Магия (-15 MP) 🔮", callback_data="pvem")
        )
        _edit(call.message.chat.id, call.message.message_id, "<b>👹 МОНСТР ПОЯВИЛСЯ!</b>\n──────────────────\n\nВыбери тип атаки:",
            reply_markup=markup)

    elif action == "roll":
        _do_roll(call.message.chat.id, uid, edit_msg=call.message)

    elif action == "loot":
        _do_loot(call.message.chat.id, uid, edit_msg=call.message, call=call)
        return  # _do_loot answers callback internally

    elif action == "race":
        _show_race_selection(call.message.chat.id, uid, edit_msg=call.message)

    elif action == "action":
        _do_action_inline(call)
        return  # _do_action_inline answers callback internally

    elif action == "stats":
        _send_stats(call.message.chat.id, uid, edit_msg=call.message)

    elif action == "items":
        txt = "<b>📦 ВСЕ ПРЕДМЕТЫ</b>\n──────────────────\n\n"
        for it_id, info in ITEMS_DB.items():
            txt += info["name"] + "\n  └ " + info["desc"] + "\n\n"
        _edit(call.message.chat.id, call.message.message_id, txt,
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("◀️ Назад в меню", callback_data="mpage_0")
            )
        )

    elif action == "top":
        _send_top10(call.message.chat.id, edit_msg=call.message)

    elif action == "brawl":
        _start_brawl_menu(call)
        return  # _start_brawl_menu answers callback internally

    bot.answer_callback_query(call.id)


def _do_action_inline(call):
    uid = call.from_user.id
    p = user_data[uid]
    cur = time.time()
    if cur - p["last_action_time"] < 180:
        rem = int(180 - (cur - p["last_action_time"]))
        bot.answer_callback_query(call.id, "Жди " + str(rem) + " сек ⏱️", show_alert=True)
        return
    p["last_action_time"] = cur
    save_data()
    act = random.choice(FUNNY_ACTIONS)
    name = call.from_user.first_name
    _edit(call.message.chat.id, call.message.message_id, "<b>🎪 СЛУЧАЙНОЕ ДЕЙСТВИЕ</b>\n──────────────────\n\n", + name + " " + act,
        reply_markup=back_to_menu_markup(0)
    )


def _send_stats(chat_id, uid, edit_msg=None):
    import io
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime, timedelta
        HAS_MPL = True
    except ImportError:
        HAS_MPL = False

    p = user_data[uid]
    wins = p.get("wins", 0)
    losses = p.get("losses", 0)
    pvp_wins = p.get("pvp_wins", 0)
    pve_wins = wins - pvp_wins
    total_pvp = pvp_wins + losses
    ratio = str(round(pvp_wins / total_pvp * 100)) + "%" if total_pvp > 0 else "N/A"
    total = wins + losses
    text = (
        "<b>📊 СТАТИСТИКА</b>\n"
        "──────────────────\n"
        "👤 <b>" + get_name(uid) + "</b>\n\n"
        "🏅 PvP победы:   <b>" + str(pvp_wins) + "</b>\n"
        "👹 PvE победы:   <b>" + str(pve_wins) + "</b>\n"
        "💀 Поражения:    <b>" + str(losses) + "</b>\n"
        "⚔️  Всего боёв:   <b>" + str(total) + "</b>\n"
        "──────────────────\n"
        "📈 Винрейт (PvP): <b>" + ratio + "</b>"
    )

    # ── Отправляем текст ──────────────────────────────────────────────────────
    if edit_msg:
        _edit(chat_id, edit_msg.message_id, text,
            reply_markup=back_to_menu_markup(0)
        )
    else:
        _send(chat_id, text)

    # ── График побед над игроками (всегда отдельным сообщением) ───────────────
    if not HAS_MPL:
        return
    dates_raw = p.get("pvp_win_dates", [])
    if not dates_raw:
        return

    # Считаем победы по дням
    from collections import Counter
    counts = Counter(dates_raw)

    # Диапазон: от первой победы до сегодня
    today = datetime.today().date()
    first = datetime.strptime(min(counts.keys()), "%Y-%m-%d").date()
    all_days = []
    d = first
    while d <= today:
        all_days.append(d)
        d += timedelta(days=1)

    y_vals = [counts.get(str(day), 0) for day in all_days]
    x_vals = [datetime.combine(day, datetime.min.time()) for day in all_days]

    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor("#f5f5f5")
    ax.set_facecolor("#f5f5f5")

    ax.bar(x_vals, y_vals, color="#b5cc18", width=0.8, zorder=3)
    ax.set_title("Победы над игроками — " + get_name(uid), fontsize=13, color="#333333")
    ax.set_ylabel("Побед", fontsize=10, color="#555555")
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    plt.xticks(rotation=45, ha="right", fontsize=8, color="#555555")
    plt.yticks(fontsize=8, color="#555555")
    ax.grid(axis="y", color="#cccccc", linewidth=0.7, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120)
    buf.seek(0)
    plt.close(fig)

    bot.send_photo(chat_id, buf, caption="📊 График побед над игроками")

def _show_race_selection(chat_id, uid, edit_msg=None):
    p = user_data[uid]
    markup = InlineKeyboardMarkup()
    for i, race_key in enumerate(RACE_KEYS):
        st = RACE_STATS[race_key]
        label = (
            get_race_display(race_key) +
            "  HP:" + str(st["hp"]) +
            " MP:" + str(st["mp"]) +
            " DEX:" + str(st["dex"])
        )
        if p["race"] == race_key:
            label = "✅ " + label
        markup.add(InlineKeyboardButton(label, callback_data="r" + str(i)))
    markup.add(InlineKeyboardButton("◀️ Назад в меню", callback_data="mpage_0"))
    text = (
        "<b>🎭 ВЫБОР КЛАССА</b>\n──────────────────\n\n"
        + (
            "Текущий: " + get_race_display(p["race"]) + "\n"
            "<i>⚠️ При смене HP/MP сбросятся, инвентарь сохранится.</i>\n\n"
            if p["race"] else ""
        )
        + "Выбери класс:"
    )
    if edit_msg:
        _edit(chat_id, edit_msg.message_id, text, reply_markup=markup)
    else:
        _send(chat_id, text, reply_markup=markup)


@bot.message_handler(commands=["race"])
def choose_race_menu(message):
    uid = message.from_user.id
    init_user(uid)
    _show_race_selection(message.chat.id, uid)


@bot.callback_query_handler(func=lambda call: call.data.startswith("r") and call.data[1:].isdigit())
def handle_race_selection(call):
    uid = call.from_user.id
    init_user(uid, call.from_user.first_name, chat_id=call.message.chat.id)
    idx = int(call.data[1:])
    if idx >= len(RACE_KEYS):
        return
    race = RACE_KEYS[idx]
    p = user_data[uid]
    old_race = p["race"]
    st = RACE_STATS[race]
    p["race"] = race
    p["max_hp"] = st["hp"]
    p["hp"] = st["hp"]
    p["max_mp"] = st["mp"]
    p["mp"] = st["mp"]
    p["dexterity"] = st["dex"]
    save_data()
    display = get_race_display(race)
    if old_race is None:
        log = (
            "<b>✅ ГЕРОЙ СОЗДАН!</b>\n"
            "──────────────────\n\n"
            "<b>" + display + "</b>\n\n"
            "❤️ HP:       <b>" + str(st["hp"]) + "</b>\n"
            "💙 MP:       <b>" + str(st["mp"]) + "</b>\n"
            "⚡ Ловкость: <b>" + str(st["dex"]) + "</b>\n\n"
            "──────────────────\n"
            "Нажми ⚔️ <i>Битва с монстром</i> чтобы начать!"
        )
    else:
        log = (
            "<b>🔄 КЛАСС ИЗМЕНЁН</b>\n"
            "──────────────────\n\n"
            "Было:  " + get_race_display(old_race) + "\n"
            "Стало: <b>" + display + "</b>\n\n"
            "❤️ HP:       <b>" + str(st["hp"]) + "</b>\n"
            "💙 MP:       <b>" + str(st["mp"]) + "</b>\n"
            "⚡ Ловкость: <b>" + str(st["dex"]) + "</b>\n\n"
            "──────────────────\n"
            "<i>Инвентарь и бонусы сохранены.</i>"
        )
    _edit(call.message.chat.id, call.message.message_id, log,
        reply_markup=back_to_menu_markup(0)
    )


# ─── Вспомогательные функции ──────────────────────────────────────────────────

def _send_hero_info(chat_id, uid, edit_msg=None):
    p = user_data[uid]
    if p["race"] is None:
        text = "У тебя ещё нет героя. Выбери класс через меню или /race"
        if edit_msg:
            _edit(chat_id, edit_msg.message_id, text,
                reply_markup=back_to_menu_markup(0)
            )
        else:
            _send(chat_id, text)
        return
    rb = get_active_roll_buff(uid)
    b_txt = ""
    if rb > 0:
        b_txt = "  🔥 бафф +" + str(rb)
    elif rb < 0:
        b_txt = "  💀 дебафф " + str(rb)
    lucky = "\n🍀 Амулет удачи активен!" if p.get("lucky_amulet") else ""
    msg = (
        "<b>👤 КАРТОЧКА ГЕРОЯ</b>\n"
        "──────────────────\n"
        "<b>" + get_race_display(p["race"]) + "</b>\n\n"
        "❤️ " + hp_bar(p["hp"], p["max_hp"]) + " <code>" + str(p["hp"]) + "/" + str(p["max_hp"]) + "</code>\n"
        "💙 " + mp_bar(p["mp"], p["max_mp"]) + " <code>" + str(p["mp"]) + "/" + str(p["max_mp"]) + "</code>\n\n"
        "⚡ Ловкость:    <b>" + str(p["dexterity"]) + "</b>\n"
        "⚔️  Боев. бонус: <b>+" + str(p["combat_bonus"]) + "</b>" + b_txt + "\n"
        "🎒 Предметов:   <b>" + str(len(p["inventory"])) + "</b>" + lucky + "\n\n"
        "──────────────────\n"
        "🏆 Победы:    <b>" + str(p.get("wins", 0)) + "</b>\n"
        "💀 Поражения: <b>" + str(p.get("losses", 0)) + "</b>"
    )
    if edit_msg:
        _edit(chat_id, edit_msg.message_id, msg,
            reply_markup=back_to_menu_markup(0)
        )
    else:
        _send(chat_id, msg)


def _send_bag(chat_id, uid, edit_msg=None):
    inv = user_data[uid]["inventory"]
    if not inv:
        text = "🎒 Инвентарь пуст. Открой сундук через меню или /loot"
        if edit_msg:
            _edit(chat_id, edit_msg.message_id, text,
                reply_markup=back_to_menu_markup(0)
            )
        else:
            _send(chat_id, text)
        return
    counts = {}
    for it in inv:
        counts[it] = counts.get(it, 0) + 1
    markup = InlineKeyboardMarkup()
    for it_id, count in counts.items():
        label = item_name(it_id) + " x" + str(count)
        markup.add(InlineKeyboardButton(label, callback_data="use" + it_id))
    markup.add(InlineKeyboardButton("◀️ Назад в меню", callback_data="mpage_0"))
    bag_text = (
        "<b>🎒 ИНВЕНТАРЬ</b>\n"
        "──────────────────\n"
        "👤 <b>" + get_name(uid) + "</b>\n"
        "📦 " + str(len(inv)) + " предм.  •  <i>Нажми — использовать</i>"
    )
    if edit_msg:
        _edit(chat_id, edit_msg.message_id, bag_text,
            reply_markup=markup)
    else:
        _send(chat_id, bag_text, reply_markup=markup)


def _do_roll(chat_id, uid, edit_msg=None):
    p = user_data[uid]
    if p.get("lucky_amulet"):
        res = random.randint(15, 20)
        p["lucky_amulet"] = False
        amulet_txt = "🍀 Амулет удачи сработал!\n"
    else:
        res = random.randint(1, 20)
        amulet_txt = ""
    if res == 20:
        b, st = 6,  "💥 КРИТ УСПЕХ! Мощный бафф!"
    elif res >= 15:
        b, st = 4,  "✨ Отличный бросок! Боевой дух!"
    elif res >= 6:
        b, st = 2,  "👍 Нормальный бросок. Чуть силы."
    else:
        b, st = -2, "💀 КРИТ НЕУДАЧА! Дебафф!"
    p["roll_buff"] = b
    p["roll_buff_time"] = time.time()
    save_data()
    sign = "+" if b >= 0 else ""
    log = (
        amulet_txt +
        "<b>🎲 БРОСОК КУБИКА d20</b>\n"
        "──────────────────\n\n"
        "Результат: <b>" + str(res) + " / 20</b>\n\n"
        + st + "\n\n"
        "<i>Модификатор " + sign + str(b) + " действует 5 минут.</i>"
    )
    if edit_msg:
        _edit(chat_id, edit_msg.message_id, log,
            reply_markup=back_to_menu_markup(0)
        )
    else:
        _send(chat_id, log)


def _do_loot(chat_id, uid, edit_msg=None, call=None):
    cur = time.time()
    last = user_data[uid]["last_loot_time"]
    if cur - last < 7200:
        rem = int(7200 - (cur - last))
        cd_text = "⏱️ Сундук закрыт! Жди " + str(rem // 3600) + "ч " + str((rem % 3600) // 60) + "м"
        if call:
            bot.answer_callback_query(call.id, cd_text, show_alert=True)
        elif edit_msg:
            _edit(chat_id, edit_msg.message_id, cd_text,
                reply_markup=back_to_menu_markup(0)
            )
        else:
            _send(chat_id, cd_text)
        return
    l_id = random.choice(ITEM_KEYS)
    user_data[uid]["inventory"].append(l_id)
    user_data[uid]["last_loot_time"] = cur
    save_data()
    text = (
        "<b>📦 СУНДУК ОТКРЫТ!</b>\n"
        "──────────────────\n\n"
        "👤 <b>" + get_name(uid) + "</b> нашёл:\n\n"
        "✨ <b>" + item_name(l_id) + "</b>\n"
        "   <i>" + item_desc(l_id) + "</i>\n\n"
        "Предмет в инвентаре 🎒"
    )
    if edit_msg:
        _edit(chat_id, edit_msg.message_id, text,
            reply_markup=back_to_menu_markup(0)
        )
    else:
        _send(chat_id, text)


# ─── /my_hero, /bag, /stats ───────────────────────────────────────────────────

@bot.message_handler(commands=["my_hero"])
def check_hero(message):
    uid = message.from_user.id
    init_user(uid, message.from_user.first_name, chat_id=message.chat.id)
    _send_hero_info(message.chat.id, uid)

@bot.message_handler(commands=["bag"])
def check_bag(message):
    uid = message.from_user.id
    init_user(uid, message.from_user.first_name, chat_id=message.chat.id)
    _send_bag(message.chat.id, uid)

@bot.message_handler(commands=["stats"])
def check_stats(message):
    uid = message.from_user.id
    init_user(uid, message.from_user.first_name, chat_id=message.chat.id)
    _send_stats(message.chat.id, uid)


@bot.message_handler(commands=["top"])
def show_top(message):
    _send_top10(message.chat.id)


# ─── Использование предметов ──────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: call.data.startswith("use"))
def handle_item_use(call):
    uid = call.from_user.id
    init_user(uid, call.from_user.first_name, chat_id=call.message.chat.id)
    p = user_data[uid]
    it_id = call.data[3:]
    if it_id not in p["inventory"]:
        bot.answer_callback_query(call.id, "Предмет не найден.")
        return
    p["inventory"].remove(it_id)
    name = item_name(it_id)
    f_name = get_name(uid)
    log = "<b>🎒 ИСПОЛЬЗОВАНИЕ ПРЕДМЕТА</b>\n──────────────────\n👤 <b>" + f_name + "</b>\n✨ <b>" + name + "</b>\n\n"

    if it_id == "juice":
        p["hp"] = p["max_hp"]
        p["mp"] = p["max_mp"]
        log += "Выпит до дна! HP и MP полностью восстановлены. 🥤"

    elif it_id == "potion":
        if random.choice([True, False]):
            heal = 30
            p["hp"] = min(p["max_hp"], p["hp"] + heal)
            log += "Целебное зелье! +" + str(heal) + " HP. 🧪"
        else:
            p["hp"] = max(10, p["hp"] - 20)
            log += "Ядовитое зелье! -20 HP. 🤢"

    elif it_id == "sword":
        p["combat_bonus"] += 3
        log += "Меч заточен (кое-как). Боевой бонус +3. 🗡️"

    elif it_id == "shield":
        p["max_hp"] += 20
        p["hp"] = min(p["hp"] + 20, p["max_hp"])
        log += "Щит надет. Макс. HP +20. 🛡️"

    elif it_id == "crown":
        p["combat_bonus"] += 5
        log += "Корона Ютуки надета. Боевой бонус +5. 👑"

    elif it_id == "boots":
        p["dexterity"] += 3
        log += "Сапоги надеты. Ловкость +3. 👞"

    elif it_id == "tome":
        p["max_mp"] += 20
        p["mp"] = min(p["mp"] + 20, p["max_mp"])
        log += "Том прочитан. Макс. MP +20. 📖"

    elif it_id == "amulet":
        p["lucky_amulet"] = True
        log += "Амулет активирован! Следующий d20 = 15+. 🍀"

    elif it_id == "fishrod":
        # Удочка ловит случайный предмет
        caught = random.choice(ITEM_KEYS)
        p["inventory"].append(caught)
        log += "Закинул удочку... поймал: " + item_name(caught) + "! 🎣"

    elif it_id == "cactus":
        p["dexterity"] += 2
        p["hp"] = max(10, p["hp"] - 5)
        log += "Кактус экипирован. Ловкость +2, но -5 HP (иголки...) 🌵"

    elif it_id == "cheese":
        p["hp"] = p["max_hp"]
        p["mp"] = max(0, p["mp"] - 10)
        log += "Сыр съеден. HP полностью восстановлено, но -10 MP. 🧀"

    else:
        log += "Предмет использован... и ничего не произошло."

    log += (
        "\n\n──────────────────\n"
        "❤️ " + hp_bar(p["hp"], p["max_hp"]) + "  " + str(p["hp"]) + "/" + str(p["max_hp"]) + "\n"
        "💙 " + mp_bar(p["mp"], p["max_mp"]) + "  " + str(p["mp"]) + "/" + str(p["max_mp"])
    )
    save_data()
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🎒 Назад в инвентарь", callback_data="menu_bag"))
    markup.add(InlineKeyboardButton("◀️ В меню", callback_data="mpage_0"))
    _edit(call.message.chat.id, call.message.message_id, log,
        reply_markup=markup)


# ─── /fight ───────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["fight"])
def start_fight(message):
    uid = message.from_user.id
    init_user(uid, message.from_user.first_name, chat_id=message.chat.id)
    if user_data[uid]["race"] is None:
        _send(message.chat.id, "Сначала создай персонажа через /race")
        return
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Физ. удар ⚔️",     callback_data="pvep"),
        InlineKeyboardButton("Магия (-15 MP) 🔮", callback_data="pvem")
    )
    _send(message.chat.id, "👹 МОНСТР ПОЯВИЛСЯ!\n──────────────────\n\nВыбери тип атаки:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data in ["pvep", "pvem"])
def handle_pve(call):
    uid = call.from_user.id
    init_user(uid, call.from_user.first_name, chat_id=call.message.chat.id)

    if check_spam(uid):
        bot.answer_callback_query(call.id, "⚡ Вы уже нажали эту кнопку, подождите немного!")
        return

    p = user_data[uid]
    if p["race"] is None:
        bot.answer_callback_query(call.id, "Сначала выбери расу!")
        return

    m_name = random.choice(list(MONSTERS_DB.keys()))
    m_info = MONSTERS_DB[m_name]
    pname = get_name(uid)
    event = random.choice(BATTLE_EVENTS)

    # Инициализируем HP монстра (примерно как у игрока)
    monster_hp = random.randint(60, 120)
    monster_max_hp = monster_hp
    player_hp = p["hp"]
    total_bonus = p["combat_bonus"] + get_active_roll_buff(uid)

    log = (
        "<b>⚔️ БОЙ С МОНСТРОМ</b>\n"
        "──────────────────\n"
        "⚔️  <b>" + pname + "</b> [" + get_race_display(p["race"]) + "]\n"
        "👹  <b>" + m_name + "</b> — <i>" + m_info["desc"] + "</i>\n"
    )
    if event:
        log += "🎲 <i>" + event + "</i>\n"
    log += "──────────────────\n\n"

    MAX_ROUNDS = random.randint(1, 3)
    winner = None

    for rnd in range(1, MAX_ROUNDS + 1):
        p_dice = random.randint(1, 20)
        e_dice = random.randint(1, 20)

        if call.data == "pvep" or p["mp"] < 15:
            p_score = p_dice + p["dexterity"] + total_bonus
            atk_desc = RACE_COMBAT[p["race"]]["phys"]
            score_str = str(p_dice) + "+" + str(p["dexterity"]) + "+" + str(total_bonus)
        else:
            p["mp"] -= 15
            p_score = p_dice + 15 + total_bonus
            atk_desc = RACE_COMBAT[p["race"]]["magic"]
            score_str = str(p_dice) + "+15+" + str(total_bonus)

        e_score = e_dice + m_info["bonus"]

        log += "[ Раунд " + str(rnd) + " ]\n"
        log += pname + " " + atk_desc + " [" + score_str + " = " + str(p_score) + "]\n"
        log += m_name + " атакует [" + str(e_dice) + "+" + str(m_info["bonus"]) + " = " + str(e_score) + "]\n"

        if p_score > e_score:
            dmg_to_monster = random.randint(10, 25)
            monster_hp = max(0, monster_hp - dmg_to_monster)
            log += "💥 " + pname + " наносит -" + str(dmg_to_monster) + " монстру (HP монстра: " + str(monster_hp) + "/" + str(monster_max_hp) + ")\n"
        elif e_score > p_score:
            dmg_to_player = random.randint(8, 20)
            player_hp = max(10, player_hp - dmg_to_player)
            log += "💀 Монстр наносит -" + str(dmg_to_player) + " игроку (HP: " + str(player_hp) + "/" + str(p["max_hp"]) + ")\n"
        else:
            log += "🤝 Ничья в раунде!\n"

        if monster_hp <= 0:
            winner = "player"
            break
        if player_hp <= p["max_hp"] * 0.1:  # игрок почти мёртв
            winner = "monster"
            break

        log += "\n"

    # Применяем итоговый HP
    p["hp"] = player_hp

    log += "\n──────────────────\n"
    if winner == "player" or (winner is None and monster_hp < monster_max_hp // 2):
        # Победил игрок (или нанёс больше урона за 6 раундов)
        if winner is None:
            log += "🏆 " + pname + " продержался все " + str(MAX_ROUNDS) + " раундов и победил по очкам!\n"
        else:
            log += "🏆 " + pname + " победил! Монстр повержен!\n"
        p["wins"] = p.get("wins", 0) + 1
        if random.random() < DROP_CHANCE:
            drop_id = random.choice(ITEM_KEYS)
            p["inventory"].append(drop_id)
            log += "\n🎁 Трофей: " + item_name(drop_id) + "\n   └ " + item_desc(drop_id) + "\n"
    else:
        log += "💀 " + pname + " проиграл после " + str(rnd) + " раундов!\n"
        p["losses"] = p.get("losses", 0) + 1

    log += (
        "\n" + "❤️ " + hp_bar(p["hp"], p["max_hp"]) + "  " + str(p["hp"]) + "/" + str(p["max_hp"]) + "\n"
        "💙 " + mp_bar(p["mp"], p["max_mp"]) + "  " + str(p["mp"]) + "/" + str(p["max_mp"])
    )

    save_data()
    _edit(call.message.chat.id, call.message.message_id, log,
        reply_markup=back_to_menu_markup(0)
    )
    bot.answer_callback_query(call.id)


# ─── /pvp — дуэль 1 на 1 ─────────────────────────────────────────────────────

@bot.message_handler(commands=["pvp"])
def start_pvp(message):
    atk_id = message.from_user.id
    init_user(atk_id, message.from_user.first_name, chat_id=message.chat.id)
    if not message.reply_to_message:
        bot.reply_to(message, "Пиши /pvp в ответ на сообщение игрока!")
        return
    def_id = message.reply_to_message.from_user.id
    init_user(def_id, message.reply_to_message.from_user.first_name, chat_id=message.chat.id)
    if atk_id == def_id:
        bot.reply_to(message, "Нельзя драться с собой!")
        return
    if user_data[atk_id]["race"] is None or user_data[def_id]["race"] is None:
        bot.reply_to(message, "У обоих игроков должны быть расы!")
        return
    b_id = str(atk_id) + "X" + str(def_id)
    active_pvp[b_id] = {"attacker": atk_id, "defender": def_id, "phase": "challenge"}
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Физ. защита ⚔️", callback_data="duelp" + b_id),
        InlineKeyboardButton("Маг. защита 🔮",  callback_data="duelm" + b_id)
    )
    markup.add(
        InlineKeyboardButton("❌ Отклонить вызов", callback_data="dueld" + b_id),
        InlineKeyboardButton("🏳️ Отозвать вызов",  callback_data="duels" + b_id))
    def_name = message.reply_to_message.from_user.first_name
    atk_name = message.from_user.first_name
    _send(
        message.chat.id,
        (
            "<b>⚔️ ВЫЗОВ НА ДУЭЛЬ</b>\n"
            "──────────────────\n\n"
            "⚡ <b>" + atk_name + "</b> вызывает <b>" + def_name + "</b>!\n\n"
            + def_name + ": выбери тип защиты.\n"
            + atk_name + ": можешь отозвать вызов."
        ),
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("duelp") or call.data.startswith("duelm") or call.data.startswith("dueld") or call.data.startswith("duels"))
def handle_pvp_battle(call):
    prefix = call.data[:5]
    b_id = call.data[5:]
    uid = call.from_user.id

    if check_spam(uid):
        bot.answer_callback_query(call.id, "⚡ Вы уже нажали эту кнопку, подождите немного!")
        return
    if b_id not in active_pvp:
        bot.answer_callback_query(call.id, "Дуэль уже завершена или не найдена.")
        return

    duel = active_pvp[b_id]
    atk_id = duel["attacker"]
    def_id = duel["defender"]

    # ── Отклонить вызов (защищающийся) ───────────────────────────────────────
    if prefix == "dueld":
        if uid != def_id:
            bot.answer_callback_query(call.id, "Только вызванный игрок может отклонить!", show_alert=True)
            return
        del active_pvp[b_id]
        n_atk = get_name(atk_id)
        n_def = get_name(def_id)
        _edit(call.message.chat.id, call.message.message_id, "<b>❌ ДУЭЛЬ ОТКЛОНЕНА</b>\n──────────────────\n\n", + n_def + " отклонил вызов " + n_atk + ".",
            reply_markup=back_to_menu_markup(0)
        )
        bot.answer_callback_query(call.id, "Вызов отклонён.")
        return

    # ── Отозвать / Сдаться (duels) ────────────────────────────────────────────
    if prefix == "duels":
        phase = duel.get("phase", "challenge")
        if phase == "challenge":
            # Отозвать вызов — только атакующий
            if uid != atk_id:
                bot.answer_callback_query(call.id, "Только атакующий может отозвать вызов!", show_alert=True)
                return
            del active_pvp[b_id]
            _edit(call.message.chat.id, call.message.message_id, "<b>🏳️ ВЫЗОВ ОТОЗВАН</b>\n──────────────────\n\n", + get_name(atk_id) + " отозвал вызов.",
                reply_markup=back_to_menu_markup(0)
            )
            bot.answer_callback_query(call.id, "Вызов отозван.")
        else:
            # Сдаться во время боя — любой участник
            if uid not in (atk_id, def_id):
                bot.answer_callback_query(call.id, "Ты не участник этой дуэли!", show_alert=True)
                return
            loser_id  = uid
            winner_id = def_id if uid == atk_id else atk_id
            p_loser   = user_data[loser_id]
            p_winner  = user_data[winner_id]
            dmg = random.randint(20, 40)
            p_loser["hp"]       = max(10, p_loser["hp"] - dmg)
            p_loser["losses"]   = p_loser.get("losses", 0) + 1
            p_winner["wins"]    = p_winner.get("wins", 0) + 1
            p_winner["pvp_wins"]= p_winner.get("pvp_wins", 0) + 1
            p_winner.setdefault("pvp_win_dates", []).append(time.strftime("%Y-%m-%d"))
            del active_pvp[b_id]
            save_data()
            _edit(call.message.chat.id, call.message.message_id,
                    "<b>🏳️ СДАЧА</b>\n"
                    "──────────────────\n\n"
                    + get_name(loser_id) + " сдался!\n\n"
                    "🏆 Победитель: " + get_name(winner_id) + "\n\n"
                    "💀 " + get_name(loser_id) + " —" + str(dmg) + " HP за трусость\n"
                    "❤️ " + hp_bar(p_loser["hp"], p_loser["max_hp"]) + "  " + str(p_loser["hp"]) + "/" + str(p_loser["max_hp"]),
                    reply_markup=back_to_menu_markup(0)
            )
            bot.answer_callback_query(call.id, "Ты сдался.")
        return

    # ── Принять вызов (физ / маг) и сыграть 3 раунда ─────────────────────────
    # prefix: "duelp" = физ, "duelm" = маг
    mode = prefix[4]   # 'p' или 'm'
    if uid != def_id:
        bot.answer_callback_query(call.id, "Это не твоя дуэль!")
        return

    # Переводим дуэль в фазу боя
    duel["phase"] = "fighting"

    p1 = user_data[atk_id]
    p2 = user_data[def_id]
    n1 = get_name(atk_id)
    n2 = get_name(def_id)
    b1 = p1["combat_bonus"] + get_active_roll_buff(atk_id)
    b2 = p2["combat_bonus"] + get_active_roll_buff(def_id)

    # ── 3 раунда (лучший из 3) ────────────────────────────────────────────────
    wins1 = 0
    wins2 = 0
    rounds_log = []

    for rnd in range(1, 4):
        d1 = random.randint(1, 20)
        d2 = random.randint(1, 20)

        if random.choice([True, False]) and p1["mp"] >= 15:
            p1["mp"] -= 15
            s1 = d1 + 15 + b1
            txt1 = "магией 🔮"
        else:
            s1 = d1 + p1["dexterity"] + b1
            txt1 = "физой ⚔️"

        if mode == "m" and p2["mp"] >= 15:
            p2["mp"] -= 15
            s2 = d2 + 15 + b2
            txt2 = "магией 🔮"
        else:
            s2 = d2 + p2["dexterity"] + b2
            txt2 = "физой ⚔️"

        rline = "[ Раунд " + str(rnd) + " ]\n"
        rline += "  ⚔️ " + n1 + " " + txt1 + " → " + str(s1) + "\n"
        rline += "  🛡️ " + n2 + " " + txt2 + " → " + str(s2) + "\n"

        if s1 > s2:
            wins1 += 1
            rline += "  ✅ " + n1 + " берёт раунд!"
        elif s2 > s1:
            wins2 += 1
            rline += "  ✅ " + n2 + " берёт раунд!"
        else:
            rline += "  🤝 Раунд — ничья"

        rounds_log.append(rline)

    # ── Итог дуэли ────────────────────────────────────────────────────────────
    log = (
        "<b>⚔️ ДУЭЛЬ</b>\n"
        "──────────────────\n"
        "⚡ <b>" + n1 + "</b> [" + get_race_display(p1["race"]) + "]\n"
        "⚡ <b>" + n2 + "</b> [" + get_race_display(p2["race"]) + "]\n"
        "──────────────────\n\n"
        + "\n".join(rounds_log) + "\n\n"
        "──────────────────\n"
        "Счёт: <b>" + str(wins1) + " : " + str(wins2) + "</b>\n\n"
    )

    if wins1 > wins2:
        dmg = random.randint(20, 40)
        p2["hp"] = max(10, p2["hp"] - dmg)
        p1["wins"] = p1.get("wins", 0) + 1
        p1["pvp_wins"] = p1.get("pvp_wins", 0) + 1
        p1.setdefault("pvp_win_dates", []).append(time.strftime("%Y-%m-%d"))
        p2["losses"] = p2.get("losses", 0) + 1
        log += "🏆 Победитель: " + n1 + "!\n💀 " + n2 + " —" + str(dmg) + " HP\n❤️ " + hp_bar(p2["hp"], p2["max_hp"]) + " " + str(p2["hp"]) + "/" + str(p2["max_hp"])
    elif wins2 > wins1:
        dmg = random.randint(20, 40)
        p1["hp"] = max(10, p1["hp"] - dmg)
        p2["wins"] = p2.get("wins", 0) + 1
        p2["pvp_wins"] = p2.get("pvp_wins", 0) + 1
        p2.setdefault("pvp_win_dates", []).append(time.strftime("%Y-%m-%d"))
        p1["losses"] = p1.get("losses", 0) + 1
        log += "🏆 Победитель: " + n2 + "!\n💀 " + n1 + " —" + str(dmg) + " HP\n❤️ " + hp_bar(p1["hp"], p1["max_hp"]) + " " + str(p1["hp"]) + "/" + str(p1["max_hp"])
    else:
        log += "🤝 НИЧЬЯ! " + n1 + " и " + n2 + " разошлись по домам."

    del active_pvp[b_id]
    save_data()
    _edit(call.message.chat.id, call.message.message_id, log,
        reply_markup=back_to_menu_markup(0)
    )
    bot.answer_callback_query(call.id)


# ─── /brawl — групповая битва (до 4 игроков) ─────────────────────────────────
#
# Логика:
#   1. /brawl — создаёт лобби, кнопка "Присоединиться"
#   2. Игроки жмут кнопку (до 4 человек)
#   3. Создатель жмёт "Начать бой" (минимум 2 игрока)
#   4. Каждый выбирает атаку, бой считается когда все ответили
#   5. Победитель — кто набрал больший счёт

def _start_brawl_menu(call):
    uid = call.from_user.id
    p = user_data[uid]
    if p["race"] is None:
        bot.answer_callback_query(call.id, "Сначала выбери расу!", show_alert=True)
        return
    brawl_id = "B" + str(uid)
    if brawl_id in active_brawl:
        bot.answer_callback_query(call.id, "У тебя уже есть активная битва! Сначала отмени её.", show_alert=True)
        return
    active_brawl[brawl_id] = {
        "owner": uid,
        "players": [uid],
        "phase": "lobby",   # lobby / choosing / done
        "choices": {},
        "chat_id": call.message.chat.id,
        "msg_id": None,
    }
    markup = _brawl_lobby_markup(brawl_id)
    name = call.from_user.first_name
    sent = _send(
        call.message.chat.id,
        (
            "<b>⚔️ ГРУППОВАЯ БИТВА</b>\n"
            "──────────────────\n\n"
            "👑 Организатор: <b>" + name + "</b>\n"
            "👥 Игроков: <b>1/10</b>\n\n"
            "<i>Жди, пока другие присоединятся!</i>"
        ),
        reply_markup=markup
    )
    active_brawl[brawl_id]["msg_id"] = sent.message_id
    bot.answer_callback_query(call.id)


def _brawl_lobby_markup(brawl_id):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("➕ Присоединиться", callback_data="brawl_join_" + brawl_id),
        InlineKeyboardButton("⚔️ Начать бой!",    callback_data="brawl_start_" + brawl_id))
    markup.add(
        InlineKeyboardButton("❌ Отменить битву", callback_data="brawl_cancel_" + brawl_id))
    return markup


@bot.message_handler(commands=["brawl"])
def start_brawl_cmd(message):
    uid = message.from_user.id
    init_user(uid, message.from_user.first_name, chat_id=message.chat.id)
    p = user_data[uid]
    if p["race"] is None:
        _send(message.chat.id, "Сначала выбери расу через /race")
        return
    brawl_id = "B" + str(uid)
    if brawl_id in active_brawl:
        _send(message.chat.id, "⚠️ У тебя уже есть активная групповая битва! Сначала отмени её.")
        return
    active_brawl[brawl_id] = {
        "owner": uid,
        "players": [uid],
        "phase": "lobby",
        "choices": {},
        "chat_id": message.chat.id,
        "msg_id": None,
    }
    markup = _brawl_lobby_markup(brawl_id)
    name = message.from_user.first_name
    sent = _send(
        message.chat.id,
        (
            "⚔️ ГРУППОВАЯ БИТВА\n"
            "──────────────────\n\n"
            "👑 Организатор: " + name + "\n"
            "👥 Игроков: 1/10\n\n"
            "Жди, пока другие присоединятся!"
        ),
        reply_markup=markup
    )
    active_brawl[brawl_id]["msg_id"] = sent.message_id


@bot.callback_query_handler(func=lambda call: call.data.startswith("brawl_"))
def handle_brawl(call):
    parts = call.data.split("_", 2)
    # parts = ["brawl", action, brawl_id]
    if len(parts) < 3:
        return
    action   = parts[1]
    brawl_id = parts[2]
    uid      = call.from_user.id
    init_user(uid, call.from_user.first_name, chat_id=call.message.chat.id)

    if brawl_id not in active_brawl:
        bot.answer_callback_query(call.id, "Битва не найдена или уже завершена.")
        return

    brawl = active_brawl[brawl_id]

    # ── отменить битву (только организатор, фаза lobby) ──────────────────────
    if action == "cancel":
        if uid != brawl["owner"]:
            bot.answer_callback_query(call.id, "Только организатор может отменить битву!", show_alert=True)
            return
        if brawl["phase"] != "lobby":
            bot.answer_callback_query(call.id, "Битву нельзя отменить — она уже идёт!", show_alert=True)
            return
        del active_brawl[brawl_id]
        _edit(brawl["chat_id"], brawl["msg_id"], "❌ Групповая битва отменена организатором.",
            reply_markup=back_to_menu_markup(0)
        )
        bot.answer_callback_query(call.id, "Битва отменена.")
        return

    # ── присоединиться ────────────────────────────────────────────────────────
    if action == "join":
        if brawl["phase"] != "lobby":
            bot.answer_callback_query(call.id, "Битва уже идёт!", show_alert=True)
            return
        if uid in brawl["players"]:
            bot.answer_callback_query(call.id, "Ты уже в битве!")
            return
        if user_data[uid]["race"] is None:
            bot.answer_callback_query(call.id, "Сначала выбери расу /race", show_alert=True)
            return
        if len(brawl["players"]) >= 10:
            bot.answer_callback_query(call.id, "Лобби полное! Максимум 10 игроков.", show_alert=True)
            return
        brawl["players"].append(uid)
        # Обновляем сообщение лобби
        lines = []
        for pid in brawl["players"]:
            p = user_data[pid]
            lines.append(get_name(pid) + " — " + get_race_display(p["race"]))
        text = (
            "<b>⚔️ ГРУППОВАЯ БИТВА</b>\n"
            "──────────────────\n\n"
            "👥 Игроков: <b>" + str(len(brawl["players"])) + "/10</b>\n\n"
            + "\n".join(lines) +
            "\n\n──────────────────\n"
            "<i>Жди, пока организатор начнёт бой!</i>"
        )
        _edit(brawl["chat_id"], brawl["msg_id"], text,
            reply_markup=_brawl_lobby_markup(brawl_id)
        )
        bot.answer_callback_query(call.id, "Ты в битве!")

    # ── начать бой ────────────────────────────────────────────────────────────
    elif action == "start":
        if uid != brawl["owner"]:
            bot.answer_callback_query(call.id, "Только организатор может начать бой!", show_alert=True)
            return
        if len(brawl["players"]) < 2:
            bot.answer_callback_query(call.id, "Нужно минимум 2 игрока!", show_alert=True)
            return
        brawl["phase"] = "choosing"
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("Физ. удар ⚔️",     callback_data="brawl_phys_" + brawl_id),
            InlineKeyboardButton("Магия (-15 MP) 🔮", callback_data="brawl_magic_" + brawl_id))
        names = [get_name(pid) + " — " + get_race_display(user_data[pid]["race"]) for pid in brawl["players"]]
        text = (
            "<b>⚔️ БИТВА НАЧИНАЕТСЯ!</b>\n"
            "──────────────────\n\n"
            "<b>Участники:</b>\n" + "\n".join(names) +
            "\n\n──────────────────\n"
            "Каждый выбирает свою атаку:"
        )
        _edit(brawl["chat_id"], brawl["msg_id"], text,
            reply_markup=markup)
        bot.answer_callback_query(call.id)

    # ── выбор атаки ───────────────────────────────────────────────────────────
    elif action in ["phys", "magic"]:
        if brawl["phase"] != "choosing":
            bot.answer_callback_query(call.id, "Сейчас не фаза выбора.")
            return
        if uid not in brawl["players"]:
            bot.answer_callback_query(call.id, "Ты не в этой битве!")
            return
        if uid in brawl["choices"]:
            bot.answer_callback_query(call.id, "Ты уже выбрал!")
            return
        brawl["choices"][uid] = action
        waited = len(brawl["players"]) - len(brawl["choices"])
        pname = get_name(uid)
        if waited > 0:
            bot.answer_callback_query(call.id, pname + " выбрал! Ждём ещё " + str(waited) + " игроков.")
        else:
            bot.answer_callback_query(call.id, pname + " выбрал! Считаем результат...")
        # Когда все выбрали — считаем результат
        if len(brawl["choices"]) == len(brawl["players"]):
            _resolve_brawl(brawl_id)


def _resolve_brawl(brawl_id):
    brawl = active_brawl[brawl_id]
    chat_id = brawl["chat_id"]
    msg_id  = brawl["msg_id"]
    scores = {}
    details = []
    for uid in brawl["players"]:
        p = user_data[uid]
        choice = brawl["choices"][uid]
        dice = random.randint(1, 20)
        bonus = p["combat_bonus"] + get_active_roll_buff(uid)
        if choice == "magic" and p["mp"] >= 15:
            p["mp"] -= 15
            score = dice + 15 + bonus
            atk_type = "магией"
        else:
            score = dice + p["dexterity"] + bonus
            atk_type = "физой"
        scores[uid] = score
        details.append(
            "  ⚔️ " + get_name(uid) + " [" + get_race_display(p["race"]) + "] " + atk_type + " → " + str(score)
        )

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    winner_id, winner_score = sorted_scores[0]

    # Урон проигравшим
    loser_lines = []
    for uid, score in sorted_scores[1:]:
        p = user_data[uid]
        dmg = random.randint(10, 25)
        p["hp"] = max(10, p["hp"] - dmg)
        p["losses"] = p.get("losses", 0) + 1
        loser_lines.append(
            "💀 " + get_name(uid) + " получает -" + str(dmg) + " HP "
            + "(осталось " + str(p["hp"]) + "/" + str(p["max_hp"]) + ")"
        )

    # Победитель получает победу + шанс дропа
    user_data[winner_id]["wins"] = user_data[winner_id].get("wins", 0) + 1
    user_data[winner_id]["pvp_wins"] = user_data[winner_id].get("pvp_wins", 0) + 1
    user_data[winner_id].setdefault("pvp_win_dates", []).append(time.strftime("%Y-%m-%d"))
    drop_log = ""
    if random.random() < DROP_CHANCE:
        drop_id = random.choice(ITEM_KEYS)
        user_data[winner_id]["inventory"].append(drop_id)
        drop_log = (
            "\n🎁 Трофей победителя: " + item_name(drop_id) + "\n   └ " + item_desc(drop_id)
        )

    log = (
        "<b>⚔️ ИТОГИ ГРУППОВОЙ БИТВЫ</b>\n"
        "──────────────────\n\n"
        + "\n".join(details)
        + "\n\n──────────────────\n"
        + "\n".join(loser_lines)
        + "\n\n🏆 Победитель: <b>" + get_name(winner_id) + "</b>"
        + " [" + get_race_display(user_data[winner_id]["race"]) + "]"
        + drop_log
    )

    save_data()
    del active_brawl[brawl_id]
    _edit(chat_id, msg_id, log,
        reply_markup=back_to_menu_markup(0)
    )


# ─── /loot, /action, /roll ────────────────────────────────────────────────────

@bot.message_handler(commands=["loot"])
def get_loot(message):
    uid = message.from_user.id
    init_user(uid, message.from_user.first_name, chat_id=message.chat.id)
    _do_loot(message.chat.id, uid)


@bot.message_handler(commands=["action"])
def do_action(message):
    uid = message.from_user.id
    init_user(uid, message.from_user.first_name, chat_id=message.chat.id)
    cur = time.time()
    last = user_data[uid]["last_action_time"]
    if cur - last < 180:
        rem = int(180 - (cur - last))
        _send(message.chat.id, "⏱️ Жди " + str(rem) + " сек")
    else:
        user_data[uid]["last_action_time"] = cur
        save_data()
        act = random.choice(FUNNY_ACTIONS)
        _send(message.chat.id, "🎪 " + get_name(uid) + " " + act)


@bot.message_handler(commands=["roll"])
def roll_cube(message):
    uid = message.from_user.id
    init_user(uid, message.from_user.first_name, chat_id=message.chat.id)
    _do_roll(message.chat.id, uid)


# ─── неизвестные сообщения ────────────────────────────────────────────────────

@bot.message_handler(func=lambda message: message.text and not message.text.startswith("/"))
def handle_unknown_messages(message):
    bot.reply_to(message, "Напиши /help для списка команд ❓")


if __name__ == "__main__":
    load_data()
    try:
        bot.set_my_commands([
            telebot.types.BotCommand("/race",    "выбрать / сменить класс"),
            telebot.types.BotCommand("/fight",   "битва с монстром (PvE)"),
            telebot.types.BotCommand("/pvp",     "дуэль 1 на 1 (ответом)"),
            telebot.types.BotCommand("/brawl",   "групповая битва"),
            telebot.types.BotCommand("/loot",    "сундук (кд 2 часа)"),
            telebot.types.BotCommand("/action",  "случайное действие (кд 3 мин)"),
            telebot.types.BotCommand("/roll",    "кубик d20"),
            telebot.types.BotCommand("/my_hero", "карточка героя"),
            telebot.types.BotCommand("/bag",     "инвентарь"),
            telebot.types.BotCommand("/stats",   "статистика"),
            telebot.types.BotCommand("/items",   "все предметы"),
            telebot.types.BotCommand("/top",     "топ-10 группы"),
            telebot.types.BotCommand("/help",    "помощь"),
        ])
    except Exception as e:
        print("set_my_commands error (ignored):", e)
    Thread(target=regen_loop, daemon=True).start()
    print("Бот успешно запущен...")
    bot.infinity_polling(timeout=30, long_polling_timeout=30, restart_on_change=False)
