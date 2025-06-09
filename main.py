import os
import json
from utils.immich_api import (
    upload_file_to_immich,
    get_or_create_album,
    add_asset_to_album
)
from utils.file_utils import compress_backup
from utils.mtp_utils import pull_media_from_phone, delete_files_from_phone

# Load config
with open("config.json") as f:
    config = json.load(f)

IMMICH_URL = config["immich_url"]
API_KEY = config["api_key"]
BACKUP_DIR = config["temp_import_dir"]


def process_media():
    print("📥 Pulling files from phone...")
    pulled_paths = pull_media_from_phone(destination=BACKUP_DIR)

    custom_album = input("🎨 Do you want to use a custom album name for this run? (leave blank to auto-detect): ").strip()

    print("🚀 Starting upload process...")
    stats = {
        "total": 0,
        "uploaded": 0,
        "duplicates": 0,
        "failed": 0
    }

    for root, _, files in os.walk(BACKUP_DIR):
        for file in files:
            if file.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".heic", ".gif")):
                stats["total"] += 1
                full_path = os.path.join(root, file)
                print(f"📤 Uploading: {full_path}")
                asset_id, upload_status = upload_file_to_immich(full_path, IMMICH_URL, API_KEY)

                if asset_id:
                    if custom_album:
                        album_name = custom_album
                    else:
                        parts = os.path.basename(root).split("_")
                        album_name = "_".join(parts[2:]) if len(parts) > 2 else parts[1] if len(parts) > 1 else parts[0]
                    album_id = get_or_create_album(album_name, IMMICH_URL, API_KEY)
                    if album_id:
                        added = add_asset_to_album(asset_id, album_id, IMMICH_URL, API_KEY)
                        print(f"📁 Added to album '{album_name}': {added}")

                    if upload_status == "duplicate":
                        stats["duplicates"] += 1
                        print("♻️ File already exists in Immich (duplicate).")
                    else:
                        stats["uploaded"] += 1
                else:
                    stats["failed"] += 1
                    print("❌ Upload failed.")

    compress_backup(BACKUP_DIR)

    # Sync summary
    print("\n📊 Sync Summary:")
    print(f"🔹 Total media files found: {stats['total']}")
    print(f"🔹 Uploaded: {stats['uploaded']}")
    print(f"🔹 Duplicates skipped: {stats['duplicates']}")
    print(f"🔹 Failed uploads: {stats['failed']}")

    confirm = input("\n🗑️ Do you want to delete the pulled files from your phone? (y/N): ").strip().lower()
    if confirm == "y":
        print("🔄 Deleting pulled files from phone...")
        delete_files_from_phone(pulled_paths)
        print("✅ Done deleting from phone.")
    else:
        print("❎ Skipped deletion.")

    # Ask about deleting pulled files from PC
    confirm_pc = input(
        "\n🧹 Do you want to delete the pulled files from your PC (they're now zipped)? (y/N): ").strip().lower()
    if confirm_pc == "y":
        import shutil
        try:
            shutil.rmtree(BACKUP_DIR)
            print("🗑️ Local pulled media folder deleted successfully.")
        except Exception as e:
            print(f"❌ Failed to delete local folder: {e}")
    else:
        print("📁 Pulled media left in place.")



if __name__ == "__main__":
    process_media()
