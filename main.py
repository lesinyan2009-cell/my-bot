import random
import time
import json
import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

BOT_TOKEN = os.getenv('BOT_TOKEN')
DATA_FILE = "save_data.json"

bot = telebot.TeleBot(BOT_TOKEN)

user_data = {}
active_pvp = {}

RACE_STATS = {
    "Томатная эльфийка": {"hp": 90, "mp": 70, "dex": 14, "emoji": "🍅"},
    "Брокен боб": {"hp": 110, "mp": 40, "dex": 11, "emoji": "🫘"},
    "Какашливый гусеница": {"hp": 150, "mp": 20, "dex": 8, "emoji": "🐛"},
    "Данилость": {"hp": 85, "mp": 100, "dex": 10, "emoji": "✨"},
    "Ютуки величайший": {"hp": 130, "mp": 80, "dex": 5, "emoji": "👑"}
}

RACE_KEYS = list(RACE_STATS.keys())

RACE_COMBAT = {
    "Томатная эльфийка": {
        "phys": "швыряет острый томатный кинжал",
        "magic": "кастует взрывной томатный сок"
    },
    "Брокен боб": {
        "phys": "таранит врага титановой кожурой",
        "magic": "призывает бобовый взрыв"
    },
    "Какашливый гусеница": {
        "phys": "падает всей массой прямо на врага",
        "magic": "выпускает удушающий туман"
    },
    "Данилость": {
        "phys": "резко бьет волшебным посохом",
        "magic": "выпускает луч космической данилости"
    },
    "Ютуки величайший": {
        "phys": "бьет врага золотой перчаткой",
        "magic": "использует магию грозного приказа"
    }
}

MONSTERS_DB = {
    "Мекзость 🧠": {"type": "ум", "bonus": 12, "desc": "хитрит мыслями"},
    "Чорность 🔮": {"type": "маг", "bonus": 14, "desc": "бьет темной магией"},
    "Размезность 💪": {"type": "сила", "bonus": 16, "desc": "бьет кулачищами"},
    "Томатость 🍅": {"type": "всё", "bonus": 4, "desc": "выглядит нелепо"}
}

# Каждый предмет: name, описание эффекта, логика в handle_item_use
ITEMS_DB = {
    "sword":   {"name": "Сломанный меч 🗡️",    "desc": "+3 боевой бонус навсегда"},
    "juice":   {"name": "Томатный сок 🥤",       "desc": "Полное восстановление HP и MP"},
    "crown":   {"name": "Корона Ютуки 👑",        "desc": "+5 боевой бонус навсегда"},
    "boots":   {"name": "Дырявые сапоги 👞",      "desc": "+3 ловкость навсегда"},
    "potion":  {"name": "Странное зелье 🧪",      "desc": "50/50: +30 HP или -20 HP"},
    "shield":  {"name": "Титановый щит 🛡️",       "desc": "+20 к максимальному HP"},
    "tome":    {"name": "Мистический том 📖",     "desc": "+20 к максимальному MP"},
    "amulet":  {"name": "Амулет удачи 🍀",        "desc": "Следующий бросок гарантированно 15+"},
}

ITEM_KEYS = list(ITEMS_DB.keys())

FUNNY_ACTIONS = [
    "случайно ломает стол в таверне",
    "спотыкается о жирную гусеницу",
    "кричит, что Ютуки — величайший",
    "пытается сделать сальто в грязь"
]

# Шанс дропа предмета с монстра (30%)
DROP_CHANCE = 0.30


# ─── сохранение / загрузка ────────────────────────────────────────────────────

def load_data():
    global user_data
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            user_data = {int(k): v for k, v in raw.items()}
            # Добавляем новые поля если их нет (миграция)
            for uid, p in user_data.items():
                p.setdefault("lucky_amulet", False)
            print("Данные загружены: " + str(len(user_data)) + " игроков")
        except Exception as e:
            print("Ошибка загрузки данных: " + str(e))
            user_data = {}
    else:
        user_data = {}


def save_data():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Ошибка сохранения: " + str(e))


# ─── вспомогательные функции ──────────────────────────────────────────────────

def init_user(uid):
    if uid not in user_data:
        user_data[uid] = {
            "race": None, "max_hp": 100, "hp": 100,
            "max_mp": 50, "mp": 50, "dexterity": 10,
            "combat_bonus": 0, "inventory": [],
            "last_loot_time": 0, "last_action_time": 0,
            "roll_buff": 0, "roll_buff_time": 0,
            "lucky_amulet": False
        }
        save_data()


