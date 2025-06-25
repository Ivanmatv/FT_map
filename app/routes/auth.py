from fastapi import APIRouter, Request
from ..config import PASSWORD
import secrets

router = APIRouter()

# Хранилище токена авторизации
token_store = {}


@router.post("/login")
async def login(request: Request):
    """Эндпоинт входа в приложение"""
    data = await request.json()
    if data.get("password") == PASSWORD:
        token = secrets.token_urlsafe(32)
        token_store[token] = True
        return {"status": "success", "token": token}
    return {"status": "error", "message": "Неверный пароль"}


@router.post("/check_token")
async def check_token(request: Request):
    """Эндпоинт проверки токена авторизации"""
    data = await request.json()
    token = data.get("token")
    if token in token_store:
        return {"status": "success"}
    return {"status": "error", "message": "Недействительный токен"}
