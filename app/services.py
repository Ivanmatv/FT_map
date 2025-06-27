import json
import requests
import geocoder
import time
import gspread
import sqlite3
import redis

from oauth2client.service_account import ServiceAccountCredentials

from .config import REDMINE_URL, API_KEY, GOOGLE_SHEET_KEY, CREDENTIALS_FILE, logger, REDIS_HOST
from .database import get_or_fetch_user_data, get_all_employees
from .state import map_data_cache, progress_store

# Инициализация Redis-клиента
redis_client = redis.Redis(host=REDIS_HOST, db=0, decode_responses=True)


def get_user_data(user_id: int) -> dict:
    """Получени пользователей из Redmine"""
    url = f"{REDMINE_URL}/users/{user_id}.json"
    headers = {'X-Redmine-API-Key': API_KEY}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching data for user {user_id}: {e}")
        return None


def clean_city_name(city):
    """Поправление название города"""
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


def get_coordinates(city: str, cache: dict) -> list:
    """Получение координад города"""
    if not city or city == "No city":
        logger.warning(f"Город '{city}' пропущен")
        return None
    # Если координаты уже в кэше, возвращаем их
    if city in cache:
        return cache[city]
    # Запрос к геокодеру
    g = geocoder.osm(city, headers={'User-Agent': 'FT_map/1.0 (imatveev@futuretoday.ru)'})
    if g.ok:
        cache[city] = g.latlng
        logger.info(f"Координаты для города {city}: {g.latlng}")
        return g.latlng
    logger.warning(f"Город {city} не найден в геокодере")
    return None


def process_users(start_id: int, end_id: int, task_id: str):
    """Филтрация пользователй FT"""
    logger.info(f"Starting background task {task_id} for range {start_id}-{end_id}")
    progress_store[task_id] = {'progress': 0, 'error': None, 'message': None, 'added_count': 0}
    added_count = 0

    try:
        for user_id in range(start_id, end_id + 1):
            user_data = get_or_fetch_user_data(user_id)
            # отбираем тольок пользователей по корпоративной почте
            if user_data and user_data['user'].get('mail') and user_data['user']['mail'].endswith('@futuretoday.ru'):    
                added_count += 1
            progress_store[task_id]['progress'] += 1
            progress_store[task_id]['added_count'] = added_count
            logger.debug(f"Task {task_id}: Processed user {user_id}, progress {progress_store[task_id]['progress']}, added {added_count}")
            time.sleep(0.5)

        logger.info(f"Task {task_id}: Added {added_count} new employees from range {start_id}-{end_id}")
        update_map_data_cache()     # Обновляем кэш после добавления сотрудников

    except Exception as e:
        progress_store[task_id]['error'] = True
        progress_store[task_id]['message'] = str(e)
        logger.error(f"Task {task_id}: Error processing users: {e}")

    finally:
        time.sleep(2)
        logger.debug(f"Task {task_id}: Cleaning up progress_store")
        progress_store.pop(task_id, None)


def update_map_data_cache():
    """Обновлоение кэша данных карты"""
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

    redis_client.set("map_data_cache", json.dumps(map_data_cache))
    # logger.debug(f"map_data_cache: {map_data_cache}")
    logger.info("Кэш данных карты успешно обновлён")


# Пока не нужен
# async def periodic_cache_update():            
#     """Автоматическое обновление данных на карте"""
#     while True:
#         update_map_data_cache()
#         await asyncio.sleep(3600)  # Обновление каждый час


def get_google_sheet():
    """Получение данных из гугл таблицы"""
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(GOOGLE_SHEET_KEY).sheet1


def process_sheet_update(db_ids, sheet_data, task_id):
    """Обновление данных сотрудников (должность, отдел)"""
    try:
        from .database import DB_PATH
        updated_count = 0
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()

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
        logger.info(f"Обновлено {updated_count} записей")

    except Exception as e:
        progress_store[task_id]["error"] = True
        progress_store[task_id]["message"] = f"Ошибка: {str(e)}"
        logger.error(f"Sheet update failed: {str(e)}")
    finally:
        time.sleep(5)
        progress_store.pop(task_id, None)