def get_race_display(race_key):
    st = RACE_STATS[race_key]
    return st["emoji"] + " " + race_key


def make_bar(cur, max_v, emoji):
    if max_v <= 0:
        return "⬜" * 10
    pct = max(0, min(10, round((cur / max_v) * 10)))
    return (emoji * pct) + ("⬜" * (10 - pct))


def get_active_roll_buff(uid):
    init_user(uid)
    p = user_data[uid]
    if time.time() - p["roll_buff_time"] < 300:
        return p["roll_buff"]
    return 0


def item_name(it_id):
    return ITEMS_DB.get(it_id, {}).get("name", "Предмет 📦")


def item_desc(it_id):
    return ITEMS_DB.get(it_id, {}).get("desc", "")


def main_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("📋 Меню"))
    return kb


def menu_inline():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("👤 Мой герой", callback_data="menu_hero"),
        InlineKeyboardButton("🎒 Инвентарь",  callback_data="menu_bag"),
        InlineKeyboardButton("⚔️ Битва",       callback_data="menu_fight"),
        InlineKeyboardButton("🎲 Кубик d20",   callback_data="menu_roll"),
        InlineKeyboardButton("📦 Сундук",       callback_data="menu_loot"),
        InlineKeyboardButton("🎭 Сменить класс",callback_data="menu_race"),
        InlineKeyboardButton("🎪 Случайное действие", callback_data="menu_action"),
    )
    return markup


# ─── /start и /help ───────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    uid = message.from_user.id
    init_user(uid)
    txt = (
        "Добро пожаловать в игру!\n\n"
        "Нажми кнопку 📋 Меню внизу — там всё нужное.\n\n"
        "Команды:\n"
        "/race — выбрать / сменить класс\n"
        "/fight — битва с монстром\n"
        "/pvp — дуэль (ответом на сообщение)\n"
        "/loot — открыть сундук (кд 2 часа)\n"
        "/action — случайное действие (кд 3 мин)\n"
        "/roll — бросить d20\n"
        "/items — список всех предметов"
    )
    bot.send_message(message.chat.id, txt, reply_markup=main_keyboard())


# ─── /items — справочник предметов ───────────────────────────────────────────

@bot.message_handler(commands=["items"])
def show_items_list(message):
    txt = "Все предметы в игре:\n\n"
    for it_id, info in ITEMS_DB.items():
        txt += info["name"] + "\n  " + info["desc"] + "\n\n"
    bot.send_message(message.chat.id, txt)


# ─── Кнопка "📋 Меню" ─────────────────────────────────────────────────────────

@bot.message_handler(func=lambda m: m.text == "📋 Меню")
def show_menu(message):
    uid = message.from_user.id
    init_user(uid)
    p = user_data[uid]
    if p["race"]:
        header = (
            get_race_display(p["race"]) + "\n"
            "HP: " + str(p["hp"]) + "/" + str(p["max_hp"]) + "  "
            "MP: " + str(p["mp"]) + "/" + str(p["max_mp"]) + "\n"
            "Предметов в сумке: " + str(len(p["inventory"])) + "\n\n"
            "Выбери действие:"
        )
    else:
        header = "Герой не создан. Выбери класс!\n\nВыбери действие:"
    bot.send_message(message.chat.id, header, reply_markup=menu_inline())


# ─── Обработка кнопок меню ────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_"))
def handle_menu_action(call):
    action = call.data[5:]
    uid = call.from_user.id
    init_user(uid)

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
            InlineKeyboardButton("Физ. удар ⚔️", callback_data="pvep"),
            InlineKeyboardButton("Магия (-15 MP) 🔮", callback_data="pvem")
        )
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Враг близко! Выбери атаку:",
            reply_markup=markup
        )

    elif action == "roll":
        _do_roll(call.message.chat.id, uid, edit_msg=call.message)

    elif action == "loot":
        _do_loot(call.message.chat.id, uid, edit_msg=call.message)

    elif action == "race":
        _show_race_selection(call.message.chat.id, uid, edit_msg=call.message)

    elif action == "action":
        _do_action_inline(call)


