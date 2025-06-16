import requests
import geocoder
from fastapi import FastAPI, BackgroundTasks, WebSocket, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os
import sqlite3
import time
import asyncio
import secrets
from dotenv import load_dotenv
from .logger import get_logger
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Загружаем переменные из .env
load_dotenv()

# Инициализируем логгер
logger = get_logger()

REDMINE_URL = "https://tasks.fut.ru"
API_KEY = os.getenv("API_KEY")
PASSWORD = os.getenv("PASSWORD")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

if not API_KEY:
    logger.error("API_KEY not found in .env file or is empty")
    raise ValueError("API_KEY not found in .env file or is empty")

if not PASSWORD:
    logger.error("PASSWORD not found in .env file or is empty")
    raise ValueError("PASSWORD not found in .env file or is empty")

if not ADMIN_PASSWORD:
    logger.error("ADMIN_PASSWORD not found in .env file or is empty")
    raise ValueError("ADMIN_PASSWORD not found in .env file or is empty")

app = FastAPI()

# Указываем путь к папке app/static
app.mount("/static", StaticFiles(directory=os.path.join("app", "static")), name="static")

# Подключение к SQLite базе данных
DB_PATH = "users.db"

# Хранилище токена авторизации
token_store = {}

# Хранилище токенов для админ-панели
admin_token_store = {}

# Хранилище прогресса для задач
progress_store = {}

# Глобальный кэш для данных карты
map_data_cache = {}

# Добавить в настройки
GOOGLE_SHEET_KEY = os.getenv("GOOGLE_SHEET_KEY")
CREDENTIALS_FILE = "credentials.json"  # Файл сервисного аккаунта Google


def get_google_sheet():
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(GOOGLE_SHEET_KEY).sheet1


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            city TEXT NOT NULL,
            department TEXT,  -- Новое поле: Отдел (опционально)
            position TEXT    -- Новое поле: Должность (опционально)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            visitor_id TEXT NOT NULL,
            visit_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


# Инициализация базы данных
init_db()


# Модель для проверки пароля
class LoginRequest(BaseModel):
    password: str


# Модель для проверки токена
class TokenRequest(BaseModel):
    token: str


# Модель для валидации входных данных
class UserRange(BaseModel):
    start_id: int
    end_id: int
    task_id: str


