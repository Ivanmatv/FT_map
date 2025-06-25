from fastapi import APIRouter
from fastapi.responses import HTMLResponse
import os

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def get_home():
    """Эндпоинт главной страницы"""
    with open(os.path.join(os.path.dirname(__file__), "..", "static", "index.html"), "r", encoding="utf-8") as file:
        html_content = file.read()
    return HTMLResponse(content=html_content)