def _do_action_inline(call):
    uid = call.from_user.id
    p = user_data[uid]
    cur = time.time()
    last = p["last_action_time"]
    if cur - last < 180:
        rem = int(180 - (cur - last))
        bot.answer_callback_query(call.id, "Жди " + str(rem) + " сек ⏱️", show_alert=True)
        return
    p["last_action_time"] = cur
    save_data()
    act = random.choice(FUNNY_ACTIONS)
    name = call.from_user.first_name
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=name + " " + act + " 🎲\n\nНажми 📋 Меню чтобы вернуться."
    )


# ─── Выбор / смена расы ───────────────────────────────────────────────────────

def _show_race_selection(chat_id, uid, edit_msg=None):
    p = user_data[uid]
    markup = InlineKeyboardMarkup()
    for i, race_key in enumerate(RACE_KEYS):
        display = get_race_display(race_key)
        if p["race"] == race_key:
            display = display + " ✅"
        markup.add(InlineKeyboardButton(display, callback_data="r" + str(i)))
    if p["race"] is not None:
        text = (
            "Текущий класс: " + get_race_display(p["race"]) + "\n\n"
            "При смене сохранятся инвентарь и бонусы,\n"
            "но HP и MP сбросятся по новым статам.\n\n"
            "Выбери класс:"
        )
    else:
        text = "Выбери класс:"
    if edit_msg:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=edit_msg.message_id,
            text=text,
            reply_markup=markup
        )
    else:
        bot.send_message(chat_id, text, reply_markup=markup)


@bot.message_handler(commands=["race"])
def choose_race_menu(message):
    uid = message.from_user.id
    init_user(uid)
    _show_race_selection(message.chat.id, uid)


@bot.callback_query_handler(func=lambda call: call.data.startswith("r") and call.data[1:].isdigit())
def handle_race_selection(call):
    uid = call.from_user.id
    init_user(uid)
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
            "СОЗДАН: " + display + "\n\n"
            "HP: " + str(st["hp"]) + "\n"
            "MP: " + str(st["mp"]) + "\n"
            "Ловкость: " + str(st["dex"]) + "\n\n"
            "Нажми 📋 Меню чтобы начать!"
        )
    else:
        log = (
            "Класс изменён!\n"
            "Было: " + get_race_display(old_race) + "\n"
            "Стало: " + display + "\n\n"
            "HP: " + str(st["hp"]) + "\n"
            "MP: " + str(st["mp"]) + "\n"
            "Ловкость: " + str(st["dex"]) + "\n\n"
            "Инвентарь и бонусы сохранены."
        )
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=log
    )


# ─── Вспомогательные функции ──────────────────────────────────────────────────

def _send_hero_info(chat_id, uid, edit_msg=None):
    p = user_data[uid]
    if p["race"] is None:
        text = "У тебя еще нет героя. Выбери класс через меню или /race"
        if edit_msg:
            bot.edit_message_text(chat_id=chat_id, message_id=edit_msg.message_id, text=text)
        else:
            bot.send_message(chat_id, text)
        return
    rb = get_active_roll_buff(uid)
    b_txt = ""
    if rb > 0:
        b_txt = " (бафф +" + str(rb) + " от кубика!)"
    elif rb < 0:
        b_txt = " (дебафф " + str(rb) + ")"
    lucky = " (амулет активен!)" if p.get("lucky_amulet") else ""
    display = get_race_display(p["race"])
    msg = (
        "ГЕРОЙ: " + display + "\n\n"
        "HP: " + str(p["hp"]) + "/" + str(p["max_hp"]) + "\n"
        + make_bar(p["hp"], p["max_hp"], "🟩") + "\n\n"
        "MP: " + str(p["mp"]) + "/" + str(p["max_mp"]) + "\n"
        + make_bar(p["mp"], p["max_mp"], "🟦") + "\n\n"
        "Ловкость: " + str(p["dexterity"]) + "\n"
        "Боевой бонус: +" + str(p["combat_bonus"]) + b_txt + "\n"
        "Предметов: " + str(len(p["inventory"])) + lucky
    )
    if edit_msg:
        bot.edit_message_text(chat_id=chat_id, message_id=edit_msg.message_id, text=msg)
    else:
        bot.send_message(chat_id, msg)