class SheetTask(BaseModel):
    task_id: str


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
    cursor.execute("SELECT name, email, city, department, position FROM employees WHERE id = ?", (user_id,))
    result = cursor.fetchone()

    if result:
        name, email, city, department, position = result
        logger.debug(f"User {user_id} found in database: {name}, {email}, {city}, {department}, {position}")
        return {
            'user': {
                'id': user_id,
                'firstname': name.split()[0],
                'lastname': ' '.join(name.split()[1:]),
                'mail': email,
                'custom_fields': [
                    {'name': 'Город проживания', 'value': city},
                    {'name': 'Отдел', 'value': department or ''},
                    {'name': 'Должность', 'value': position or ''}
                ]
            }
        }

    user_data = get_user_data(user_id)
    if user_data:
        user = user_data['user']
        email = user.get('mail', '')
        if email.endswith('@futuretoday.ru'):
            name = f"{user['firstname']} {user['lastname']}"
            city = "No city"
            department = None
            position = None
            for field in user.get('custom_fields', []):
                if field['name'] == 'Город проживания':
                    city = field.get('value') or "No city"
                elif field['name'] == 'Отдел':
                    department = field.get('value') or None
                elif field['name'] == 'Должность':
                    position = field.get('value') or None
            city = clean_city_name(city) or "No city"
            cursor.execute("""
                INSERT OR REPLACE INTO employees (id, name, email, city, department, position)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, name, email, city, department, position))
            conn.commit()
            logger.info(f"User {user_id} saved to database: {name}, {email}, {city}, {department}, {position}")
            return user_data

    conn.close()
    logger.warning(f"User {user_id} not found in API")
    return None


# Функция для получения всех сотрудников
def get_all_employees():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, email, city, department, position FROM employees")
    employees = [
        {
            'id': row[0],
            'name': row[1],
            'profile_url': f"{REDMINE_URL}/users/{row[0]}",
            'city': row[3],
            'department': row[4] if row[4] and row[4] != 'None' else None,
            'position': row[5] if row[5] and row[5] != 'None' else None
        }
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
            time.sleep(0.5)

        logger.info(f"Task {task_id}: Added {added_count} new employees from range {start_id}-{end_id}")
        update_map_data_cache()  # Обновляем кэш после добавления сотрудников

    except Exception as e:
        progress_store[task_id]['error'] = True
        progress_store[task_id]['message'] = str(e)
        logger.error(f"Task {task_id}: Error processing users: {e}")

    finally:
        time.sleep(2)
        logger.debug(f"Task {task_id}: Cleaning up progress_store")
        progress_store.pop(task_id, None)


# Функция подсчёта уникальных посетителей
def get_unique_visitors():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(DISTINCT visitor_id) FROM visits")
    unique_count = cursor.fetchone()[0]
    conn.close()
    return unique_count


# Функция подсчёта посетителей
def get_total_visits():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM visits")
    total_count = cursor.fetchone()[0]
    conn.close()
    return total_count


# Функция для записи посещения в базу данных
def record_visit(visitor_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO visits (visitor_id) VALUES (?)", (visitor_id,))
    conn.commit()
    conn.close()


# Функция для обновления кэша данных карты
def update_map_data_cache():
    global map_data_cache
    logger.info("Обновление кэша данных карты")
    employees = get_all_employees()
    city_employees = {}
    coordinates_cache = {}

    for employee in employees:
        city = clean_city_name(employee['city'])
        if city:
            if city not in city_employees:
                city_employees[city] = []
            employee_data = {
                'name': employee['name'],
                'profile_url': employee['profile_url']
            }
            if employee['department'] and employee['department'] != 'None':
                employee_data['department'] = employee['department']
            if employee['position'] and employee['position'] != 'None':
                employee_data['position'] = employee['position']
            city_employees[city].append(employee_data)

            logger.debug(f"Сгруппирован сотрудник {employee['name']} для города {city}")

    map_data_cache = []
    for city, emp_list in city_employees.items():
        emp_list.sort(key=lambda x: x['name'])
        if city == "Москва":
            coordinates = [55.778487, 37.672379]
            logger.info(f"Используются заданные координаты для Москвы: {coordinates}")
        else:
            coordinates = get_coordinates(city, coordinates_cache)
        if coordinates:
            marker_data = {
                'city': city,
                'coordinates': coordinates,
                'employees': emp_list
            }
            map_data_cache.append(marker_data)
            logger.info(f"Добавлены данные в кэш для города {city} с {len(emp_list)} сотрудниками")
        else:
            logger.warning(f"Координаты для города {city} не найдены")

    logger.info("Кэш данных карты успешно обновлён")


# Функция для периодического обновления кэша
async def periodic_cache_update():
    while True:
        update_map_data_cache()
        await asyncio.sleep(1800)  # Обновление каждые 60 минут


def process_sheet_update(db_ids, sheet_data, task_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        updated_count = 0

        for idx, user_id in enumerate(db_ids):
            sheet_row = next((row for row in sheet_data if row["#"] == user_id), None)
            if sheet_row:
                cursor.execute("""
                    UPDATE employees SET
                    department = ?,
                    position = ?
                    WHERE id = ?
                """, (
                    sheet_row.get("Отдел", ""),
                    sheet_row.get("Должность", ""),
                    user_id
                ))
                updated_count += 1

            progress_store[task_id]["processed"] = idx + 1
            time.sleep(0.1)

        conn.commit()
        progress_store[task_id]["message"] = f"Обновлено {updated_count} записей"
        progress_store[task_id]["status"] = "completed"

    except Exception as e:
        progress_store[task_id]["error"] = True
        progress_store[task_id]["message"] = f"Ошибка: {str(e)}"
        logger.error(f"Sheet update failed: {str(e)}")
    finally:
        conn.close()
        time.sleep(5)
        progress_store.pop(task_id, None)


# Запуск кэша при старте приложения
@app.on_event("startup")
async def startup_event():
    update_map_data_cache()  # Инициализация кэша при старте
    asyncio.create_task(periodic_cache_update())  # Запуск периодического обновления


@app.get("/map_data")
async def get_map_data():
    return map_data_cache


# Эндпоинт для подсчёта посетитлей
@app.get("/admin_stats")
async def get_admin_stats():
    unique_visitors = get_unique_visitors()
    total_visits = get_total_visits()
    return {"unique_visitors": unique_visitors, "total_visits": total_visits}


# Эндпоинт для авторизации
@app.post("/login")
async def login(request: Request):
    data = await request.json()
    if data.get("password") == PASSWORD:
        token = secrets.token_urlsafe(32)
        token_store[token] = True
        return {"status": "success", "token": token}
    return {"status": "error", "message": "Неверный пароль"}


@app.post("/check_token")
async def check_token(request: Request):
    data = await request.json()
    token = data.get("token")
    if token in token_store:
        return {"status": "success"}
    return {"status": "error", "message": "Недействительный токен"}


# Эндпоинт для авторизации в админ-панели
@app.post("/admin_login")
async def admin_login(login_request: LoginRequest):
    if login_request.password == ADMIN_PASSWORD:
        token = secrets.token_urlsafe(32)
        admin_token_store[token] = True
        logger.info("Успешная авторизация в админ-панели")
        return {"status": "success", "token": token}
    logger.warning("Неудачная попытка авторизации в админ-панели")
    return {"status": "error", "message": "Неверный пароль"}


# Эндпоинт для проверки токена админ-панели
@app.post("/check_admin_token")
async def check_admin_token(token_request: TokenRequest):
    if token_request.token in admin_token_store:
        logger.debug("Токен админ-панели действителен")
        return {"status": "success"}
    logger.warning("Недействительный токен админ-панели")
    return {"status": "error", "message": "Недействительный токен"}


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


# Страница админ-панели
@app.get("/admin", response_class=HTMLResponse)
async def get_admin_panel(request: Request):
    admin_token = request.cookies.get("admin_token")
    if not admin_token or admin_token not in admin_token_store:
        logger.warning("Попытка доступа к админ-панели без авторизации")
        with open(os.path.join("app", "static", "admin.html"), "r", encoding="utf-8") as file:
            html_content = file.read()
        return HTMLResponse(content=html_content)
    with open(os.path.join("app", "static", "admin.html"), "r", encoding="utf-8") as file:
        html_content = file.read()
    return HTMLResponse(content=html_content)


# WebSocket для отправки данных карты в реальном времени
@app.websocket("/ws/map")
async def websocket_map(websocket: WebSocket):
    await websocket.accept()
    try:
        for marker_data in map_data_cache:
            await websocket.send_json(marker_data)
            logger.info(f"Отправлены кэшированные данные для города {marker_data['city']}")
            await asyncio.sleep(0.005)  # Небольшая задержка для имитации потоковой передачи
        await websocket.send_json({'status': 'complete'})
        logger.info("Все кэшированные данные карты отправлены")
    except Exception as e:
        logger.error(f"Ошибка в WebSocket: {e}")
        await websocket.send_json({'status': 'error', 'message': str(e)})
    finally:
        await websocket.close()


# Эндпоинт для карты
@app.get("/map", response_class=HTMLResponse)
async def get_map():
    with open(os.path.join("app", "static", "employees_map.html"), "r", encoding="utf-8") as file:
        html_content = file.read()
    return HTMLResponse(content=html_content)


@app.post("/update_from_sheet")
async def update_from_sheet(task: SheetTask, background_tasks: BackgroundTasks):
    try:
        sheet = get_google_sheet()
        all_records = sheet.get_all_records()
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM employees")
        db_ids = [row[0] for row in cursor.fetchall()]
        conn.close()

        progress_store[task.task_id] = {
            "processed": 0,
            "total": len(db_ids),
            "message": "",
            "error": False
        }

        background_tasks.add_task(process_sheet_update, db_ids, all_records, task.task_id)
        return {"status": "success", "total_users": len(db_ids), "task_id": task.task_id}
    except Exception as e:
        logger.error(f"Sheet update error: {str(e)}")
        return {"status": "error", "message": str(e)}


@app.get("/sheet_progress/{task_id}")
async def get_sheet_progress(task_id: str):
    return progress_store.get(task_id, {"processed": 0, "error": True, "message": "Task not found"})


# Эндпоинт для ручного обнолвления кэша
@app.get("/refresh_cache")
async def refresh_cache():
    update_map_data_cache()
    return {"message": "Map data cache refreshed"}


# Эндпоинт для отслеживания посещений карты
@app.get("/track_visit")
async def track_visit(request: Request):
    # Генерация уникального ID посетителя (можно использовать сессионные cookies или IP-адрес)
    visitor_id = request.cookies.get("visitor_id")
    if not visitor_id:
        visitor_id = secrets.token_urlsafe(16)  # Создаём уникальный идентификатор для посетителя
        response = HTMLResponse(content="Карта сотрудников", status_code=200)
        response.set_cookie("visitor_id", visitor_id, max_age=60*60*24)  # Храним ID посетителя в cookie
    else:
        response = HTMLResponse(content="Карта сотрудников", status_code=200)

    # Регистрируем посещение
    record_visit(visitor_id)

    return response