import os
import shutil
import zipfile
from datetime import datetime

def backup_file(src_path, source_root, backup_root, logger=print):
    relative_path = os.path.relpath(src_path, source_root)
    dest_path = os.path.join(backup_root, relative_path)

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    shutil.copy2(src_path, dest_path)  # keeps metadata
    logger(f"💾 Backed up: {relative_path}")

def compress_backup(backup_root, logger=print):
    date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    zip_path = os.path.join(os.path.dirname(backup_root), f"ImmichBackup_{date_str}.zip")

    logger(f"\n🗜️ Compressing backup to: {zip_path}")
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
        for root, _, files in os.walk(backup_root):
            for file in files:
                full_path = os.path.join(root, file)
                arcname = os.path.relpath(full_path, backup_root)
                zipf.write(full_path, arcname)
    logger("✅ Backup compressed.")

import hashlib

def compute_file_hash(filepath, chunk_size=65536):
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            sha256.update(chunk)
    return sha256.hexdigest()

