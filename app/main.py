import requests
import geocoder
import folium
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from .logger import get_logger
import time
import os

# Инициализируем логгер
logger = get_logger()

REDMINE_URL = "https://tasks.fut.ru"
API_KEY = "fc3fb4d72858a7dbbf747dceb6e99325dbed58b2"

app = FastAPI()

# Подключаем статические файлы из папки "static"
app.mount("/static", StaticFiles(directory=os.path.join("app", "static")), name="static")

# Главная страница как статический файл
@app.get("/", response_class=HTMLResponse)
async def get_home():
    with open(os.path.join("app", "static", "index.html"), "r", encoding="utf-8") as file:
        html_content = file.read()
    return HTMLResponse(content=html_content)

# Функция для получения данных о пользователе
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

# Эндпоинт для генерации карты
@app.get("/map", response_class=HTMLResponse)
async def get_map():
    user_ids = range(1, 50)  # Оставил 50 для примера, можно вернуть 1400
    map = folium.Map(location=[55.7558, 37.6173], zoom_start=5)  # Центр карты — Москва

    city_employees = {}
    coordinates_cache = {}

    for user_id in user_ids:
        user_data = get_user_data(user_id)
        if user_data:
            name = f"{user_data['user']['firstname']} {user_data['user']['lastname']}"
            city = "No city"
            for field in user_data['user']['custom_fields']:
                if field['name'] == 'Город проживания':
                    city = field['value'] or "No city"
                    break
            logger.info(f"User {user_id}: Город проживания: {city}")

            if city != "No city":
                if city not in city_employees:
                    city_employees[city] = []
                city_employees[city].append(name)
        else:
            logger.warning(f"Пользователь с ID {user_id} не найден.")
        time.sleep(1)

    for city, employees in city_employees.items():
        coordinates = get_coordinates(city, coordinates_cache)
        if coordinates:
            popup_html = f"<b>Сотрудники в городе {city}</b><br><ul>"
            for employee in employees:
                popup_html += f"<li>{employee}</li>"
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