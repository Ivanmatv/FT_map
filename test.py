import requests
from requests.auth import HTTPBasicAuth

response = requests.get(
    "https://www.redmine.org/users.json?limit=1000",
    headers={"X-Redmine-API-Key": "d18da853ad9642a79a69ce90b42b8089fc0ab941"},
    auth=HTTPBasicAuth('imatveev', '0@Rx5rFj')
)

headers = {"X-Redmine-API-Key": "d18da853ad9642a79a69ce90b42b8089fc0ab941"}
response = requests.get("https://tasks.fut.ru/users.json?limit=1000", headers=headers)

# Печать заголовков и текста ответа для диагностики
print(f"Status Code: {response.status_code}")
print(f"Response Headers: {response.headers}")
print(f"Response Body: {response.text}")
print(f"Response Body: {response}")