def _send_bag(chat_id, uid, edit_msg=None):
    inv = user_data[uid]["inventory"]
    if not inv:
        text = "Инвентарь пуст. Открой сундук через меню или /loot"
        if edit_msg:
            bot.edit_message_text(chat_id=chat_id, message_id=edit_msg.message_id, text=text)
        else:
            bot.send_message(chat_id, text)
        return
    counts = {}
    for it in inv:
        counts[it] = counts.get(it, 0) + 1
    markup = InlineKeyboardMarkup()
    for it_id, count in counts.items():
        name = item_name(it_id)
        desc = item_desc(it_id)
        label = name + " x" + str(count) + "  [" + desc + "]"
        markup.add(InlineKeyboardButton(label, callback_data="use" + it_id))
    if edit_msg:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=edit_msg.message_id,
            text="Твой инвентарь (нажми предмет чтобы использовать):",
            reply_markup=markup
        )
    else:
        bot.send_message(chat_id, "Твой инвентарь:", reply_markup=markup)


def _do_roll(chat_id, uid, edit_msg=None):
    p = user_data[uid]
    # Амулет удачи гарантирует 15+
    if p.get("lucky_amulet"):
        res = random.randint(15, 20)
        p["lucky_amulet"] = False
        amulet_txt = "Амулет удачи сработал! 🍀\n"
    else:
        res = random.randint(1, 20)
        amulet_txt = ""
    if res == 20:
        b, st = 6, "КРИТ УСПЕХ! Мощный бафф! 🔥"
    elif res >= 15:
        b, st = 4, "Отличный бросок! Боевой дух! ✨"
    elif res >= 6:
        b, st = 2, "Нормальный бросок. Чуть силы. 👍"
    else:
        b, st = -2, "КРИТ НЕУДАЧА! Дебафф! 💀"
    p["roll_buff"] = b
    p["roll_buff_time"] = time.time()
    save_data()
    sign = "+" if b >= 0 else ""
    log = (
        amulet_txt +
        "На d20 выпало: " + str(res) + " 🎲\n\n"
        + st + "\n"
        "Эффект: Модификатор " + sign + str(b) + " на 5 минут!"
    )
    if edit_msg:
        bot.edit_message_text(chat_id=chat_id, message_id=edit_msg.message_id, text=log)
    else:
        bot.send_message(chat_id, log)


def _do_loot(chat_id, uid, edit_msg=None):
    cur = time.time()
    last = user_data[uid]["last_loot_time"]
    if cur - last < 7200:
        rem = int(7200 - (cur - last))
        text = "Жди " + str(rem // 3600) + "ч " + str((rem % 3600) // 60) + "м ⏱️"
    else:
        l_id = random.choice(ITEM_KEYS)
        user_data[uid]["inventory"].append(l_id)
        user_data[uid]["last_loot_time"] = cur
        save_data()
        text = "Найдено: " + item_name(l_id) + "\n" + item_desc(l_id) + "\n\nИщи в инвентаре 📦"
    if edit_msg:
        bot.edit_message_text(chat_id=chat_id, message_id=edit_msg.message_id, text=text)
    else:
        bot.send_message(chat_id, text)


# ─── /my_hero ─────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["my_hero"])
def check_hero(message):
    uid = message.from_user.id
    init_user(uid)
    _send_hero_info(message.chat.id, uid)


# ─── /bag ─────────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["bag"])
def check_bag(message):
    uid = message.from_user.id
    init_user(uid)
    _send_bag(message.chat.id, uid)


@bot.callback_query_handler(func=lambda call: call.data.startswith("use"))
def handle_item_use(call):
    uid = call.from_user.id
    init_user(uid)
    p = user_data[uid]
    it_id = call.data[3:]
    if it_id not in p["inventory"]:
        bot.answer_callback_query(call.id, "Предмет не найден.")
        return
    p["inventory"].remove(it_id)
    name = item_name(it_id)
    f_name = call.from_user.first_name
    log = f_name + " использует: " + name + "\n\n"

    if it_id == "juice":
        # Полное восстановление HP и MP
        p["hp"] = p["max_hp"]
        p["mp"] = p["max_mp"]
        log += "Выпит до дна! HP и MP полностью восстановлены. 🥤"

    elif it_id == "potion":
        # 50/50
        if random.choice([True, False]):
            heal = 30
            p["hp"] = min(p["max_hp"], p["hp"] + heal)
            log += "Зелье оказалось целебным! +" + str(heal) + " HP. 🧪"
        else:
            p["hp"] = max(10, p["hp"] - 20)
            log += "Зелье оказалось ядовитым! -20 HP. 🤢"

    elif it_id == "sword":
        # +3 боевой бонус
        p["combat_bonus"] += 3
        log += "Меч заточен (кое-как). Боевой бонус +3. 🗡️"

    elif it_id == "shield":
        # +20 к макс HP
        p["max_hp"] += 20
        p["hp"] = min(p["hp"] + 20, p["max_hp"])
        log += "Щит надет. Максимальный HP +20. 🛡️"

    elif it_id == "crown":
        # +5 боевой бонус
        p["combat_bonus"] += 5
        log += "Корона Ютуки надета. Боевой бонус +5. 👑"

    elif it_id == "boots":
        # +3 ловкость
        p["dexterity"] += 3
        log += "Сапоги надеты (дырки не мешают). Ловкость +3. 👞"

    elif it_id == "tome":
        # +20 к макс MP
        p["max_mp"] += 20
        p["mp"] = min(p["mp"] + 20, p["max_mp"])
        log += "Том прочитан. Максимальный MP +20. 📖"

    elif it_id == "amulet":
        # Следующий бросок 15+
        p["lucky_amulet"] = True
        log += "Амулет активирован! Следующий бросок d20 будет 15+. 🍀"

    else:
        log += "Предмет использован... и ничего не произошло."

    save_data()
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=log
    )


