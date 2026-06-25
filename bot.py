import asyncio
import random
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
import aiosqlite
from answers import correct_answers  # ← наш файл с ответами
import os

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@твой_ник")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class UserState(StatesGroup):
    choosing_subject = State()
    checking_mode = State()
    checking_answers = State()   # активная проверка

# ==================== ПРОВЕРКА ПОДПИСКИ ====================
async def check_subscription(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

async def subscription_required(callback: CallbackQuery) -> bool:
    if not await check_subscription(callback.from_user.id):
        await callback.message.answer(
            "❗️ У тебя больше нет подписки на канал.\n\n"
            f"Подпишись заново: {CHANNEL_ID}\n\nПосле этого нажми /start"
        )
        await callback.answer()
        return False
    return True

# ==================== БАЗА ДАННЫХ ====================
async def get_used_variants(user_id: int, subject: str):
    async with aiosqlite.connect("users.db") as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS used_variants 
                          (user_id INTEGER, subject TEXT, variant INTEGER, PRIMARY KEY(user_id, subject, variant))""")
        await db.commit()
        cursor = await db.execute("SELECT variant FROM used_variants WHERE user_id=? AND subject=?", (user_id, subject))
        return [row[0] for row in await cursor.fetchall()]

async def mark_variant_as_used(user_id: int, subject: str, variant: int):
    async with aiosqlite.connect("users.db") as db:
        await db.execute("INSERT OR IGNORE INTO used_variants VALUES(?, ?, ?)", (user_id, subject, variant))
        await db.commit()

# ==================== ТАБЛИЦА ПЕРЕВОДА ====================
score_to_100 = {
    1:6, 2:12, 3:20, 4:25, 5:27, 6:30, 7:35, 8:39, 9:43,
    10:47, 11:52, 12:57, 13:61, 14:64, 15:66, 16:68, 17:72,
    18:76, 19:79, 20:81, 21:84, 22:89, 23:90, 24:95, 25:100
}

# ==================== КЛАВИАТУРЫ ====================
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Counter-Strike", callback_data="subject_cs")],
        [InlineKeyboardButton(text="⛏️ Minecraft", callback_data="subject_minecraft")],
        [InlineKeyboardButton(text="🆘 Техподдержка", callback_data="support")]
    ])

def after_answers_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_menu")],
        [InlineKeyboardButton(text="🆘 Техподдержка", url=f"https://t.me/{ADMIN_USERNAME.strip('@')}")]
    ])

# ==================== СТАРТ ====================
@dp.message(Command("start"))
async def start(message: Message, state: FSMContext):
    if not await check_subscription(message.from_user.id):
        await message.answer("❗️ Подпишись на канал, чтобы пользоваться ботом.")
        return
    await state.clear()
    await message.answer("🎉 Добро пожаловать в бот авторских вариантов ЕГЭ!\n\nВыбери предмет:", reply_markup=main_menu())

# ==================== ВЫБОР ПРЕДМЕТА ====================
@dp.callback_query(F.data.startswith("subject_"))
async def subject_selected(callback: CallbackQuery, state: FSMContext):
    if not await subscription_required(callback): return
    subject = callback.data.split("_")[1]
    await state.update_data(subject=subject)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Случайный вариант", callback_data="random_variant")],
        [InlineKeyboardButton(text="📋 Выбрать вариант", callback_data="manual_variant")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

    name = "🎮 Counter-Strike" if subject == "cs" else "⛏️ Minecraft"
    await callback.message.edit_text(f"{name}\n\nВыбери режим:", reply_markup=kb)
    await callback.answer()

# ==================== СЛУЧАЙНЫЙ ВАРИАНТ ====================
@dp.callback_query(F.data == "random_variant")
async def give_random_variant(callback: CallbackQuery, state: FSMContext):
    if not await subscription_required(callback): return
    data = await state.get_data()
    subject = data.get("subject")
    user_id = callback.from_user.id

    used = await get_used_variants(user_id, subject)
    available = [i for i in range(1, 6) if i not in used]

    if not available:
        await callback.message.answer("✅ Ты уже решил все доступные варианты по этому предмету!")
        return

    variant = random.choice(available)
    await mark_variant_as_used(user_id, subject, variant)

    await callback.message.answer_document(
        FSInputFile(f"variants/{subject}/variant{variant}.pdf"),
        caption=f"🎲 Случайный вариант №{variant}\n\nУдачи в решении!"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Начать проверку", callback_data=f"start_check_{subject}_{variant}")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
    ])

    await callback.message.answer("Готов проверить ответы?", reply_markup=kb)
    await callback.answer()

# ==================== ВЫБОР ВАРИАНТА ВРУЧНУЮ ====================
@dp.callback_query(F.data == "manual_variant")
async def manual_variant(callback: CallbackQuery, state: FSMContext):
    if not await subscription_required(callback): return
    data = await state.get_data()
    subject = data.get("subject")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Вариант №{i}", callback_data=f"manual_{subject}_{i}")] for i in range(1, 6)
    ] + [[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]])

    await callback.message.edit_text("Выбери номер варианта:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("manual_"))
async def give_manual_variant(callback: CallbackQuery):
    if not await subscription_required(callback): return
    _, subject, variant_str = callback.data.split("_")
    variant = int(variant_str)

    await callback.message.answer_document(
        FSInputFile(f"variants/{subject}/variant{variant}.pdf"),
        caption=f"📋 Вариант №{variant}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Начать проверку", callback_data=f"start_check_{subject}_{variant}")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
    ])

    await callback.message.answer("Готов проверить ответы?", reply_markup=kb)
    await callback.answer()

# ==================== СТАРТ ПРОВЕРКИ ====================
@dp.callback_query(F.data.startswith("start_check_"))
async def start_check(callback: CallbackQuery, state: FSMContext):
    if not await subscription_required(callback): return
    _, subject, variant_str = callback.data.split("_")
    variant = int(variant_str)

    await state.update_data(subject=subject, variant=variant, current_task=0, total_score=0)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Автоматическая проверка", callback_data="auto_mode")],
        [InlineKeyboardButton(text="📄 Ручная (файл ответов)", callback_data="manual_file")]
    ])

    await callback.message.answer(f"Вариант №{variant} — {subject.upper()}\n\nВыбери способ проверки:", reply_markup=kb)
    await callback.answer()

# ==================== РУЧНАЯ ПРОВЕРКА ====================
@dp.callback_query(F.data == "manual_file")
async def manual_file(callback: CallbackQuery):
    await callback.message.answer("📄 Вот файл с ответами:")
    # Здесь можно добавить отправку файла ответов, если хочешь
    await callback.message.answer("Что дальше?", reply_markup=after_answers_keyboard())
    await callback.answer()

# ==================== АВТОМАТИЧЕСКАЯ ПРОВЕРКА ====================
@dp.callback_query(F.data == "auto_mode")
async def auto_mode(callback: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="По мере решения", callback_data="live_check")],
        [InlineKeyboardButton(text="После решения всего", callback_data="batch_check")]
    ])
    await callback.message.answer("Выбери режим автоматической проверки:", reply_markup=kb)
    await callback.answer()

# По мере решения
@dp.callback_query(F.data == "live_check")
async def live_check(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    subject = data["subject"]
    variant = data["variant"]

    await state.set_state(UserState.checking_answers)
    await callback.message.answer(
        f"✅ Начинаем проверку варианта №{variant} по мере решения.\n\n"
        f"Отправляй ответы по одному.\n"
        f"Задание 1:"
    )
    await callback.answer()

# После решения всего
@dp.callback_query(F.data == "batch_check")
async def batch_check(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    subject = data["subject"]
    variant = data["variant"]

    await state.set_state(UserState.checking_answers)
    await callback.message.answer(
        f"✅ Начинаем проверку варианта №{variant}.\n\n"
        f"Отправляй ответы по порядку, начиная с задания 1."
    )
    await callback.answer()

# ==================== ОБРАБОТКА ОТВЕТОВ ====================
@dp.message(UserState.checking_answers)
async def process_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    subject = data["subject"]
    variant = data["variant"]
    task = data.get("current_task", 0)
    total_score = data.get("total_score", 0)

    key = (subject, variant)
    if key not in correct_answers or task >= len(correct_answers[key]):
        await message.answer("Проверка завершена!")
        await finish_checking(message, state)
        return

    correct = correct_answers[key][task]
    user_answer = message.text.strip()

    is_correct = user_answer.upper() == correct["answer"].upper()

    if is_correct:
        total_score += correct["points"]
        await message.answer(f"✅ Задание {task+1} — Правильно! (+{correct['points']} балл)")
    else:
        await message.answer(
            f"❌ Задание {task+1} — Неверно.\n"
            f"Правильный ответ: {correct['answer']}"
        )

    await state.update_data(current_task=task + 1, total_score=total_score)

    if task + 1 >= len(correct_answers[key]):
        await finish_checking(message, state)
    else:
        await message.answer(f"Задание {task + 2}:")

async def finish_checking(message: Message, state: FSMContext):
    data = await state.get_data()
    total_primary = data.get("total_score", 0)
    secondary = score_to_100.get(total_primary, 0)

    await message.answer(
        f"🎉 Проверка завершена!\n\n"
        f"Первичные баллы: <b>{total_primary}</b>\n"
        f"Вторичные баллы: <b>{secondary}</b>",
        parse_mode="HTML"
    )
    await state.clear()

# ==================== ТЕХПОДДЕРЖКА ====================
@dp.callback_query(F.data == "support")
async def support(callback: CallbackQuery):
    await callback.message.answer(
        "🆘 Связь с администратором:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Написать админу", url=f"https://t.me/{ADMIN_USERNAME.strip('@')}")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    if not await subscription_required(callback): return
    await state.clear()
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu())
    await callback.answer()

async def main():
    print("✅ Бот ЕГЭ с продвинутой проверкой запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())