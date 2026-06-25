import asyncio
import random
import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
import aiosqlite

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@твой_ник")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


class UserState(StatesGroup):
    choosing_subject = State()


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
            f"Подпишись заново: {CHANNEL_ID}\n\nПосле этого нажми /start",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🆘 Техподдержка", url=f"https://t.me/{ADMIN_USERNAME.strip('@')}")]
            ])
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
        await message.answer("❗️ Подпишись на канал, чтобы пользоваться ботом:\n" + CHANNEL_ID)
        return

    await state.clear()
    await message.answer("🎉 Добро пожаловать в бот авторских вариантов ЕГЭ!\n\nВыбери предмет:",
                         reply_markup=main_menu())


# ==================== ВЫБОР ПРЕДМЕТА ====================
@dp.callback_query(F.data.startswith("subject_"))
async def subject_selected(callback: CallbackQuery, state: FSMContext):
    if not await subscription_required(callback): return

    subject = callback.data.split("_")[1]
    await state.update_data(subject=subject)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Случайный вариант (без повторений)", callback_data="random_variant")],
        [InlineKeyboardButton(text="📋 Выбрать вариант самому", callback_data="manual_variant")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

    subject_name = "🎮 Counter-Strike" if subject == "cs" else "⛏️ Minecraft"
    await callback.message.edit_text(f"{subject_name}\n\nВыбери режим:", reply_markup=kb)
    await callback.answer()


# ==================== СЛУЧАЙНЫЙ ВАРИАНТ ====================
@dp.callback_query(F.data == "random_variant")
async def give_random_variant(callback: CallbackQuery, state: FSMContext):
    if not await subscription_required(callback): return

    data = await state.get_data()
    subject = data.get("subject")
    user_id = callback.from_user.id

    used = await get_used_variants(user_id, subject)
    available = [i for i in range(1, 6) if i not in used]  # можно увеличить количество

    if not available:
        await callback.message.answer("✅ Ты уже решил все варианты по этому предмету!")
        return

    variant = random.choice(available)
    await mark_variant_as_used(user_id, subject, variant)

    await callback.message.answer_document(
        FSInputFile(f"variants/{subject}/variant{variant}.pdf"),
        caption=f"🎲 Случайный вариант №{variant}\n\nУдачи в решении!"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я решил", callback_data=f"answers_{subject}_{variant}")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")],
        [InlineKeyboardButton(text="🆘 Техподдержка", url=f"https://t.me/{ADMIN_USERNAME.strip('@')}")]
    ])

    await callback.message.answer("Когда решишь — нажми кнопку ниже:", reply_markup=kb)
    await callback.answer()


# ==================== ВЫБОР ВАРИАНТА ВРУЧНУЮ ====================
@dp.callback_query(F.data == "manual_variant")
async def manual_variant(callback: CallbackQuery, state: FSMContext):
    if not await subscription_required(callback): return

    data = await state.get_data()
    subject = data.get("subject")

    kb = InlineKeyboardMarkup(inline_keyboard=[
                                                  [InlineKeyboardButton(text=f"Вариант №{i}",
                                                                        callback_data=f"manual_{subject}_{i}")] for i in
                                                  range(1, 6)
                                              ] + [
                                                  [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]])

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
        [InlineKeyboardButton(text="✅ Я решил", callback_data=f"answers_{subject}_{variant}")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")],
        [InlineKeyboardButton(text="🆘 Техподдержка", url=f"https://t.me/{ADMIN_USERNAME.strip('@')}")]
    ])

    await callback.message.answer("Когда решишь — нажми:", reply_markup=kb)
    await callback.answer()


# ==================== ОТВЕТЫ ====================
@dp.callback_query(F.data.startswith("answers_"))
async def send_answers(callback: CallbackQuery):
    if not await subscription_required(callback): return

    _, subject, variant_str = callback.data.split("_")
    variant = int(variant_str)

    await callback.message.answer_document(
        FSInputFile(f"answers/{subject}/answer{variant}.pdf"),
        caption=f"📝 Ответы к варианту №{variant}"
    )

    await callback.message.answer("Что дальше?", reply_markup=after_answers_keyboard())
    await callback.answer()


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
    print("✅ Бот ЕГЭ (CS + Minecraft) запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())