# ─── /fight ───────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["fight"])
def start_fight(message):
    uid = message.from_user.id
    init_user(uid)
    if user_data[uid]["race"] is None:
        bot.send_message(message.chat.id, "Сначала создай персонажа через /race")
        return
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Физ. удар ⚔️", callback_data="pvep"),
        InlineKeyboardButton("Магия (-15 MP) 🔮", callback_data="pvem")
    )
    bot.send_message(message.chat.id, "Враг близко! Выбери атаку:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data in ["pvep", "pvem"])
def handle_pve(call):
    uid = call.from_user.id
    init_user(uid)
    p = user_data[uid]
    if p["race"] is None:
        bot.answer_callback_query(call.id, "Сначала выбери расу!")
        return
    m_name = random.choice(list(MONSTERS_DB.keys()))
    m_info = MONSTERS_DB[m_name]
    p_dice, e_dice = random.randint(1, 20), random.randint(1, 20)
    total_bonus = p["combat_bonus"] + get_active_roll_buff(uid)
    log = "Битва: " + get_race_display(p["race"]) + " vs " + m_name + "\n"
    log += m_info["desc"] + "\n\n"
    if call.data == "pvep" or p["mp"] < 15:
        p_score = p_dice + p["dexterity"] + total_bonus
        e_score = e_dice + m_info["bonus"]
        log += "Ты " + RACE_COMBAT[p["race"]]["phys"] + "\n"
        log += "Бросок: " + str(p_dice) + "+" + str(p["dexterity"]) + "+" + str(total_bonus) + " = " + str(p_score) + "\n"
    else:
        p["mp"] -= 15
        p_score = p_dice + 15 + total_bonus
        e_score = e_dice + m_info["bonus"]
        log += "Ты " + RACE_COMBAT[p["race"]]["magic"] + "\n"
        log += "Магия: " + str(p_dice) + "+15+" + str(total_bonus) + " = " + str(p_score) + "\n"
    log += "Монстр: " + str(e_dice) + "+" + str(m_info["bonus"]) + " = " + str(e_score) + "\n\n"

    if p_score > e_score:
        log += "ПОБЕДА! Монстр повержен. 🏆"
        # Дроп предмета с шансом DROP_CHANCE
        if random.random() < DROP_CHANCE:
            drop_id = random.choice(ITEM_KEYS)
            p["inventory"].append(drop_id)
            log += "\n\nМонстр обронил: " + item_name(drop_id) + " 🎁\nЗабери в инвентаре!"
    elif e_score > p_score:
        dmg = random.randint(15, 30)
        p["hp"] = max(10, p["hp"] - dmg)
        log += "ПРОИГРЫШ! Потеряно " + str(dmg) + " HP 💀"
    else:
        log += "НИЧЬЯ! Вы разошлись. 🤝"

    save_data()
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=log
    )


