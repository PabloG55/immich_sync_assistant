import requests

def upload_file_to_immich(file_path, immich_url, api_key, logger=print):
    import os
    import requests
    from datetime import datetime

    stats = os.stat(file_path)
    headers = {
        'Accept': 'application/json',
        'x-api-key': api_key
    }

    data = {
        'deviceAssetId': f'{file_path}-{stats.st_mtime}',
        'deviceId': 'python',
        'fileCreatedAt': datetime.fromtimestamp(stats.st_mtime).isoformat(),
        'fileModifiedAt': datetime.fromtimestamp(stats.st_mtime).isoformat(),
        'isFavorite': 'false',
    }

    files = {
        'assetData': open(file_path, 'rb')
    }

    response = requests.post(f'{immich_url}/api/assets', headers=headers, data=data, files=files)

    if response.status_code == 201:
        return response.json()["id"], "created"
    elif response.status_code == 200 and response.json().get("status") == "duplicate":
        return response.json()["id"], "duplicate"
    else:
        logger(f"❌ Upload failed: {file_path}")
        logger(f"Status Code: {response.status_code}")
        logger(f"Response: {response.text}")
        return None, "error"




def get_or_create_album(album_name, immich_url, api_key):
    headers = {"x-api-key": api_key}

    res = requests.get(f"{immich_url}/api/albums", headers=headers)
    if res.status_code == 200:
        for album in res.json():
            if album["albumName"] == album_name:
                return album["id"]

    res = requests.post(f"{immich_url}/api/albums", headers=headers, json={"albumName": album_name})
    if res.status_code == 201:
        return res.json()["id"]

    return None


def add_asset_to_album(asset_id, album_id, immich_url, api_key):
    headers = {"x-api-key": api_key}
    res = requests.put(
        f"{immich_url}/api/albums/{album_id}/assets",
        headers=headers,
        json={"ids": [asset_id]}
    )
    return res.status_code == 200
