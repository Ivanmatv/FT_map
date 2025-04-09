import requests
import geocoder
import folium
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from .logger import get_logger
import time
import os
from dotenv import load_dotenv
import sqlite3

# Загружаем переменные из .env
load_dotenv()

# Инициализируем логгер
logger = get_logger()

REDMINE_URL = "https://tasks.fut.ru"
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    logger.error("API_KEY not found in .env file or is empty")
    raise ValueError("API_KEY not found in .env file or is empty")

app = FastAPI()

# Указываем путь к папке app/static относительно корня проекта
app.mount("/static", StaticFiles(directory=os.path.join("app", "static")), name="static")

# Подключение к SQLite базе данных
DB_PATH = "users.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            city TEXT NOT NULL,
            job_title TEXT,
            department TEXT
        )
    """)
    conn.commit()
    conn.close()

# Инициализация базы данных при запуске
init_db()

# Функция для получения данных о пользователе из Redmine API
def get_user_data(user_id: int) -> dict:
    url = f"{REDMINE_URL}/users/{user_id}.json"
    headers = {'X-Redmine-API-Key': API_KEY}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching data for user {user_id}: {e}")
        return None

# Функция для получения данных из базы или API
def get_or_fetch_user_data(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name, email, city, job_title, department FROM employees WHERE id = ?", (user_id,))
    result = cursor.fetchone()

    if result:
        # Если пользователь есть в базе, возвращаем данные
        name, email, city, job_title, department = result
        return {
            'user': {
                'id': user_id,
                'firstname': name.split()[0],  # Предполагаем, что имя и фамилия разделены пробелом
                'lastname': ' '.join(name.split()[1:]),
                'mail': email,
                'custom_fields': [
                    {'name': 'Город проживания', 'value': city},
                    {'name': 'Должность', 'value': job_title},
                    {'name': 'Отдел', 'value': department}
                ]
            }
        }

    # Если пользователя нет в базе, запрашиваем из API
    user_data = get_user_data(user_id)
    if user_data:
        user = user_data['user']
        email = user.get('mail', '')
        if email.endswith('@futuretoday.ru'):
            name = f"{user['firstname']} {user['lastname']}"
            city = "No city"
            job_title = "Не указана"
            department = "Не указан"
            for field in user.get('custom_fields', []):
                if field['name'] == 'Город проживания':
                    city = field.get('value') or "No city"
                elif field['name'] == 'Должность':
                    job_title = field.get('value') or "Не указана"
                elif field['name'] == 'Отдел':
                    department = field.get('value') or "Не указан"

            # Сохраняем в базу
            cursor.execute("""
                INSERT OR REPLACE INTO employees (id, name, email, city, job_title, department)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, name, email, city, job_title, department))
            conn.commit()
            logger.info(f"User {user_id} saved to database: {name}, {email}")
            return user_data

    conn.close()
    return None

# Функция для получения координат города с использованием кэширования
def get_coordinates(city: str, cache: dict) -> list:
    if not city or city == "No city":
        return None
    if city in cache:
        return cache[city]
    g = geocoder.osm(city, headers={'User-Agent': 'FT_map/1.0 (imatveev@futuretoday.ru)'})
    if g.ok:
        cache[city] = g.latlng
        return g.latlng
    else:
        logger.warning(f"Город {city} не найден в геокодере.")
        return None

# Главная страница как статический файл
@app.get("/", response_class=HTMLResponse)
async def get_home():
    with open(os.path.join("app", "static", "index.html"), "r", encoding="utf-8") as file:
        html_content = file.read()
    return HTMLResponse(content=html_content)

# Эндпоинт для генерации карты
@app.get("/map", response_class=HTMLResponse)
async def get_map():
    user_ids = range(1, 1400)  # Оставил 50 для примера, можно вернуть 1400
    map = folium.Map(location=[55.7558, 37.6173], zoom_start=5)  # Центр карты — Москва

    city_employees = {}
    coordinates_cache = {}

    for user_id in user_ids:
        user_data = get_or_fetch_user_data(user_id)
        if user_data:
            user = user_data['user']
            email = user.get('mail', '')
            name = f"{user['firstname']} {user['lastname']}"

            if not email.endswith('@futuretoday.ru'):
                logger.info(f"User {user_id} skipped: email {email} does not end with @futuretoday.ru")
                continue

            city = "No city"
            job_title = "Не указана"
            department = "Не указан"
            for field in user.get('custom_fields', []):
                if field['name'] == 'Город проживания':
                    city = field.get('value') or "No city"
                elif field['name'] == 'Должность':
                    job_title = field.get('value') or "Не указана"
                elif field['name'] == 'Отдел':
                    department = field.get('value') or "Не указан"

            logger.info(f"User {user_id}: Email: {email}, Город: {city}, Должность: {job_title}, Отдел: {department}")

            if city != "No city":
                if city not in city_employees:
                    city_employees[city] = []
                city_employees[city].append({
                    'name': name,
                    'email': email,
                    'job_title': job_title,
                    'department': department
                })
        else:
            logger.warning(f"Пользователь с ID {user_id} не найден.")
        time.sleep(1)  # Задержка только для API запросов

    for city, employees in city_employees.items():
        coordinates = get_coordinates(city, coordinates_cache)
        if coordinates:
            popup_html = f"<b>Сотрудники в городе {city}</b><br><ul>"
            for employee in employees:
                popup_html += (
                    f"<li>"
                    f"{employee['name']}<br>"
                    f"Email: {employee['email']}<br>"
                    f"Должность: {employee['job_title']}<br>"
                    f"Отдел: {employee['department']}"
                    f"</li>"
                )
            popup_html += "</ul>"

            folium.Marker(
                location=coordinates,
                popup=folium.Popup(popup_html, max_width=300)
            ).add_to(map)
        else:
            logger.warning(f"Не удалось получить координаты для города {city}")

    map_path = "employees_map.html"
    try:
        map.save(map_path)
        logger.info(f"Карта сохранена в {map_path}")
    except Exception as e:
        logger.error(f"Ошибка при сохранении карты: {e}")

    with open(map_path, "r", encoding="utf-8") as file:
        html_content = file.read()

    return HTMLResponse(content=html_content)