# ─── /pvp ─────────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["pvp"])
def start_pvp(message):
    atk_id = message.from_user.id
    init_user(atk_id)
    if not message.reply_to_message:
        bot.reply_to(message, "Пиши /pvp в ответ на сообщение игрока!")
        return
    def_id = message.reply_to_message.from_user.id
    init_user(def_id)
    if atk_id == def_id:
        bot.reply_to(message, "Нельзя драться с собой!")
        return
    if user_data[atk_id]["race"] is None or user_data[def_id]["race"] is None:
        bot.reply_to(message, "У обоих игроков должны быть расы!")
        return
    b_id = str(atk_id) + "X" + str(def_id)
    active_pvp[b_id] = {"attacker": atk_id, "defender": def_id}
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Физ. защита ⚔️", callback_data="duelp" + b_id),
        InlineKeyboardButton("Маг. защита 🔮",  callback_data="duelm" + b_id)
    )
    def_name = message.reply_to_message.from_user.first_name
    bot.send_message(message.chat.id, "Вызов для " + def_name + "! Выбери тип защиты:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("duelp") or call.data.startswith("duelm"))
def handle_pvp_battle(call):
    mode = call.data[4]
    b_id = call.data[5:]
    if b_id not in active_pvp:
        bot.answer_callback_query(call.id, "Дуэль уже завершена или не найдена.")
        return
    duel = active_pvp[b_id]
    if call.from_user.id != duel["defender"]:
        bot.answer_callback_query(call.id, "Это не твоя дуэль!")
        return
    p1 = user_data[duel["attacker"]]
    p2 = user_data[duel["defender"]]
    d1, d2 = random.randint(1, 20), random.randint(1, 20)
    b1 = p1["combat_bonus"] + get_active_roll_buff(duel["attacker"])
    b2 = p2["combat_bonus"] + get_active_roll_buff(duel["defender"])
    if random.choice([True, False]) and p1["mp"] >= 15:
        p1["mp"] -= 15
        s1 = d1 + 15 + b1
        txt1 = "магией"
    else:
        s1 = d1 + p1["dexterity"] + b1
        txt1 = "физой"
    if mode == "m" and p2["mp"] >= 15:
        p2["mp"] -= 15
        s2 = d2 + 15 + b2
        txt2 = "магией"
    else:
        s2 = d2 + p2["dexterity"] + b2
        txt2 = "физой"
    log = "ИТОГИ ДУЭЛИ!\n\n"
    log += "Атакующий " + get_race_display(p1["race"]) + " (" + txt1 + "). Бросок: " + str(s1) + "\n"
    log += "Защищающий " + get_race_display(p2["race"]) + " (" + txt2 + "). Бросок: " + str(s2) + "\n\n"
    if s1 > s2:
        dmg = random.randint(20, 40)
        p2["hp"] = max(10, p2["hp"] - dmg)
        log += "Атакующий победил! Защищающий теряет " + str(dmg) + " HP. 🏆"
    elif s2 > s1:
        dmg = random.randint(20, 40)
        p1["hp"] = max(10, p1["hp"] - dmg)
        log += "Защищающий победил! Атакующий теряет " + str(dmg) + " HP. 🏆"
    else:
        log += "Ничья! 🤝"
    del active_pvp[b_id]
    save_data()
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=log
    )


# ─── /loot ────────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["loot"])
def get_loot(message):
    uid = message.from_user.id
    init_user(uid)
    _do_loot(message.chat.id, uid)


# ─── /action ──────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["action"])
def do_action(message):
    uid = message.from_user.id
    init_user(uid)
    cur = time.time()
    last = user_data[uid]["last_action_time"]
    if cur - last < 180:
        rem = int(180 - (cur - last))
        bot.send_message(message.chat.id, "Жди " + str(rem) + " сек ⏱️")
    else:
        user_data[uid]["last_action_time"] = cur
        save_data()
        act = random.choice(FUNNY_ACTIONS)
        bot.send_message(message.chat.id, message.from_user.first_name + " " + act + " 🎲")


# ─── /roll ────────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["roll"])
def roll_cube(message):
    uid = message.from_user.id
    init_user(uid)
    _do_roll(message.chat.id, uid)


# ─── неизвестные сообщения ────────────────────────────────────────────────────

@bot.message_handler(func=lambda message: not message.text.startswith("/") and message.text != "📋 Меню")
def handle_unknown_messages(message):
    bot.reply_to(message, "Напиши /help или нажми 📋 Меню ❓")


if __name__ == "__main__":
    load_data()
    print("Бот успешно запущен...")
    bot.infinity_polling()
