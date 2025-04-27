import requests
import geocoder
from fastapi import FastAPI, BackgroundTasks, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
from dotenv import load_dotenv
import sqlite3
import json
import time
import asyncio
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

# Хранилище прогресса для задач
progress_store = {}

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
    task_id: str

# Функция для фоновой обработки пользователей
def process_users(start_id: int, end_id: int, task_id: str):
    logger.info(f"Starting background task {task_id} for range {start_id}-{end_id}")
    progress_store[task_id] = {'progress': 0, 'error': None, 'message': None, 'added_count': 0}
    added_count = 0

    try:
        for user_id in range(start_id, end_id + 1):
            user_data = get_or_fetch_user_data(user_id)
            if user_data and user_data['user']['mail'].endswith('@futuretoday.ru'):
                added_count += 1
            progress_store[task_id]['progress'] += 1
            progress_store[task_id]['added_count'] = added_count
            logger.debug(f"Task {task_id}: Processed user {user_id}, progress {progress_store[task_id]['progress']}, added {added_count}")
            time.sleep(0.5)  # Задержка для избежания лимитов API

        logger.info(f"Task {task_id}: Added {added_count} new employees from range {start_id}-{end_id}")

    except Exception as e:
        progress_store[task_id]['error'] = True
        progress_store[task_id]['message'] = str(e)
        logger.error(f"Task {task_id}: Error processing users: {e}")

    finally:
        time.sleep(2)  # Даём клиенту время получить финальный прогресс
        logger.debug(f"Task {task_id}: Cleaning up progress_store")
        progress_store.pop(task_id, None)

# Эндпоинт для получения прогресса
@app.get("/progress/{task_id}")
async def get_progress(task_id: str):
    progress = progress_store.get(task_id, {'progress': 0, 'error': None, 'message': None, 'added_count': 0})
    logger.debug(f"Progress requested for task {task_id}: {progress}")
    return progress

# Эндпоинт для добавления новых сотрудников
@app.post("/add_users")
async def add_users(user_range: UserRange, background_tasks: BackgroundTasks):
    start_id = user_range.start_id
    end_id = user_range.end_id
    task_id = user_range.task_id

    if start_id < 1 or end_id < start_id:
        logger.warning(f"Invalid range {start_id}-{end_id} for task {task_id}")
        return {"message": "Некорректный диапазон ID", "status": "error"}

    # Запускаем обработку в фоновом режиме
    background_tasks.add_task(process_users, start_id, end_id, task_id)
    logger.info(f"Scheduled background task {task_id} for range {start_id}-{end_id}")
    return {"message": "Обработка запущена", "task_id": task_id, "status": "success"}

# Главная страница
@app.get("/", response_class=HTMLResponse)
async def get_home():
    with open(os.path.join("app", "static", "index.html"), "r", encoding="utf-8") as file:
        html_content = file.read()
    return HTMLResponse(content=html_content)

# WebSocket для отправки данных карты в реальном времени
@app.websocket("/ws/map")
async def websocket_map(websocket: WebSocket):
    await websocket.accept()
    try:
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

        for city, emp_list in city_employees.items():
            emp_list.sort(key=lambda x: x['name'])
            coordinates = get_coordinates(city, coordinates_cache)
            if coordinates:
                marker_data = {
                    'city': city,
                    'coordinates': coordinates,
                    'employees': emp_list
                }
                await websocket.send_json(marker_data)
                logger.info(f"Отправлены данные для города {city} с {len(emp_list)} сотрудниками")
                await asyncio.sleep(0.1)  # Небольшая задержка для имитации потоковой передачи
            else:
                logger.warning(f"Координаты для города {city} не найдены")

        await websocket.send_json({'status': 'complete'})
        logger.info("Все данные карты отправлены")
    except Exception as e:
        logger.error(f"Ошибка в WebSocket: {e}")
        await websocket.send_json({'status': 'error', 'message': str(e)})
    finally:
        await websocket.close()

# Эндпоинт для карты
@app.get("/map", response_class=HTMLResponse)
async def get_map():
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Employees Map</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {
                margin: 0;
                font-family: Arial, sans-serif;
            }
            #sidebar {
                position: absolute;
                top: 0;
                left: 0;
                width: 300px;
                height: 100%;
                overflow-y: auto;
                background: #f8f8f8;
                border-right: 1px solid #ccc;
                padding: 10px;
                box-sizing: border-box;
                z-index: 1000;
            }
            #sidebar h3 {
                margin-top: 0;
            }
            #employeeList li {
                padding: 4px 0;
                border-bottom: 1px solid #ddd;
            }
            #map {
                position: absolute;
                top: 0;
                left: 300px;
                right: 0;
                bottom: 0;
            }
        </style>
        <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
        <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    </head>
    <body>
        <div id="sidebar">
            <h3>Сотрудники</h3>
            <ul id="employeeList"></ul>
        </div>
        <div id="map"></div>
        <script>
            var map = L.map('map').setView([55.7558, 37.6173], 5);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap contributors'
            }).addTo(map);

            function showEmployees(employees) {
                var list = document.getElementById("employeeList");
                list.innerHTML = "";
                employees.forEach(function(emp) {
                    var li = document.createElement("li");
                    li.innerHTML = `<strong>${emp.name}</strong><br>Email: ${emp.email}`;
                    list.appendChild(li);
                });
            }

            var ws = new WebSocket("ws://" + window.location.host + "/ws/map");
            ws.onmessage = function(event) {
                var data = JSON.parse(event.data);
                console.log("Получены данные:", data);
                if (data.status === 'complete') {
                    console.log("Все данные карты получены");
                    return;
                }
                if (data.status === 'error') {
                    console.error("Ошибка:", data.message);
                    return;
                }
                var marker = L.marker(data.coordinates)
                    .addTo(map)
                    .bindPopup(data.city);
                marker.on('click', function() {
                    console.log("Маркер для города " + data.city + " нажат");
                    showEmployees(data.employees);
                });
            };
            ws.onclose = function() {
                console.log("WebSocket соединение закрыто");
            };
            ws.onerror = function(error) {
                console.error("WebSocket ошибка:", error);
            };
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)