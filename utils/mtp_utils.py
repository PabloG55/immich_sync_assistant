import shlex
import subprocess
import os
import json
import sys
from datetime import datetime
import piexif
from utils.file_utils import compute_file_hash

HASH_FILE = "seen_hashes.json"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0

def run_quiet(cmd, **kwargs):
    return subprocess.run(cmd, creationflags=NO_WINDOW, **kwargs)

def get_android_file_datetime(filepath, logger=print):
    import shlex

    result = run_quiet(
        ["adb", "shell", f"stat -c %y '{filepath}'"],
        capture_output=True, text=True, encoding="utf-8"
    )

    if result.returncode != 0:
        logger("⚠️ Fallback 1: Using shlex.quote()")
        escaped_path = shlex.quote(filepath)
        result = run_quiet(
            ["adb", "shell", f"stat -c %y {escaped_path}"],
            capture_output=True,
            text=True
        )

    if result.returncode != 0:
        logger("⚠️ Fallback 2: Using ls -l as alternative")
        result = run_quiet(
            ["adb", "shell", "ls", "-l", filepath],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            if lines:
                parts = lines[0].split()
                if len(parts) >= 8:
                    date_part = parts[5]
                    time_part = parts[6]
                    date_str = f"{date_part} {time_part}:00"

                    try:
                        from datetime import datetime
                        parsed_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                        logger(f"📅 Fetched Android file date via ls for {filepath}: {parsed_date}")
                        return parsed_date
                    except ValueError as e:
                        logger(f"⚠️ Could not parse ls date: {date_str}, error: {e}")

    if result.returncode != 0:
        logger("⚠️ Fallback 3: Using octal escaping")

        def octal_escape(s):
            result = ""
            for char in s:
                if char.isalnum() or char in "/-_.":
                    result += char
                else:
                    result += f"\\{ord(char):03o}"
            return result

        escaped_path = octal_escape(filepath)
        result = run_quiet(
            ["adb", "shell", f"stat -c %y '{escaped_path}'"],
            capture_output=True,
            text=True
        )

    if result.returncode != 0:
        logger("⚠️ Fallback 4: Using find command")
        dir_path = os.path.dirname(filepath)
        filename = os.path.basename(filepath)

        result = run_quiet(
            ["adb", "shell", "find", dir_path, "-name", filename, "-exec", "stat", "-c", "%y", "{}", ";"],
            capture_output=True,
            text=True
        )

    if result.returncode == 0:
        date_str = result.stdout.strip().split(".")[0]
        try:
            from datetime import datetime
            parsed_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            logger(f"📅 Fetched Android file date for {filepath}: {parsed_date}")
            return parsed_date
        except ValueError:
            logger(f"⚠️ Could not parse Android file date: {date_str}")
    else:
        logger(f"⚠️ Failed to get Android date for {filepath}: {result.stderr}")

    return None


def ensure_exif_date(image_path, fallback_datetime=None, logger=print):
    try:
        if not image_path.lower().endswith((".jpg", ".jpeg")):
            return  # Only applicable to JPEGs

        exif_dict = piexif.load(image_path)
        exif = exif_dict.get("Exif", {})

        if piexif.ExifIFD.DateTimeOriginal not in exif:
            if fallback_datetime:
                date_str = fallback_datetime.strftime("%Y:%m:%d %H:%M:%S")
            else:
                mtime = os.path.getmtime(image_path)
                date_str = datetime.fromtimestamp(mtime).strftime("%Y:%m:%d %H:%M:%S")

            logger(f"🕓 Embedding EXIF date: {date_str}")
            exif[piexif.ExifIFD.DateTimeOriginal] = date_str.encode()
            exif_dict["Exif"] = exif
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, image_path)
    except Exception as e:
        logger(f"⚠️ Failed to add EXIF date to {image_path}: {e}")


def embed_png_gif_metadata(path, dt, logger=print):
    if dt is None:
        logger(f"⚠️ No datetime available to embed for {os.path.basename(path)}")
        return

    ds = dt.strftime("%Y:%m:%d %H:%M:%S")
    run_quiet([
        "exiftool", "-overwrite_original",
        f"-CreationDate={ds}",
        f"-XMP:CreateDate={ds}",
        path
    ])
    logger(f"🧩 Embedded CreationDate/XMP:CreateDate in {os.path.basename(path)}")

