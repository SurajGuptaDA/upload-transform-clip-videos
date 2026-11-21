import requests
import os
from dotenv import load_dotenv
load_dotenv()

print(os.getenv("ACCESS_TOKEN"))
r = requests.get(
    "https://graph.facebook.com/v25.0/17963365248215725",
    params={"fields": "status_code,status", "access_token": os.getenv("ACCESS_TOKEN")},
)
print(r.json())