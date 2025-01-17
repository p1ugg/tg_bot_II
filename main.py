import json
import os
import random
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeDefault, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command, StateFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncio
from aiogram import BaseMiddleware
from typing import Callable, Dict, Any, Awaitable
import csv

from aiogram.utils.markdown import hbold
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from gigachat import GigaChat  # Импортируем библиотеку для работы с GigaChat
from langchain.memory import ConversationBufferMemory
from dotenv import load_dotenv

load_dotenv()

# Bot setup
API_TOKEN = os.getenv('API_TOKEN')
ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')

bot = Bot(token=API_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

memory = ConversationBufferMemory(return_messages=True)

# GigaChat setup
giga_chat = GigaChat(credentials=ACCESS_TOKEN, verify_ssl_certs=False)

messages = [
    "🔥 Не забудь сделать что-то полезное сегодня!",
    "💡 Новый день — новые возможности!",
    "😊 Сделай паузу и отдохни!",
    "📌 Помни: главное — движение вперёд!",
    "🌟 Твои усилия не напрасны, продолжай в том же духе!"
]

# Путь к файлу с chat_id пользователей
USERS_FILE = "users.json"


# Функция для загрузки всех chat_id пользователей
def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


# Функция для сохранения chat_id новых пользователей
def save_user(chat_id):
    users = load_users()
    if chat_id not in users:
        users.append(chat_id)
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=4)


async def send_daily_message():
    """Отправляет одно случайное сообщение всем пользователям в 18:00 по Москве."""
    users = load_users()
    if not users:
        print("❌ Нет пользователей для отправки сообщения.")
        return

    message = random.choice(messages)
    for chat_id in users:
        try:
            await bot.send_message(chat_id, hbold(message))  # Жирный текст
            print(f"✅ Сообщение отправлено пользователю с chat_id {chat_id}")
        except Exception as e:
            print(f"❌ Ошибка при отправке сообщения пользователю {chat_id}: {e}")


scheduler = AsyncIOScheduler()
scheduler.add_job(send_daily_message, CronTrigger(hour=18, minute=0, timezone="Europe/Moscow"))


# FSM States
class Registration(StatesGroup):
    name = State()
    last_name = State()
    field = State()
    question = State()
    username = State()


# Поля выбора и их клавиатура
fields = [
    ("Астрономия", "astro"),
    ("Космонавтика", "space"),
    ("Теоретическая физика", "phys"),
    ("Исследование планет", "planets"),
    ("Технологии", "tech"),
    ("История космоса", "history")
]

# Создание клавиатуры
field_buttons = InlineKeyboardBuilder()
for field_name, callback_code in fields:
    field_buttons.button(
        text=field_name[:20],  # Сокращение названия кнопок до 20 символов
        callback_data=f"field_{callback_code}"
    )
field_buttons.adjust(2)  # Установим кнопки в две строки для удобства
field_buttons = field_buttons.as_markup()


async def set_commands():
    commands = [BotCommand(command='start', description='Запустить и заполнить анкету'),
                BotCommand(command='ask', description='Задать вопрос'),
                BotCommand(command='cancel', description='В главное меню')]
    await bot.set_my_commands(commands, BotCommandScopeDefault())


# Handlers
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    user_chat_id = message.chat.id
    save_user(user_chat_id)
    await message.answer("Добро пожаловать! Давайте зарегистрируемся. Как вас зовут?")
    await state.set_state(Registration.name)


@dp.message(StateFilter(Registration.name))
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите вашу фамилию:")
    await state.set_state(Registration.last_name)


@dp.message(StateFilter(Registration.last_name))
async def process_last_name(message: types.Message, state: FSMContext):
    await state.update_data(last_name=message.text)
    await message.answer("Выберите вашу интересующую сферу:", reply_markup=field_buttons)


# Хэндлер выбора сферы
@dp.callback_query(StateFilter(Registration.last_name))
# @dp.callback_query(Text(startswith="field_"), StateFilter(Registration.last_name))
async def process_field(callback_query: types.CallbackQuery, state: FSMContext):
    callback_code = callback_query.data.split("field_")[1]

    # Поиск полного имени сферы по коду
    field = next((name for name, code in fields if code == callback_code), None)

    if not field:
        await callback_query.answer("Ошибка: неизвестная сфера.")
        return

    await state.update_data(field=field)
    await bot.send_message(callback_query.from_user.id, "Напишите ваш первый вопрос:")
    await state.set_state(Registration.question)


@dp.message(StateFilter(Registration.question))
async def process_question(message: types.Message, state: FSMContext):
    await state.update_data(question=message.text)
    await message.answer("Введите ваш username в Telegram (начинается с @):")
    await state.set_state(Registration.username)