def embed_video_metadata(path, dt, logger=print):
    if dt is None:
        logger(f"⚠️ No datetime available to embed for {os.path.basename(path)}")
        return

    try:
        ds = dt.strftime("%Y:%m:%d %H:%M:%S")
        args = ["exiftool", "-overwrite_original"]

        if path.lower().endswith(".mov"):
            args += [
                f"-QuickTime:CreateDate={ds}",
                f"-QuickTime:ModifyDate={ds}"
            ]
        elif path.lower().endswith(".heic"):
            args += [
                f"-DateTimeOriginal={ds}"
            ]
        elif path.lower().endswith(".mp4"):
            args += [
                f"-QuickTime:CreateDate={ds}",
                f"-QuickTime:ModifyDate={ds}",
                f"-TrackCreateDate={ds}",
                f"-MediaCreateDate={ds}"
            ]

        args.append(path)
        run_quiet(args)
        logger(f"🎬 Embedded metadata in {os.path.basename(path)}")
    except Exception as e:
        logger(f"⚠️ Failed to embed metadata in {path}: {e}")


def delete_files_from_phone(paths, logger=print):
    total = len(paths)
    success = 0
    failed = 0

    for path in paths:
        logger(f"🗑️ Deleting: {path}")

        result = run_quiet(["adb", "shell", "rm", path], capture_output=True, text=True)

        if result.returncode != 0:
            logger("⚠️ Fallback 1: Using shlex.quote()")
            escaped_path = shlex.quote(path)
            result = run_quiet(["adb", "shell", f"rm {escaped_path}"], capture_output=True, text=True)

        if result.returncode != 0:
            logger("⚠️ Fallback 2: Using double quotes")
            escaped = path.replace('\\', '\\\\').replace('"', '\\"')
            result = run_quiet(["adb", "shell", f'rm "{escaped}"'], capture_output=True, text=True)

        if result.returncode != 0:
            logger("⚠️ Fallback 3: Using octal escaping")

            def octal_escape(s):
                result = ""
                for char in s:
                    if char.isalnum() or char in "/-_.":
                        result += char
                    else:
                        result += f"\\{ord(char):03o}"
                return result

            escaped_path = octal_escape(path)
            result = run_quiet(["adb", "shell", f"rm '{escaped_path}'"], capture_output=True, text=True)

        if result.returncode != 0:
            logger("⚠️ Fallback 4: Using find and delete")
            dir_path = os.path.dirname(path)
            filename = os.path.basename(path)

            result = run_quiet([
                "adb", "shell", "find", dir_path, "-name", filename, "-delete"
            ], capture_output=True, text=True)

        if result.returncode == 0:
            logger(f"✅ Successfully deleted: {path}")
            success += 1
        else:
            logger(f"❌ Failed to delete {path}: {result.stderr.strip()}")
            failed += 1

    # Sync Summary
    logger("\n📊 Deletion Summary:")
    logger(f"🔹 Total files attempted: {total}")
    logger(f"✅ Successfully deleted: {success}")
    logger(f"❌ Failed to delete: {failed}")



def rename_with_date_if_needed(file_path, fallback_datetime, logger=print):
    try:
        base, ext = os.path.splitext(file_path)
        filename = os.path.basename(file_path)

        if any(char.isdigit() for char in filename):
            return file_path

        if fallback_datetime is None:
            logger(f"⚠️ No phone date available. Using PC file modified time.")
            mtime = os.path.getmtime(file_path)
            fallback_datetime = datetime.fromtimestamp(mtime)

        date_str = fallback_datetime.strftime("%Y%m%d_%H%M%S")
        new_path = os.path.join(os.path.dirname(file_path), f"{date_str}{ext}")

        os.rename(file_path, new_path)
        logger(f"📛 Renamed to include date: {os.path.basename(new_path)}")
        return new_path
    except Exception as e:
        logger(f"⚠️ Failed to rename file {file_path}: {e}")
        return file_path


