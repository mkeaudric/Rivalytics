import requests
import os

# Replace the URL with one from the Available Endpoints
url = "https://api.sectors.app/v2/companies/"

api_key = os.getenv("SECTORS_API_KEY")
if not api_key:
    raise ValueError("API key not found! Ensure the SECTORS_API_KEY environment variable is set.")

headers = {"Authorization": api_key}

try:
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()
except requests.exceptions.HTTPError as err:
    raise SystemExit(err)