@dp.message(StateFilter(Registration.username))
async def process_username(message: types.Message, state: FSMContext):
    if not message.text.startswith("@"):  # Validation
        await message.answer("Некорректный username. Попробуйте ещё раз:")
        return

    user_data = await state.get_data()
    user_data["username"] = message.text

    # Save to CSV
    with open("users.csv", "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([user_data["name"], user_data["last_name"], user_data["field"], user_data["question"],
                         user_data["username"]])

    await message.answer("Спасибо за регистрацию! Чтобы задавать вопросы напишите /ask.")
    await state.clear()


class RegistrationMiddleware(BaseMiddleware):
    async def __call__(
            self, handler: Callable[[types.Message, Dict[str, Any]], Awaitable[Any]],
            event: types.Message, data: Dict[str, Any]
    ) -> Any:
        """Middleware для проверки регистрации пользователя перед выполнением команд."""

        # Проверяем, что событие — это сообщение
        if not isinstance(event, types.Message):
            return await handler(event, data)

        # Получаем команду или текст
        command = event.text.strip().split()[0].lower()

        # Если команда /start — пропускаем проверку
        if command == "/start":
            return await handler(event, data)

        # Проверяем, находится ли пользователь в процессе регистрации (FSM)
        state: FSMContext = data.get("state")
        state_data = await state.get_state()

        if state_data:  # Если пользователь уже в процессе регистрации — пропускаем проверку
            return await handler(event, data)

        # Получаем username пользователя
        user_username = event.from_user.username

        if not user_username:
            await event.answer("⚠ У вас нет username в Telegram. Установите его в настройках и попробуйте снова.")
            return

        # Проверяем регистрацию пользователя в users.csv
        registered = False
        try:
            with open("users.csv", "r", encoding="utf-8") as file:
                reader = csv.reader(file)
                for row in reader:
                    if len(row) >= 5 and row[4][1:] == user_username:  # Сравниваем username без "@"
                        registered = True
                        break
        except FileNotFoundError:
            await event.answer("⚠ Ошибка: База данных пользователей не найдена.")
            return

        if not registered:
            await event.answer("❌ Вы не зарегистрированы. Введите /start для регистрации.")
            return

        return await handler(event, data)  # Продолжаем выполнение


# Подключаем Middleware
dp.message.middleware(RegistrationMiddleware())


class LoggingMiddleware(BaseMiddleware):
    LOG_FILE = "logs.csv"

    def __init__(self):
        super().__init__()
        self.create_log_file()

    def create_log_file(self):
        """Создает файл логов, если его нет."""
        if not os.path.exists(self.LOG_FILE):
            try:
                with open(self.LOG_FILE, "w", newline="", encoding="utf-8") as file:
                    writer = csv.writer(file)
                    writer.writerow(["username", "date_time", "message"])
                print(f"✅ Файл {self.LOG_FILE} создан.")
            except Exception as e:
                print(f"❌ Ошибка при создании {self.LOG_FILE}: {e}")

    async def __call__(self, handler, event, data):
        """Записывает текстовые сообщения в логи."""
        print(f"🟡 Middleware вызван! Тип события: {type(event)}")

        if event.message and event.message.text:  # Теперь проверяем event.message
            username = event.message.from_user.username or f"user_{event.message.from_user.id}"
            message_text = event.message.text.strip()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            print(f"📜 Логируем: {username} | {timestamp} | {message_text}")

            try:
                with open(self.LOG_FILE, "a", newline="", encoding="utf-8") as file:
                    writer = csv.writer(file)
                    writer.writerow([username, timestamp, message_text])
                    file.flush()

            except Exception as e:
                print(f"❌ Ошибка при записи в лог: {e}")

        return await handler(event, data)


dp.update.middleware(LoggingMiddleware())


class Asking(StatesGroup):
    asking = State()


# Клавиатура с кнопкой /ask
def get_ask_keyboard():
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="/ask")]],
        resize_keyboard=True
    )
    return keyboard


# Команда /ask включает режим вопросов
@dp.message(Command("ask"))
async def ask_question(message: types.Message, state: FSMContext):
    await state.set_state(Asking.asking)  # Устанавливаем состояние
    await message.answer("Вы можете задавать вопросы. Напишите /cancel, чтобы выйти.")


# Команда /cancel выключает режим вопросов
@dp.message(Command("cancel"))
async def cancel_asking(message: types.Message, state: FSMContext):
    await state.clear()  # Очищаем состояние
    await message.answer("Вы вышли из режима вопросов.", reply_markup=get_ask_keyboard())