def pull_media_from_phone(destination, logger=print):
    with open("config.json") as f:
        config = json.load(f)

    paths = config.get("phone_media_paths", [])
    os.makedirs(destination, exist_ok=True)

    if os.path.exists(HASH_FILE):
        with open(HASH_FILE, "r") as f:
            seen_hashes = set(json.load(f))
    else:
        seen_hashes = set()

    stats = {
        "pulled": 0,
        "duplicates_skipped": 0,
        "total_files_seen": 0
    }

    pulled_paths = []
    media_exts = (".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".heic", ".gif")

    for base_path in paths:
        logger(f"📥 Recursively scanning: {base_path}")

        result = run_quiet(
            ["adb", "shell", "find", base_path, "-type", "f"],
            capture_output=True, text=True, encoding="utf-8", errors="replace"
        )

        if result.returncode != 0:
            logger(f"❌ Failed to scan {base_path} with find, trying ls -R fallback")
            logger(f"Error: {result.stderr}")

            result = run_quiet(
                ["adb", "shell", "ls", "-R", base_path],
                capture_output=True, text=True, encoding="utf-8", errors="replace"
            )

            if result.returncode != 0:
                logger(f"❌ All scanning methods failed for {base_path}")
                logger(f"Error: {result.stderr}")
                continue

            all_files = parse_ls_r_output(result.stdout, base_path)
        else:
            all_files = []
            for line in result.stdout.strip().split("\n"):
                if line and not any(part.startswith('.') for part in line.split('/')):
                    all_files.append(line)

        for phone_file in all_files:
            if not phone_file or not phone_file.lower().endswith(media_exts):
                continue

            stats["total_files_seen"] += 1
            file = os.path.basename(phone_file)
            folder_name = os.path.dirname(phone_file).strip("/").replace("/", "_")
            local_path = os.path.join(destination, folder_name)
            os.makedirs(local_path, exist_ok=True)

            logger(f"⬇️ Pulling {file} from {phone_file} → {local_path}")
            pulled_paths.append(phone_file)

            pull_result = pull_file_safely(phone_file, local_path)

            if not pull_result:
                logger(f"❌ Failed to pull {file}")
                continue

            downloaded_files = [os.path.join(local_path, f) for f in os.listdir(local_path)]
            newest_file = max(downloaded_files, key=os.path.getmtime)

            safe_name = file.replace("?", "_").replace("&", "_").replace("=", "_")
            safe_path = os.path.join(local_path, safe_name)
            os.rename(newest_file, safe_path)

            capture_date = get_android_file_datetime(phone_file, logger=print)

            if safe_path.lower().endswith((".jpg", ".jpeg")):
                ensure_exif_date(safe_path, fallback_datetime=capture_date, logger=print)
            else:
                safe_path = rename_with_date_if_needed(safe_path, fallback_datetime=capture_date)
                if safe_path.lower().endswith((".png", ".gif", ".webp")):
                    embed_png_gif_metadata(safe_path, capture_date)
                elif safe_path.lower().endswith((".mov", ".heic", ".mp4")):
                    embed_video_metadata(safe_path, capture_date)

            file_hash = compute_file_hash(safe_path)
            if file_hash in seen_hashes:
                logger(f"🗑️ Duplicate detected. Removing {os.path.basename(safe_path)}")
                os.remove(safe_path)
                stats["duplicates_skipped"] += 1
            else:
                seen_hashes.add(file_hash)
                stats["pulled"] += 1
                logger(f"✅ Kept: {os.path.basename(safe_path)}")

    with open(HASH_FILE, "w") as f:
        json.dump(list(seen_hashes), f)

    logger("\n📊 Sync Summary:")
    logger(f"🔹 Total files found: {stats['total_files_seen']}")
    logger(f"🔹 New files pulled: {stats['pulled']}")
    logger(f"🔹 Duplicates skipped: {stats['duplicates_skipped']}\n")

    return pulled_paths


def pull_file_safely(phone_file, local_path, logger=print):
    """Safely pull a file that might have special characters in its name"""

    result = run_quiet(
        ["adb", "pull", phone_file, local_path],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        return True

    logger("⚠️ Direct pull failed, trying with quotes...")

    escaped_path = shlex.quote(phone_file)
    result = run_quiet(
        ["adb", "shell", f"cp {escaped_path} /sdcard/temp_file && exit"],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        result = run_quiet(
            ["adb", "pull", "/sdcard/temp_file", local_path],
            capture_output=True, text=True
        )

        run_quiet(["adb", "shell", "rm", "/sdcard/temp_file"], capture_output=True)

        if result.returncode == 0:
            return True

    logger("⚠️ All pull methods failed")
    return False


def parse_ls_r_output(output, base_path):
    """Parse ls -R output to extract file paths"""
    files = []
    current_dir = base_path

    for line in output.split('\n'):
        line = line.strip()
        if not line:
            continue

        if line.endswith(':'):
            current_dir = line[:-1]
        elif not line.startswith('total ') and not line.startswith('d'):
            if current_dir and line:
                full_path = os.path.join(current_dir, line).replace('\\', '/')
                files.append(full_path)

    return files