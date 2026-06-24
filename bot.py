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
        [InlineKeyboardButton(text="📚 Выбрать предмет", callback_data="choose_subject")],
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
        await message.answer(
            "❗️ Бот работает при поддержке этого канала:\n\n"
            f"{CHANNEL_ID}\n\nПодпишись и нажми /start снова.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🆘 Техподдержка", url=f"https://t.me/{ADMIN_USERNAME.strip('@')}")]
            ])
        )
        return

    await state.clear()
    await message.answer(
        "🎉 Добро пожаловать в бот авторских вариантов ЕГЭ!!\n\n"
        "Выбери предмет и решай.",
        reply_markup=main_menu()
    )


# ==================== МЕНЮ ====================
@dp.callback_query(F.data == "choose_subject")
async def choose_subject(callback: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Counter-Strike", callback_data="subject_cs")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text("Выбери предмет:", reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Главное меню:", reply_markup=main_menu())
    await callback.answer()


@dp.callback_query(F.data.startswith("subject_"))
async def subject_selected(callback: CallbackQuery, state: FSMContext):
    subject = callback.data.split("_")[1]
    await state.update_data(subject=subject)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Случайный вариант (без повторений)", callback_data="random_variant")],
        [InlineKeyboardButton(text="📋 Выбрать вариант самому", callback_data="manual_variant")],
        [InlineKeyboardButton(text="🔙 Назад к предметам", callback_data="choose_subject")]
    ])

    await callback.message.edit_text("Counter-Strike\n\nВыбери режим:", reply_markup=kb)
    await callback.answer()


# ==================== СЛУЧАЙНЫЙ ВАРИАНТ ====================
@dp.callback_query(F.data == "random_variant")
async def give_random_variant(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    subject = data.get("subject")
    user_id = callback.from_user.id

    used = await get_used_variants(user_id, subject)
    available = [i for i in range(1, 6) if i not in used]

    if not available:
        await callback.message.answer("Ты уже решил все 5 вариантов по этому предмету!")
        return

    variant = random.choice(available)
    await mark_variant_as_used(user_id, subject, variant)

    await callback.message.answer_document(
        FSInputFile(f"variants/variant{variant}.pdf"),
        caption=f"🎲 Случайный вариант №{variant}\n\nУдачи в решении!"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Решено", callback_data=f"answers_{variant}")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")],
        [InlineKeyboardButton(text="🆘 Техподдержка", url=f"https://t.me/{ADMIN_USERNAME.strip('@')}")]
    ])

    await callback.message.answer("Когда решишь - нажми:", reply_markup=kb)
    await callback.answer()


# ==================== ВЫБОР ВАРИАНТА ВРУЧНУЮ ====================
@dp.callback_query(F.data == "manual_variant")
async def manual_variant(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
                                                  [InlineKeyboardButton(text=f"Вариант №{i}",
                                                                        callback_data=f"manual_{i}") for i in
                                                   range(1, 6)]
                                              ] + [[InlineKeyboardButton(text="🔙 Назад",
                                                                         callback_data="choose_subject")]])

    await callback.message.edit_text("Выбери номер варианта:", reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("manual_"))
async def give_manual_variant(callback: CallbackQuery):
    variant = int(callback.data.split("_")[1])

    await callback.message.answer_document(
        FSInputFile(f"variants/variant{variant}.pdf"),
        caption=f"📋 Выбран вариант №{variant}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Решено", callback_data=f"answers_{variant}")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")],
        [InlineKeyboardButton(text="🆘 Техподдержка", url=f"https://t.me/{ADMIN_USERNAME.strip('@')}")]
    ])

    await callback.message.answer("Когда решишь — нажми:", reply_markup=kb)
    await callback.answer()


# ==================== ОТПРАВКА ОТВЕТОВ + КНОПКИ ====================
@dp.callback_query(F.data.startswith("answers_"))
async def send_answers(callback: CallbackQuery):
    variant = int(callback.data.split("_")[1])

    await callback.message.answer_document(
        FSInputFile(f"answers/answer{variant}.pdf"),
        caption=f"📝 Ответы к варианту №{variant}\n\nПроверь свои результаты."
    )

    # Добавляем кнопки после ответов
    await callback.message.answer(
        "Что дальше?",
        reply_markup=after_answers_keyboard()
    )

    await callback.answer("Ответы отправлены!")


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


async def main():
    print("✅ Бот ЕГЭ запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())