# # Обрабатываем вопросы только в режиме Asking.asking
# @dp.message(Asking.asking)
# async def handle_question(message: types.Message, state: FSMContext):
#
#     response = giga_chat.chat(message.text)
#     answer = response.choices[0].message.content
#     words_in_answer = len(answer.split())
#
#     max_length = 700
#     confidence_score = min(words_in_answer / max_length, 1.0)
#
#     print(f"Длина ответа GigaChat: {words_in_answer} слов, коэффициент уверенности: {confidence_score}")
#
#     if confidence_score < 0:
#         await message.answer("Данный вопрос требует помощи эксперта, скоро вернусь.")
#
#         user_field = None
#         with open("users.csv", "r", encoding="utf-8") as user_file:
#             user_reader = csv.reader(user_file)
#             for row in user_reader:
#                 if row[4][1:] == message.from_user.username:
#                     user_field = row[2]
#                     break
#
#         if user_field:
#             expert_found = False
#             with open("experts.csv", "r", encoding="utf-8") as expert_file:
#                 expert_reader = csv.reader(expert_file)
#                 for expert_row in expert_reader:
#                     if user_field in expert_row[2]:
#                         expert_username = expert_row[1]
#                         expert_found = True
#
#                         await bot.send_message(expert_username,
#                                                f"Пользователь @{message.from_user.username} задал вопрос: {message.text}. Пожалуйста, дайте ответ в ЛС пользователю.")
#                         break
#
#             if not expert_found:
#                 await message.answer("Не удалось найти подходящего эксперта.")
#         else:
#             await message.answer("Не удалось найти подходящую область интересов для пользователя.")
#     else:
#         await message.answer(f"{answer}")

user_question_count = {}


@dp.message(Asking.asking)
async def handle_question(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_input = message.text

    # Увеличиваем счетчик вопросов пользователя
    user_question_count[user_id] = user_question_count.get(user_id, 0) + 1

    # Получаем историю диалога
    history = memory.load_memory_variables({})
    history_str = "\n".join([f"{msg.type}: {msg.content}" for msg in history.get("history", [])])

    # Запрос к GigaChat с учетом контекста
    response = giga_chat.chat(f"История диалога:\n{history_str}\nПользователь: {user_input}")

    # Получение ответа
    answer = response.choices[0].message.content

    # Запись в память
    memory.save_context(
        {"input": f"User: {user_input}"},
        {"output": f"Bot: {answer}"}
    )
    words_in_answer = len(answer.split())

    max_length = 80
    confidence_score = min(words_in_answer / max_length, 1.0)

    print(f"Длина ответа GigaChat: {words_in_answer} слов, коэффициент уверенности: {confidence_score}")

    if confidence_score < 0.2:
        await message.answer("Данный вопрос требует помощи эксперта, скоро вернусь.")

        user_field = None
        with open("users.csv", "r", encoding="utf-8") as user_file:
            user_reader = csv.reader(user_file)
            for row in user_reader:
                if row[4][1:] == message.from_user.username:
                    user_field = row[2]
                    break

        if user_field:
            expert_found = False
            with open("experts.csv", "r", encoding="utf-8") as expert_file:
                expert_reader = csv.reader(expert_file)
                for expert_row in expert_reader:
                    if user_field in expert_row[2]:
                        expert_username = expert_row[1]
                        expert_found = True

                        await bot.send_message(expert_username,
                                               f"Пользователь @{message.from_user.username} задал вопрос: {message.text}. Пожалуйста, дайте ответ в ЛС пользователю.")
                        break

            if not expert_found:
                await message.answer("Не удалось найти подходящего эксперта.")
        else:
            await message.answer("Не удалось найти подходящую область интересов для пользователя.")
    else:
        await message.answer(f"{answer}")

    # # Отправка ответа пользователю
    # await message.answer(answer)

    # Если задано 5 вопросов, предлагаем оценить бота
    if user_question_count[user_id] == 5:
        await message.answer("Оцените, пожалуйста, работу бота от 1 до 10:")


# Обработчик сообщений, если пользователь пишет вне режима вопросов
@dp.message()
async def unknown_message(message: types.Message):
    await message.answer(
        "Я не понимаю, что вы хотите. Чтобы задать вопрос, нажмите кнопку ниже или введите /ask.",
        reply_markup=get_ask_keyboard()
    )


# Run bot
async def main():
    scheduler.start()
    print("✅ Планировщик запущен!")
    await dp.start_polling(bot)
    await set_commands()


if __name__ == "__main__":
    asyncio.run(main())
