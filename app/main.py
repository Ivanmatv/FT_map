import requests
import geocoder
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
from dotenv import load_dotenv
import sqlite3
import json
import time
from .logger import get_logger

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

# Указываем путь к папке app/static
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
            city TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

# Инициализация базы данных
init_db()

# Функция для получения данных из Redmine API
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

# Функция для очистки названий городов
def clean_city_name(city):
    if not city:
        return None
    city = city.strip()
    if city in ["No city", "Ввести город", "Город проживания"]:
        return None
    mapping = {
        "Санкт Петербург": "Санкт-Петербург",
        "г. Петергоф, г. Санкт-Петербург": "Санкт-Петербург",
        "Пермь/Санкт-Петербург": "Санкт-Петербург",
        "Электросталь (МО)": "Электросталь",
        "Орехово-Зуево, Московская обл.": "Орехово-Зуево",
        "Пушкино, Московская область": "Пушкино",
        "Белград, Сербия": "Белград",
        "Нови Сад, Сербия": "Нови Сад",
    }
    return mapping.get(city, city)

# Функция для получения данных из базы или API
def get_or_fetch_user_data(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name, email, city FROM employees WHERE id = ?", (user_id,))
    result = cursor.fetchone()

    if result:
        name, email, city = result
        logger.debug(f"User {user_id} found in database: {name}, {email}, {city}")
        return {
            'user': {
                'id': user_id,
                'firstname': name.split()[0],
                'lastname': ' '.join(name.split()[1:]),
                'mail': email,
                'custom_fields': [{'name': 'Город проживания', 'value': city}]
            }
        }

    user_data = get_user_data(user_id)
    if user_data:
        user = user_data['user']
        email = user.get('mail', '')
        if email.endswith('@futuretoday.ru'):
            name = f"{user['firstname']} {user['lastname']}"
            city = "No city"
            for field in user.get('custom_fields', []):
                if field['name'] == 'Город проживания':
                    city = field.get('value') or "No city"
            city = clean_city_name(city) or "No city"
            cursor.execute("""
                INSERT OR REPLACE INTO employees (id, name, email, city)
                VALUES (?, ?, ?, ?)
            """, (user_id, name, email, city))
            conn.commit()
            logger.info(f"User {user_id} saved to database: {name}, {email}, {city}")
            return user_data

    conn.close()
    logger.warning(f"User {user_id} not found in API")
    return None

# Функция для получения всех сотрудников
def get_all_employees():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, email, city FROM employees")
    employees = [
        {'id': row[0], 'name': row[1], 'email': row[2], 'city': row[3]}
        for row in cursor.fetchall()
    ]
    conn.close()
    logger.info(f"Извлечено {len(employees)} сотрудников из базы данных")
    return employees

# Функция для получения координат города
def get_coordinates(city: str, cache: dict) -> list:
    if not city or city == "No city":
        logger.warning(f"Город '{city}' пропущен")
        return None
    if city in cache:
        return cache[city]
    g = geocoder.osm(city, headers={'User-Agent': 'FT_map/1.0 (imatveev@futuretoday.ru)'})
    if g.ok:
        cache[city] = g.latlng
        logger.info(f"Координаты для города {city}: {g.latlng}")
        return g.latlng
    logger.warning(f"Город {city} не найден в геокодере")
    return None

# Модель для валидации входных данных
class UserRange(BaseModel):
    start_id: int
    end_id: int

# Эндпоинт для добавления новых сотрудников
@app.post("/add_users")
async def add_users(user_range: UserRange):
    start_id = user_range.start_id
    end_id = user_range.end_id

    if start_id < 1 or end_id < start_id:
        return {"message": "Некорректный диапазон ID", "status": "error"}

    added_count = 0
    for user_id in range(start_id, end_id + 1):
        user_data = get_or_fetch_user_data(user_id)
        if user_data and user_data['user']['mail'].endswith('@futuretoday.ru'):
            added_count += 1
        time.sleep(0.5)  # Задержка для избежания лимитов API

    logger.info(f"Добавлено {added_count} новых сотрудников из диапазона {start_id}-{end_id}")
    return {"message": "Сотрудники успешно добавлены", "added_count": added_count, "status": "success"}

# Главная страница
@app.get("/", response_class=HTMLResponse)
async def get_home():
    with open(os.path.join("app", "static", "index.html"), "r", encoding="utf-8") as file:
        html_content = file.read()
    return HTMLResponse(content=html_content)

# Эндпоинт для карты
@app.get("/map", response_class=HTMLResponse)
async def get_map():
    employees = get_all_employees()
    city_employees = {}
    coordinates_cache = {}

    for employee in employees:
        city = clean_city_name(employee['city'])
        if city:
            if city not in city_employees:
                city_employees[city] = []
            city_employees[city].append({
                'name': employee['name'],
                'email': employee['email']
            })
            logger.info(f"Сгруппировано {len(city_employees[city])} сотрудников для города {city}")
        else:
            logger.warning(f"Сотрудник {employee['name']} пропущен: город не указан")

    city_data = {}
    for city, emp_list in city_employees.items():
        coordinates = get_coordinates(city, coordinates_cache)
        if coordinates:
            city_data[city] = {
                'coordinates': coordinates,
                'employees': emp_list
            }
            logger.info(f"Город {city} добавлен на карту с {len(emp_list)} сотрудниками")

    html_content = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Карта сотрудников</title>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <style>
            body { margin: 0; padding: 0; font-family: Arial, sans-serif; }
            #container { display: flex; height: 100vh; }
            #sidebar {
                width: 300px;
                background-color: #f8f9fa;
                padding: 20px;
                overflow-y: auto;
                border-right: 1px solid #ddd;
            }
            #map { flex: 1; height: 100%; }
            h2 { font-size: 1.5em; margin-bottom: 10px; }
            ul { list-style: none; padding: 0; }
            li { margin-bottom: 10px; }
            .employee { border-bottom: 1px solid #eee; padding-bottom: 5px; }
        </style>
    </head>
    <body>
        <div id="container">
            <div id="sidebar">
                <h2>Сотрудники</h2>
                <div id="employee-list">Выберите город на карте</div>
            </div>
            <div id="map"></div>
        </div>
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
        <script>
            const cityData = """ + json.dumps(city_data) + """;
            const map = L.map('map').setView([55.7558, 37.6173], 5);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            }).addTo(map);

            for (const city in cityData) {
                const { coordinates, employees } = cityData[city];
                const marker = L.marker(coordinates).addTo(map);
                marker.on('click', () => {
                    const sidebar = document.getElementById('employee-list');
                    sidebar.innerHTML = `<h3>Сотрудники в городе ${city}</h3><ul>` + 
                        employees.map(emp => 
                            `<li class="employee"><strong>${emp.name}</strong><br>Email: ${emp.email}</li>`
                        ).join('') + `</ul>`;
                });
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)