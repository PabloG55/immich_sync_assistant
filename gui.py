import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, simpledialog, messagebox
import json
import subprocess
import threading
import os
import sys
from utils.mtp_utils import pull_media_from_phone, delete_files_from_phone
from utils.immich_api import upload_file_to_immich, get_or_create_album, add_asset_to_album
from utils.file_utils import compress_backup

NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0

def check_dependencies():
    missing = []
    try:
        import requests
    except ImportError:
        missing.append("requests")
    try:
        import piexif
    except ImportError:
        missing.append("piexif")
    if missing:
        msg = f"Missing required packages: {', '.join(missing)}\nInstall with: pip install {' '.join(missing)}"
        messagebox.showerror("Missing Dependencies", msg)
        return False
    return True


def run_quiet(cmd, **kwargs):
    return subprocess.run(cmd, creationflags=NO_WINDOW, **kwargs)


class PhoneBackupGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Immich Sync Assistant")
        try:
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.abspath(".")

            icon_path = os.path.join(base_path, "resources", "icon.ico")
            self.root.iconbitmap(icon_path)

        except Exception as e:
            print(f"⚠️ Failed to load icon: {e}")
        self.root.geometry("800x700")
        self.root.minsize(700, 600)
        self.config_file = "config.json"
        self.load_config()
        self.pulled_paths = []
        self.current_backup_dir = ""
        self.backup_thread = None
        self.create_widgets()
        self.refresh_selected_paths()
        threading.Thread(target=self.refresh_phone_folders, daemon=True).start()

    def load_config(self):
        try:
            with open(self.config_file, 'r') as f:
                self.config = json.load(f)
        except FileNotFoundError:
            home = os.path.expanduser("~")
            pictures_dir = os.path.join(home, "Pictures")
            self.config = {
                "immich_url": "",
                "api_key": "",
                "temp_import_dir": pictures_dir,
                "phone_media_paths": []
            }
            self.save_config()

    def save_config(self):
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)

    def save_configuration(self):
        self.config["immich_url"] = self.immich_url_var.get().strip()
        self.config["api_key"] = self.api_key_var.get().strip()
        self.config["temp_import_dir"] = self.backup_dir_var.get().strip()
        try:
            self.save_config()
            messagebox.showinfo("Success", "Configuration saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save configuration: {e}")


    def create_widgets(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill='both', expand=True, padx=10, pady=10)
        config_frame = ttk.Frame(notebook)
        folders_frame = ttk.Frame(notebook)
        backup_frame = ttk.Frame(notebook)
        notebook.add(config_frame, text="Configuration")
        notebook.add(folders_frame, text="Phone Folders")
        notebook.add(backup_frame, text="Backup Process")
        self.create_config_tab(config_frame)
        self.create_folders_tab(folders_frame)
        self.create_backup_tab(backup_frame)

    def create_config_tab(self, parent):
        ttk.Label(parent, text="Immich Server URL:").pack(anchor='w', padx=10, pady=(10, 0))
        self.immich_url_var = tk.StringVar(value=self.config.get("immich_url", ""))
        ttk.Entry(parent, textvariable=self.immich_url_var, width=60).pack(fill='x', padx=10, pady=5)
        ttk.Label(parent, text="API Key:").pack(anchor='w', padx=10, pady=(10, 0))
        self.api_key_var = tk.StringVar(value=self.config.get("api_key", ""))
        api_entry = ttk.Entry(parent, textvariable=self.api_key_var, width=60, show="*")
        api_entry.pack(fill='x', padx=10, pady=5)
        self.show_api_key = tk.BooleanVar()
        ttk.Checkbutton(parent, text="Show API Key", variable=self.show_api_key,
                        command=lambda: api_entry.config(show="" if self.show_api_key.get() else "*")).pack(anchor='w', padx=10)
        ttk.Label(parent, text="Local Backup Directory:").pack(anchor='w', padx=10, pady=(20, 0))
        backup_frame = ttk.Frame(parent)
        backup_frame.pack(fill='x', padx=10, pady=5)
        self.backup_dir_var = tk.StringVar(value=self.config.get("temp_import_dir", os.path.join(os.path.expanduser("~"), "Pictures")))
        ttk.Entry(backup_frame, textvariable=self.backup_dir_var).pack(side='left', fill='x', expand=True)
        ttk.Button(backup_frame, text="Browse", command=self.select_backup_directory).pack(side='right')
        ttk.Button(parent, text="Test Immich Connection", command=self.test_connection).pack(pady=(15, 0))
        self.connection_status = ttk.Label(parent, text="")
        self.connection_status.pack(padx=10, pady=5)
        ttk.Button(parent, text="Save Configuration", command=self.save_configuration).pack(pady=20)

    def create_folders_tab(self, parent):
        ttk.Label(parent, text="Select phone folders to include in backups.", justify='center').pack(pady=10)
        frame = ttk.Frame(parent)
        frame.pack(pady=10)
        self.phone_status = ttk.Label(frame, text="")
        self.phone_status.pack(side='left', padx=(0, 10))  # Add padding between label and button
        ttk.Button(frame, text="Refresh Folders", 
                  command=lambda: threading.Thread(target=self.refresh_phone_folders, daemon=True).start()
        ).pack(side='left')
        self.folders_tree = ttk.Treeview(parent, columns=('path',), show='tree headings')
        self.folders_tree.heading('#0', text='Folder')
        self.folders_tree.heading('path', text='Full Path')
        self.folders_tree.column('#0', width=300)
        self.folders_tree.pack(fill='both', expand=True, padx=10, pady=5)
        self.selected_listbox = tk.Listbox(parent, height=8)
        self.selected_listbox.pack(fill='x', padx=10, pady=5)
        ttk.Button(parent, text="Add Selected", command=self.add_selected_folder).pack(side='left', padx=10, pady=5)
        ttk.Button(parent, text="Remove Selected", command=self.remove_selected_folder).pack(side='left', padx=10)
        ttk.Button(parent, text="Add Custom Path", command=self.add_custom_path).pack(side='left')

    def create_backup_tab(self, parent):
        ttk.Label(parent, text="Custom Album Name (optional):").pack(anchor='w', padx=10)
        self.custom_album_var = tk.StringVar()
        ttk.Entry(parent, textvariable=self.custom_album_var, width=40).pack(anchor='w', padx=10, pady=(0, 10))
        self.progress_var = tk.StringVar(value="Ready to start backup...")
        ttk.Label(parent, textvariable=self.progress_var).pack(anchor='w', padx=10)
        self.progress_bar = ttk.Progressbar(parent, mode='indeterminate')
        self.progress_bar.pack(fill='x', padx=10, pady=5)
        self.log_text = scrolledtext.ScrolledText(parent, height=15, width=80)
        self.log_text.pack(fill='both', expand=True, padx=10, pady=5)
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill='x', padx=10)
        self.start_button = ttk.Button(btn_frame, text="Start Backup", command=self.start_backup_process)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(btn_frame, text="Stop", command=self.stop_process, state='disabled')
        self.stop_button.pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Clear Log", command=self.clear_log).pack(side='right')

    def log_message(self, msg):
        self.root.after(0, lambda: (self.log_text.insert(tk.END, msg + "\n"), self.log_text.see(tk.END)))

    def clear_log(self):
        self.log_text.delete(1.0, tk.END)

    def start_backup_process(self):
        self.start_button.config(state='disabled')
        self.stop_button.config(state='normal')
        self.progress_bar.start()
        self.progress_var.set("Starting backup...")
        self.backup_thread = threading.Thread(target=self.run_backup_process, daemon=True)
        self.backup_thread.start()

    def run_backup_process(self):
        try:
            backup_dir = self.config["temp_import_dir"]
            immich_url = self.config["immich_url"]
            api_key = self.config["api_key"]
            self.log_message("📥 Pulling files from phone…")
            pulled = pull_media_from_phone(destination=backup_dir, logger=self.log_message)
            album = self.custom_album_var.get().strip()
            stats = {"total": 0, "uploaded": 0, "duplicates": 0, "failed": 0}
            self.log_message("🚀 Uploading to Immich…")
            for root, _, files in os.walk(backup_dir):
                for fn in files:
                    if not fn.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".heic", ".gif")):
                        continue
                    stats["total"] += 1
                    path = os.path.join(root, fn)
                    self.log_message(f"📤 Uploading: {path}")
                    asset_id, status = upload_file_to_immich(path, immich_url, api_key, logger=self.log_message)
                    if not asset_id:
                        stats["failed"] += 1
                        continue

                    parts = os.path.basename(root).split("_")
                    alb = album or "_".join(parts[2:]) if len(parts) > 2 else parts[1] if len(parts) > 1 else parts[0]
                    album_id = get_or_create_album(alb, immich_url, api_key)
                    if album_id:
                        added = add_asset_to_album(asset_id, album_id, immich_url, api_key)
                        self.log_message(f"📁 Added to album '{alb}': {added}")
                    if status == "duplicate":
                        stats["duplicates"] += 1
                        self.log_message("♻️ File already exists in Immich (duplicate).")
                    else:
                        stats["uploaded"] += 1
            compress_backup(backup_dir, logger=self.log_message)
            self.log_message("\n📊 Sync Summary:")
            for k, v in stats.items():
                self.log_message(f"🔹 {k.capitalize()}: {v}")
            self.log_message("")
            self.ask_cleanup(pulled, backup_dir)
        except Exception as e:
            self.log_message(f"❌ Backup failed: {e}")
        finally:
            self.root.after(0, self.progress_bar.stop)
            self.root.after(0, lambda: self.start_button.config(state='normal'))
            self.root.after(0, lambda: self.stop_button.config(state='disabled'))
            self.progress_var.set("Backup process finished")

    def ask_cleanup(self, pulled_paths, backup_dir):
        def ask_and_handle():
            if messagebox.askyesno("Cleanup", "🗑️ Delete pulled files from phone?"):
                delete_files_from_phone(pulled_paths, logger=self.log_message)
            if messagebox.askyesno("Cleanup", "🧹 Delete pulled files from PC (they're now zipped)?\n⚠️ This will delete the local backup folder!"):
                import shutil
                try:
                    shutil.rmtree(backup_dir)
                    self.log_message("\n🗑️ Local pulled media folder deleted.")
                except Exception as e:
                    self.log_message(f"❌ Failed to delete local: {e}")
        threading.Thread(target=ask_and_handle, daemon=True).start()

    def select_backup_directory(self):
        folder = filedialog.askdirectory(initialdir=self.backup_dir_var.get())
        if folder:
            self.backup_dir_var.set(folder)

    def test_connection(self):
        url = self.immich_url_var.get().strip()
        key = self.api_key_var.get().strip()
        if not url or not key:
            self.connection_status.config(text="❌ Enter URL and API key", foreground='red')
            return
        import requests
        try:
            resp = requests.get(f"{url.rstrip('/')}/api/server/ping", headers={"x-api-key": key}, timeout=10)
            if resp.status_code == 200:
                self.connection_status.config(text="✅ Connected!", foreground='green')
            else:
                self.connection_status.config(text=f"❌ Error: {resp.status_code}", foreground='red')
        except Exception as e:
            self.connection_status.config(text=f"❌ Connection failed: {e}", foreground='red')

    def refresh_selected_paths(self):
        try:
            with open("config.json") as f:
                config = json.load(f)
                paths = config.get("phone_media_paths", [])
                self.selected_listbox.delete(0, tk.END)  # Clear current items
                for path in paths:
                    self.selected_listbox.insert(tk.END, path)
        except Exception as e:
            print(f"Error reading config: {e}")

    def refresh_phone_folders(self):
        self.root.after(0, lambda: self.phone_status.config(text="🔄 Scanning phone..."))
        try:
            result = run_quiet(["adb", "devices"], capture_output=True, text=True)
            if "device" not in result.stdout or len(result.stdout.strip().split('\n')) < 2:
                self.root.after(0, lambda: self.phone_status.config(text="❌ No phone connected"))
                return
        except FileNotFoundError:
            self.root.after(0, lambda: self.phone_status.config(text="❌ ADB not found"))
            return

        common_dirs = [
            "/sdcard/DCIM", "/sdcard/Pictures", "/sdcard/Download",
            "/sdcard/Camera", "/sdcard/WhatsApp/Media"
        ]
        found = []
        for d in common_dirs:
            try:
                res = run_quiet(["adb", "shell", "find", d, "-maxdepth", "2", "-type", "d"],
                                capture_output=True, text=True, timeout=10)
                if res.returncode == 0:
                    for line in res.stdout.strip().split('\n'):
                        if line and line not in found:
                            found.append(line)
            except Exception:
                continue
        self.root.after(0, self.folders_tree.delete, *self.folders_tree.get_children())
        for f in sorted(found):
            self.root.after(0, lambda folder=f: self.folders_tree.insert('', 'end',
                                                                         text=os.path.basename(folder) or folder,
                                                                         values=(folder,)))
        self.root.after(0, lambda: self.phone_status.config(text=f"✅ Found {len(found)} folders"))
        self.root.after(0, self.refresh_selected_paths)

    def add_selected_folder(self):
        sel = self.folders_tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select a folder")
            return
        path = self.folders_tree.item(sel[0], 'values')[0]
        if path not in self.config["phone_media_paths"]:
            self.config["phone_media_paths"].append(path)
            self.save_config()
            self.update_selected_listbox()
            messagebox.showinfo("Success", f"Added: {path}")
        else:
            messagebox.showinfo("Info", "Already added")

    def remove_selected_folder(self):
        idx = self.selected_listbox.curselection()
        if not idx:
            messagebox.showwarning("Warning", "Select a folder to remove")
            return
        path = self.config["phone_media_paths"][idx[0]]
        if messagebox.askyesno("Confirm", f"Remove {path}?"):
            self.config["phone_media_paths"].pop(idx[0])
            self.save_config()
            self.update_selected_listbox()

    def add_custom_path(self):
        path = simpledialog.askstring("Custom Path", "Enter phone directory path:")
        if path and path not in self.config["phone_media_paths"]:
            self.config["phone_media_paths"].append(path)
            self.save_config()
            self.update_selected_listbox()
            messagebox.showinfo("Success", f"Added: {path}")

    def update_selected_listbox(self):
        self.selected_listbox.delete(0, tk.END)
        for p in self.config["phone_media_paths"]:
            self.selected_listbox.insert(tk.END, p)

    def stop_process(self):
        self.log_message("🛑 Stop requested by user")


def main():
    if not check_dependencies():
        return
    root = tk.Tk()
    app = PhoneBackupGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()