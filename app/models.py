from pydantic import BaseModel


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
