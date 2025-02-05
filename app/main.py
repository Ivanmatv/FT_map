from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import requests
from collections import defaultdict
import asyncio
from typing import Optional, List, Dict
from pydantic import BaseModel

# Импорт и инициализация логгера
from .logger import get_logger
logger = get_logger()

app = FastAPI()
templates = Jinja2Templates(directory="templates")

REDMINE_URL = "https://www.redmine.org"
API_KEY = "d18da853ad9642a79a69ce90b42b8089fc0ab941"
CITY_FIELD_NAME = "city"

# Кэш координат городов
city_coords_cache = {
    "Москва": (55.7558, 37.6173),
    "Санкт-Петербург": (59.9343, 30.3351),
    "Екатеринбург": (56.8389, 60.6057),
}

@app.on_event("startup")
async def startup_event():
    logger.info("Сервер запущен")
    logger.debug(f"Конфигурация: REDMINE_URL={REDMINE_URL}, CITY_FIELD={CITY_FIELD_NAME}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Сервер остановлен")

async def fetch_users():
    """Получение пользователей из Redmine с логированием"""
    logger.debug("Начало получения пользователей из Redmine")
    url = f"{REDMINE_URL}/users.json?limit=1000"
    headers = {"X-Redmine-API-Key": API_KEY}
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        logger.info(f"Успешно получено {len(response.json().get('users', []))} пользователей")
        return response.json().get("users", [])
    except requests.exceptions.HTTPError as e:
        logger.error(f"Ошибка HTTP при запросе пользователей: {e.response.status_code}")
        raise
    except Exception as e:
        logger.critical(f"Критическая ошибка при запросе пользователей: {str(e)}", exc_info=True)
        raise

def process_users(users):
    """Обработка данных пользователей с логированием"""
    logger.debug("Начало обработки данных пользователей")
    city_stats = defaultdict(int)
    
    try:
        for index, user in enumerate(users):
            city = None
            for cf in user.get("custom_fields", []):
                if cf.get("name") == CITY_FIELD_NAME and cf.get("value"):
                    city = cf["value"]
                    break
            
            if city:
                if city in city_coords_cache:
                    city_stats[city] += 1
                    logger.debug(f"Пользователь {index}: город {city}")
                else:
                    logger.warning(f"Город {city} не найден в кэше координатов")
            else:
                logger.debug(f"Пользователь {index}: город не указан")
        
        logger.info(f"Обработано {len(users)} пользователей, найдено {len(city_stats)} городов")
        return city_stats
    
    except Exception as e:
        logger.error(f"Ошибка обработки пользователей: {str(e)}", exc_info=True)
        raise

@app.get("/map-data")
async def get_map_data():
    """Эндпоинт данных для карты"""
    logger.info("Запрос данных для карты")
    try:
        users = await fetch_users()
        city_stats = process_users(users)
        
        features = []
        for city, count in city_stats.items():
            lat, lon = city_coords_cache.get(city, (None, None))
            if lat and lon:
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {"city": city, "count": count}
                })
            else:
                logger.warning(f"Пропущен город {city} - отсутствуют координаты")
        
        logger.debug(f"Сформировано {len(features)} объектов для карты")
        return JSONResponse({"type": "FeatureCollection", "features": features})
    
    except Exception as e:
        logger.error(f"Ошибка формирования данных карты: {str(e)}")
        return JSONResponse(
            {"error": "Internal Server Error"}, 
            status_code=500
        )

@app.get("/map", response_class=HTMLResponse)
async def map_page(request: Request):
    """Страница с картой"""
    logger.info("Запрос страницы с картой")
    return templates.TemplateResponse("map.html", {"request": request})

@app.get("/users")
async def get_users(email_domain: str = Query(...)):
    """Поиск пользователей по домену"""
    logger.info(f"Поиск пользователей по домену: @{email_domain}")
    try:
        users = await fetch_users()
        filtered_users = [
            user for user in users 
            if user.get("mail", "").endswith(f"@{email_domain}")
        ]
        
        logger.info(f"Найдено {len(filtered_users)} пользователей с доменом @{email_domain}")
        return JSONResponse(
            content=[extract_user_data(user) for user in filtered_users],
            headers={"X-Domain-Filter": email_domain}
        )
    except Exception as e:
        logger.error(f"Ошибка поиска пользователей: {str(e)}")
        return JSONResponse(
            {"error": "Internal Server Error"}, 
            status_code=500
        )

def extract_user_data(user):
    """Извлечение данных пользователя с обработкой ошибок"""
    try:
        return {
            "id": user["id"],
            "name": f"{user.get('firstname', '')} {user.get('lastname', '')}".strip(),
            "email": user.get("mail", ""),
            "city": next(
                (cf["value"] for cf in user.get("custom_fields", [])
                 if cf.get("name") == CITY_FIELD_NAME and cf.get("value")),
                "Не указан"
            )
        }
    except KeyError as e:
        logger.warning(f"Ошибка извлечения данных пользователя: отсутствует ключ {str(e)}")
        return {"error": "Неполные данные пользователя"}