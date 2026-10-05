import requests

# Replace the URL with one from the Available Endpoints
url = "https://api.sectors.app/v2/companies/"
api_key = "240d3ca634429f46d37f8da324022e98f1e922f0731d20340f76a4c504316ae7"
headers = {"Authorization": api_key}

try:
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()
except requests.exceptions.HTTPError as err:
    raise SystemExit(err)