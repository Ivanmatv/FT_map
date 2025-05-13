import requests


# URL Redmine API для пользователя с ID 956
url = "https://tasks.fut.ru/users/1221.json"
headers = {'X-Redmine-API-Key': 'fc3fb4d72858a7dbbf747dceb6e99325dbed58b2'}  # Замените на ваш API ключ

# Запрос к API
response = requests.get(url, headers=headers)

# Проверка на успешный ответ
if response.status_code == 200:
    user_data = response.json()  # Преобразуем ответ в JSON
    print(user_data)  # Выводим всю информацию о пользователе
else:
    print(f"Ошибка при запросе данных о пользователе: {response.status_code}")


# import requests
# import folium

# # URL Redmine API для пользователя с ID 956
# url = "https://tasks.fut.ru/users/1298.json"
# headers = {'X-Redmine-API-Key': 'fc3fb4d72858a7dbbf747dceb6e99325dbed58b2'}  # Замените на ваш API ключ


# # Функция для получения координат города с помощью Nominatim API (или другого API)
# def get_coordinates(city: str):
#     url = f"https://nominatim.openstreetmap.org/search?q={city}&format=json&addressdetails=1"
#     try:
#         response = requests.get(url)
#         data = response.json()
#         if data:
#             return [float(data[0]["lat"]), float(data[0]["lon"])]  # Возвращаем координаты
#     except Exception as e:
#         print(f"Ошибка при получении координат для города {city}: {e}")
#     return [55.7558, 37.6173]  # Если не получилось получить координаты, возвращаем Москву как запасной вариант


# response = requests.get(url, headers=headers)

# # Проверка на успешный ответ
# if response.status_code == 200:
#     user_data = response.json()  # Преобразуем ответ в JSON
#     print(user_data)  # Выводим всю информацию о пользователе

#     # Извлекаем информацию о пользователе
#     name = user_data['user']['firstname'] + " " + user_data['user']['lastname']
#     city = user_data['user'].get('city', 'No city')  # Получаем город (если он есть)

#     # Создаем карту
#     map = folium.Map(location=[55.7558, 37.6173], zoom_start=5)  # Стартовые координаты для Москвы

#     # Если город указан, добавляем его на карту
#     if city != 'No city':
#         # Получаем координаты города через геокодирование (используем Nominatim API)
#         city_coordinates = get_coordinates(city)  # Эта функция будет описана ниже

#         # Добавляем маркер с городом
#         folium.Marker(
#             location=city_coordinates, 
#             popup=f"{name} - {city}"
#         ).add_to(map)
#     else:
#         print("Город не указан, карта будет пустой")

#     # Сохраняем карту в HTML
#     map_path = "employees_map.html"
#     try:
#         map.save(map_path)  # Сохраняем карту в файл
#         print(f"Карта сохранена в {map_path}")
#     except Exception as e:
#         print(f"Ошибка при сохранении карты: {e}")

# else:
#     print(f"Ошибка при запросе данных о пользователе: {response.status_code}")


