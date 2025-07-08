import customtkinter as ctk
import tkinter as tk  # For messagebox and filedialog
from tkinter import messagebox
import threading
import requests
import subprocess
import json
import os
import re
import concurrent.futures


CONFIG_FILE = "dispatcharr_gui_config.json"
HISTORY_FILE = "dispatcharr_history.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f)
    except Exception:
        pass

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {"DISPATCHARR_URL": "http://66.23.230.54:9191", "API_KEY": ""}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

def ffprobe_stream(url):
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,avg_frame_rate",
        "-of", "json", url
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        info = json.loads(result.stdout)
        stream = info['streams'][0]
        codec = stream.get('codec_name')
        width = stream.get('width')
        height = stream.get('height')
        fps = eval(stream.get('avg_frame_rate')) if stream.get('avg_frame_rate') else None
        return codec, f"{width}x{height}", fps
    except Exception:
        return None, None, None

def fetch_streams(dispatcharr_url, api_key):
    streams_url = f"{dispatcharr_url}/api/channels/streams/"
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(streams_url, headers=headers)
    resp.raise_for_status()
    streams = resp.json()
    if isinstance(streams, dict):
        if 'results' in streams:
            streams = streams['results']
        else:
            for v in streams.values():
                if isinstance(v, list):
                    streams = v
                    break
    return streams

def get_channel_name(channel_id, channels):
    for ch in channels:
        if str(ch.get('id')) == str(channel_id):
            return ch.get('name')
    return f"Channel {channel_id}"

def fetch_channels(dispatcharr_url, api_key):
    channels_url = f"{dispatcharr_url}/api/channels/channels/"
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(channels_url, headers=headers)
    resp.raise_for_status()
    return resp.json()

def sanitize_filename(name):
    # Remove invalid filename characters and strip
    return re.sub(r'[^\w\-_\. ]', '_', name).strip()

def capture_image_from_stream(stream_url, channel_name):
    folder = "captured"
    if not os.path.exists(folder):
        os.makedirs(folder)
    filename = os.path.join(folder, sanitize_filename(channel_name) + ".jpg")
    # Use ffmpeg to capture a single frame
    cmd = [
        "ffmpeg", "-y", "-i", stream_url, "-frames:v", "1", "-q:v", "2", filename
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=10)
    except Exception:
        pass

class ChannelStatusApp(ctk.CTk):
    # History and right-click menu functionality removed as requested. No-op stubs.
    def safe_set_status(self, msg, state=None):
        # Robust status setter: use set_status if available, else status_var, else print
        if hasattr(self, 'set_status') and callable(getattr(self, 'set_status', None)):
            if state is not None:
                self.set_status(msg, state)
            else:
                self.set_status(msg)
        elif hasattr(self, 'status_var') and isinstance(self.status_var, tk.StringVar):
            self.status_var.set(msg)
        else:
            print(msg)
    def _update_preview_if_selected(self, channel_name):
        # Show image preview for the selected channel in the right panel (not a popup)
        import os
        from PIL import Image, ImageTk
        import requests
        import xml.etree.ElementTree as ET
        import datetime
        import uuid
        folder = "captured"
        filename = os.path.join(folder, sanitize_filename(channel_name) + ".jpg")

        def clear_preview():
            # Only clear if widgets exist (robust to early calls)
            if hasattr(self, '_preview_name_label'):
                self._preview_name_label.configure(text="No Preview Available")
            if hasattr(self, '_preview_image_label'):
                try:
                    self._preview_image_label.configure(image="", text="No Image", fg_color="#222")
                except Exception:
                    pass
                self._preview_image_label.image = None
            # Clear info tab if present
            if hasattr(self, '_preview_info_status'):
                self._preview_info_status.configure(text="Status: --")
                self._preview_info_codec.configure(text="Codec: --")
                self._preview_info_resolution.configure(text="Resolution: --")
                self._preview_info_fps.configure(text="FPS: --")
            # Always clear EPG now playing label
            if hasattr(self, '_preview_epg_now_label'):
                self._preview_epg_now_label.configure(text="Now Playing: --")

        # Always update info tab, even if image is missing
        def get_channel_info(name):
            for item in self.tree.get_children():
                values = self.tree.item(item, 'values')
                if len(values) > 1 and values[1] == name:
                    return {
                        'id': values[0] if len(values) > 0 else None,
                        'status': values[2] if len(values) > 2 else '--',
                        'codec': values[3] if len(values) > 3 else '--',
                        'resolution': values[4] if len(values) > 4 else '--',
                        'fps': values[5] if len(values) > 5 else '--',
                    }
            return {'id': None, 'status': '--', 'codec': '--', 'resolution': '--', 'fps': '--'}

        info = get_channel_info(channel_name)
        if hasattr(self, '_preview_info_status'):
            self._preview_info_status.configure(text=f"Status: {info['status']}")
            self._preview_info_codec.configure(text=f"Codec: {info['codec']}")
            self._preview_info_resolution.configure(text=f"Resolution: {info['resolution']}")
            self._preview_info_fps.configure(text=f"FPS: {info['fps']}")


        # --- EPG Now Playing (no progress bar) ---
        # Remove/hide previous EPG label if present
        if hasattr(self, '_preview_epg_now_label') and self._preview_epg_now_label is not None:
            self._preview_epg_now_label.grid_remove()

        epg_request_id = str(uuid.uuid4())
        self._epg_request_id = epg_request_id

        def fetch_epg_now_playing(channel_id, channel_name, request_id):
            url = self.url_var.get().strip()
            epg_url = url.rstrip('/') + "/output/epg"
            now_playing = None
            try:
                resp = requests.get(epg_url, timeout=5)
                resp.raise_for_status()
                xml = resp.content
                # Try to parse as XMLTV (may need to skip declaration)
                try:
                    tree = ET.fromstring(xml)
                except ET.ParseError:
                    xml_str = xml.decode(errors='ignore')
                    xml_str = xml_str[xml_str.find('<tv'): ] if '<tv' in xml_str else xml_str
                    tree = ET.fromstring(xml_str)
                # Find channel xmltv-id by matching display-name (case-insensitive, ignore extra spaces)
                channel_xmltv_id = None
                channel_name_norm = channel_name.strip().lower().replace(' ', '')
                for ch in tree.findall("channel"):
                    for disp in ch.findall('display-name'):
                        disp_name = disp.text.strip().lower().replace(' ', '') if disp.text else ''
                        if disp_name == channel_name_norm:
                            channel_xmltv_id = ch.get('id') or ch.get('xmltv-id') or ch.get('channel') or ch.attrib.get('id')
                            break
                    if channel_xmltv_id:
                        break
                if not channel_xmltv_id:
                    # Try partial match (contains)
                    for ch in tree.findall("channel"):
                        for disp in ch.findall('display-name'):
                            disp_name = disp.text.strip().lower().replace(' ', '') if disp.text else ''
                            if channel_name_norm in disp_name or disp_name in channel_name_norm:
                                channel_xmltv_id = ch.get('id') or ch.get('xmltv-id') or ch.get('channel') or ch.attrib.get('id')
                                break
                        if channel_xmltv_id:
                            break
                if not channel_xmltv_id:
                    now_playing = None
                else:
                    # Find current time in UTC (EPG times are usually UTC)
                    now = datetime.datetime.utcnow()
                    # Find all programmes for this channel
                    for prog in tree.findall("programme"):
                        if prog.get('channel') != channel_xmltv_id:
                            continue
                        start = prog.get('start')
                        stop = prog.get('stop')
                        # XMLTV time format: YYYYMMDDHHMMSS Z (e.g. 20250708120000 +0000)
                        def parse_xmltv_time(t):
                            if not t:
                                return None
                            t = t.strip()
                            # Remove timezone if present
                            if ' ' in t:
                                t = t.split(' ')[0]
                            if '+' in t or '-' in t:
                                t = t.split('+')[0].split('-')[0]
                            try:
                                return datetime.datetime.strptime(t[:14], "%Y%m%d%H%M%S")
                            except Exception:
                                return None
                        start_dt = parse_xmltv_time(start)
                        stop_dt = parse_xmltv_time(stop)
                        if start_dt and stop_dt and start_dt <= now <= stop_dt:
                            title = prog.find('title')
                            now_playing = title.text if title is not None and title.text else None
                            break
            except Exception:
                now_playing = None
            # Only update if this is the latest request
            if getattr(self, '_epg_request_id', None) == request_id:
                self.after(0, update_epg_label, now_playing)

        def update_epg_label(now_playing):
            # Only show the label if EPG data is found
            if now_playing:
                if not hasattr(self, '_preview_epg_now_label') or self._preview_epg_now_label is None:
                    right_panel = self._preview_info_status.master.master
                    self._preview_epg_now_label = ctk.CTkLabel(right_panel, text=f"Now Playing: {now_playing}", font=("Segoe UI", 13, "bold"), text_color="#fff")
                    self._preview_epg_now_label.grid(row=4, column=0, sticky="ew", padx=18, pady=(6, 18))
                else:
                    self._preview_epg_now_label.configure(text=f"Now Playing: {now_playing}")
                    self._preview_epg_now_label.grid(row=4, column=0, sticky="ew", padx=18, pady=(6, 18))
            else:
                if hasattr(self, '_preview_epg_now_label') and self._preview_epg_now_label is not None:
                    self._preview_epg_now_label.grid_remove()

        channel_id = info.get('id')
        if channel_id:
            threading.Thread(target=fetch_epg_now_playing, args=(channel_id, channel_name, epg_request_id), daemon=True).start()
        else:
            update_epg_label(None)

        if not os.path.exists(filename):
            self.after(0, clear_preview)
            return

        def set_image():
            try:
                img = Image.open(filename)
                max_size = (420, 320)
                if hasattr(Image, 'Resampling'):
                    img.thumbnail(max_size, Image.Resampling.LANCZOS)
                else:
                    img.thumbnail(max_size)
                # Use the CTkLabel itself as master for PhotoImage (not the internal _label)
                photo = ImageTk.PhotoImage(img, master=self._preview_image_label)
                # Always clear previous image reference before setting new one
                try:
                    if hasattr(self._preview_image_label, "_label"):
                        self._preview_image_label._label.configure(image="")
                except Exception:
                    pass
                self._preview_image_label.image = photo  # keep reference
                self._preview_image_label.configure(image=photo, text="", fg_color="#181c20")
                if hasattr(self, '_preview_name_label'):
                    self._preview_name_label.configure(text=channel_name)
            except Exception:
                clear_preview()

        set_image()
    # Duplicate/old __init__ removed. Only the correct, persistent, string-keyed, file-saving version remains.

    def _build_gui(self):
        # Set modern appearance and color theme
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        # --- Top Bar ---
        top_bar = ctk.CTkFrame(self, height=48, fg_color="#2563eb")
        top_bar.pack(fill="x", side="top")
        splash_label = ctk.CTkLabel(
            top_bar,
            text="Dispatcharr Channel Status",
            font=("Segoe UI", 24, "bold"),
            text_color="#fff"
        )
        splash_label.pack(side="left", padx=24, pady=10)

        # --- Main Layout ---
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=12, pady=12)
        main_frame.grid_columnconfigure(0, weight=3)
        main_frame.grid_columnconfigure(1, weight=2)
        main_frame.grid_rowconfigure(0, weight=1)

        # --- Left Panel ---
        left_panel = ctk.CTkFrame(main_frame)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        # Auth Section
        auth_frame = ctk.CTkFrame(left_panel)
        auth_frame.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(auth_frame, text="Dispatcharr URL:", font=("Segoe UI", 13, "bold"), text_color=None).grid(row=0, column=0, sticky="w", padx=6, pady=3)
        self.url_var = tk.StringVar(value=self.config_data.get("DISPATCHARR_URL", ""))
        self._url_show = tk.BooleanVar(value=False)
        self.url_entry = ctk.CTkEntry(auth_frame, textvariable=self.url_var, width=260, show="*", font=("Segoe UI", 13, "bold"), text_color=None)
        self.url_entry.grid(row=0, column=1, padx=6, pady=3)
        def toggle_url_show():
            if self._url_show.get():
                self.url_entry.configure(show="")
                self.url_show_btn.configure(text="Hide")
            else:
                self.url_entry.configure(show="*")
                self.url_show_btn.configure(text="Show")
        self.url_show_btn = ctk.CTkButton(auth_frame, text="Show", width=54, font=("Segoe UI", 12, "bold"), command=lambda: self._url_show.set(not self._url_show.get()))
        self.url_show_btn.grid(row=0, column=2, padx=2, pady=3)
        self._url_show.trace_add('write', lambda *args: toggle_url_show())
        ctk.CTkLabel(auth_frame, text="Username:", font=("Segoe UI", 13, "bold"), text_color=None).grid(row=1, column=0, sticky="w", padx=6, pady=3)
        self.username_var = tk.StringVar()
        self.username_entry = ctk.CTkEntry(auth_frame, textvariable=self.username_var, width=190, font=("Segoe UI", 13, "bold"), text_color=None)
        self.username_entry.grid(row=1, column=1, padx=6, pady=3)
        ctk.CTkLabel(auth_frame, text="Password:", font=("Segoe UI", 13, "bold"), text_color=None).grid(row=2, column=0, sticky="w", padx=6, pady=3)
        self.password_var = tk.StringVar()
        self.password_entry = ctk.CTkEntry(auth_frame, textvariable=self.password_var, width=190, show="*", font=("Segoe UI", 13, "bold"), text_color=None)
        self.password_entry.grid(row=2, column=1, padx=6, pady=3)
        self.token_btn = ctk.CTkButton(auth_frame, text="Get Token", command=self.get_token_direct, fg_color="#2563eb", text_color="#fff", font=("Segoe UI", 13, "bold"), width=120, height=36)
        self.token_btn.grid(row=0, column=2, rowspan=3, padx=12, pady=3)
        self.token_status = ctk.CTkLabel(auth_frame, text="", text_color="#888", font=("Segoe UI", 12, "bold"))
        self.token_status.grid(row=3, column=0, columnspan=3, sticky="w", padx=6, pady=3)

        # Config Section
        config_frame = ctk.CTkFrame(left_panel)
        config_frame.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(config_frame, text="API Key:", font=("Segoe UI", 13, "bold"), text_color=None).grid(row=0, column=0, sticky="w", padx=6, pady=3)
        self.api_key_var = tk.StringVar(value=self.config_data.get("API_KEY", ""))
        self.api_key_entry = ctk.CTkEntry(config_frame, textvariable=self.api_key_var, width=340, show="*", font=("Segoe UI", 13, "bold"), text_color=None)
        self.api_key_entry.grid(row=0, column=1, padx=6, pady=3)
        self.save_btn = ctk.CTkButton(config_frame, text="Save Key And Load Channels", command=self.save_settings, fg_color="#2563eb", text_color="#fff", font=("Segoe UI", 13, "bold"), width=180, height=36)
        self.save_btn.grid(row=0, column=2, padx=12, pady=3)

        # Max Threads
        threads_frame = ctk.CTkFrame(left_panel)
        threads_frame.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(threads_frame, text="Max Threads:", font=("Segoe UI", 13, "bold"), text_color=None).pack(side="left", padx=(0, 6))
        self.max_threads_var = tk.IntVar(value=4)
        self.threads_spinbox = ctk.CTkSlider(threads_frame, from_=1, to=32, number_of_steps=31, variable=self.max_threads_var, width=130)
        self.threads_spinbox.pack(side="left", padx=(0, 12))
        def update_threads_label(val):
            self.threads_value_label.configure(text=f"{int(float(val))}")
        self.threads_value_label = ctk.CTkLabel(threads_frame, text=f"{self.max_threads_var.get()}", font=("Segoe UI", 13, "bold"), text_color="#2563eb")
        self.threads_value_label.pack(side="left")
        self.threads_spinbox.configure(command=update_threads_label)

        # Channels Label
        section_label = ctk.CTkLabel(left_panel, text="Channels", font=("Segoe UI", 16, "bold"), text_color="#2563eb")
        section_label.pack(anchor="w", pady=(12, 0))

        # Treeview for channels (CustomTkinter does not have a native Treeview, so fallback to ttk)
        import tkinter.ttk as ttk
        tree_frame = ctk.CTkFrame(left_panel)
        tree_frame.pack(fill="both", expand=True, pady=8)
        self.tree = ttk.Treeview(tree_frame, columns=("ID", "Name", "Status", "Codec", "Resolution", "FPS", "Show Image"), show="headings", selectmode="extended")
        self._tree_sort_column = None
        self._tree_sort_reverse = False
        for col in ("ID", "Name", "Status", "Codec", "Resolution", "FPS", "Show Image"):
            if col == "ID":
                self.tree.heading(col, text=col, command=lambda c=col: self.sort_by_column(c))
            else:
                self.tree.heading(col, text=col)
            if col == "Show Image":
                self.tree.column(col, width=100, anchor="center")
            else:
                self.tree.column(col, width=130, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.tag_configure('online', foreground='green')
        self.tree.tag_configure('offline', foreground='red')
        self.tree.bind('<<TreeviewSelect>>', self.on_tree_select)

        # Buttons
        btn_frame = ctk.CTkFrame(left_panel)
        btn_frame.pack(fill="x", pady=8)
        self.analyze_btn = ctk.CTkButton(btn_frame, text="Analyze Selected Streams", command=self.analyze_selected, fg_color="#2563eb", text_color="#fff", font=("Segoe UI", 14, "bold"), width=180, height=38)
        self.analyze_btn.pack(side="left", padx=6)
        self.refresh_btn = ctk.CTkButton(btn_frame, text="Analyze All Streams", command=self.refresh, fg_color="#2563eb", text_color="#fff", font=("Segoe UI", 14, "bold"), width=160, height=38)
        self.refresh_btn.pack(side="left", padx=6)
        self.select_all_btn = ctk.CTkButton(btn_frame, text="Select All", command=self.select_all, fg_color="#22c55e", text_color="#fff", font=("Segoe UI", 13, "bold"), width=110, height=38)
        self.select_all_btn.pack(side="left", padx=6)
        self.deselect_all_btn = ctk.CTkButton(btn_frame, text="Deselect All", command=self.deselect_all, fg_color="#ef4444", text_color="#fff", font=("Segoe UI", 13, "bold"), width=120, height=38)
        self.deselect_all_btn.pack(side="left", padx=6)

        # --- Export/Import Buttons ---
        # Export/Import buttons removed as requested. If you need them again, let me know.

        # --- Progress Bar and Thread Status ---
        perf_frame = ctk.CTkFrame(left_panel)
        perf_frame.pack(fill="x", pady=(0, 8))
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ctk.CTkProgressBar(perf_frame, variable=self.progress_var, width=320, height=18)
        self.progress_bar.pack(side="left", padx=6, pady=4)
        self.thread_status_var = tk.StringVar(value="Threads: 0/0")
        self.thread_status_label = ctk.CTkLabel(perf_frame, textvariable=self.thread_status_var, font=("Segoe UI", 12, "bold"), text_color="#2563eb")
        self.thread_status_label.pack(side="left", padx=8)
    # --- Export/Import Functionality ---
    # Export/Import functionality removed as requested. If you need it again, let me know.

        # --- Right Panel: Preview Panel ---
        right_panel = ctk.CTkFrame(main_frame, fg_color="#181c20", corner_radius=18)
        right_panel.grid(row=0, column=1, sticky="nsew")
        right_panel.grid_rowconfigure(0, weight=0)
        right_panel.grid_rowconfigure(1, weight=1)
        right_panel.grid_rowconfigure(2, weight=0)
        right_panel.grid_columnconfigure(0, weight=1)
        # Channel name label
        self._preview_name_label = ctk.CTkLabel(right_panel, text="No Preview Available", font=("Segoe UI", 16, "bold"), text_color="#60a5fa", anchor="center")
        self._preview_name_label.grid(row=0, column=0, sticky="ew", pady=(18, 6), padx=12)
        # Image label (for preview)
        self._preview_image_label = ctk.CTkLabel(right_panel, text="No Image", fg_color="#222", width=420, height=320, corner_radius=16)
        self._preview_image_label.grid(row=1, column=0, sticky="n", pady=(0, 6), padx=12)

        # --- Channel Info Tab (Status, Codec, Resolution, FPS) ---
        info_tab = ctk.CTkFrame(right_panel, fg_color="#23272e", corner_radius=12)
        info_tab.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 0))
        info_tab.grid_columnconfigure(0, weight=1)
        info_tab.grid_columnconfigure(1, weight=1)
        info_tab.grid_columnconfigure(2, weight=1)
        info_tab.grid_columnconfigure(3, weight=1)
        self._preview_info_status = ctk.CTkLabel(info_tab, text="Status: --", font=("Segoe UI", 13, "bold"), text_color="#fff")
        self._preview_info_status.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        self._preview_info_codec = ctk.CTkLabel(info_tab, text="Codec: --", font=("Segoe UI", 13, "bold"), text_color="#fff")
        self._preview_info_codec.grid(row=0, column=1, sticky="ew", padx=8, pady=6)
        self._preview_info_resolution = ctk.CTkLabel(info_tab, text="Resolution: --", font=("Segoe UI", 13, "bold"), text_color="#fff")
        self._preview_info_resolution.grid(row=0, column=2, sticky="ew", padx=8, pady=6)
        self._preview_info_fps = ctk.CTkLabel(info_tab, text="FPS: --", font=("Segoe UI", 13, "bold"), text_color="#fff")
        self._preview_info_fps.grid(row=0, column=3, sticky="ew", padx=8, pady=6)
        # --- EPG Now Playing Label ---
        # (No persistent label; created dynamically when EPG data is loaded)

    def select_all(self):
        # Select all rows in the treeview efficiently (batch update)
        self.tree.selection_set(self.tree.get_children())

    def deselect_all(self):
        # Deselect all rows in the treeview
        self.tree.selection_remove(self.tree.selection())

    def _setup_help_menu(self):
        # No-op: menu is not used in CustomTkinter UI
        pass

    def _show_help(self):
        # No-op: menu is not used in CustomTkinter UI
        pass

    def _show_readme(self):
        # Show the README.md file in a scrollable window
        import tkinter as tk
        import os
        readme_path = os.path.join(os.path.dirname(__file__), "README.md")
        if not os.path.exists(readme_path):
            messagebox.showerror("README Not Found", "README.md file not found in the application folder.")
            return
        with open(readme_path, "r", encoding="utf-8") as f:
            readme_content = f.read()
        win = tk.Toplevel(self)
        win.title("README.md - Dispatcharr Channel Status GUI")
        win.geometry("900x700")
        text = tk.Text(win, wrap=tk.WORD, font=("Segoe UI", 11))
        text.pack(fill=tk.BOTH, expand=True)
        text.insert(tk.END, readme_content)
        text.config(state=tk.DISABLED)
        # Add vertical scrollbar
        scrollbar = tk.Scrollbar(win, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _add_api_status_widgets(self):
        # Modern status bar for API status, version, and latency
        statusbar_frame = ctk.CTkFrame(self, fg_color="#181c20", height=48)
        statusbar_frame.pack(side=ctk.BOTTOM, fill=ctk.X, padx=0, pady=0)
        statusbar_frame.grid_columnconfigure(0, minsize=18)
        statusbar_frame.grid_columnconfigure(1, minsize=36)
        statusbar_frame.grid_columnconfigure(2, minsize=12)
        statusbar_frame.grid_columnconfigure(3, minsize=180)
        statusbar_frame.grid_columnconfigure(4, minsize=36)
        statusbar_frame.grid_columnconfigure(5, minsize=12)
        statusbar_frame.grid_columnconfigure(6, minsize=180)
        statusbar_frame.grid_columnconfigure(7, minsize=36)
        statusbar_frame.grid_columnconfigure(8, weight=1)

        # Server Version icon and label
        self.api_version_icon = ctk.CTkLabel(statusbar_frame, text="🖥️", font=("Segoe UI", 22, "bold"), text_color="#60a5fa", fg_color="#181c20", bg_color="#181c20")
        self.api_version_icon.grid(row=0, column=0, padx=(18, 0), pady=0, sticky="w")
        self.api_version_var = tk.StringVar(value="Server Version: --")
        self.api_version_label = ctk.CTkLabel(statusbar_frame, textvariable=self.api_version_var, font=("Segoe UI", 16, "bold"), text_color="#fff", fg_color="#181c20", bg_color="#181c20")
        self.api_version_label.grid(row=0, column=1, padx=(6, 18), pady=0, sticky="w")

        # Status dot (larger, more visible)
        self.api_status_dot = tk.Canvas(statusbar_frame, width=26, height=26, highlightthickness=0, bg="#181c20")
        self.api_status_dot.grid(row=0, column=2, padx=(0, 0), pady=0, sticky="w")
        # Status label (larger, bold, green/red/yellow)
        self.api_status_label = ctk.CTkLabel(statusbar_frame, textvariable=self.api_status_var, font=("Segoe UI", 16, "bold"), text_color="#22c55e", fg_color="#181c20", bg_color="#181c20")
        self.api_status_label.grid(row=0, column=3, padx=(6, 18), pady=0, sticky="w")

        # Latency icon and label (larger, more visible)
        self.api_latency_icon = ctk.CTkLabel(statusbar_frame, text="⏱️", font=("Segoe UI", 22, "bold"), text_color="#60a5fa", fg_color="#181c20", bg_color="#181c20")
        self.api_latency_icon.grid(row=0, column=4, padx=(0, 0), pady=0, sticky="w")
        self.api_latency_label = ctk.CTkLabel(statusbar_frame, textvariable=self.api_latency_var, font=("Segoe UI", 16, "bold"), text_color="#fff", fg_color="#181c20", bg_color="#181c20")
        self.api_latency_label.grid(row=0, column=5, padx=(6, 18), pady=0, sticky="w")

        # Modern GET M3U and GET EPG buttons with icons using CustomTkinter
        def open_m3u():
            url = self.url_var.get().strip()
            if not url:
                messagebox.showerror("Error", "Server URL is empty.")
                return
            m3u_url = url.rstrip('/') + "/output/m3u"
            import webbrowser
            webbrowser.open(m3u_url)
        def open_epg():
            url = self.url_var.get().strip()
            if not url:
                messagebox.showerror("Error", "Server URL is empty.")
                return
            epg_url = url.rstrip('/') + "/output/epg"
            import webbrowser
            webbrowser.open(epg_url)


        # --- Modern, perfectly spaced GET M3U and GET EPG buttons with icons ---
        buttons_frame = ctk.CTkFrame(statusbar_frame, fg_color="transparent")
        buttons_frame.grid(row=0, column=6, padx=(0, 0), pady=0, sticky="e")
        # GET M3U
        m3u_icon = ctk.CTkLabel(
            buttons_frame,
            text="📺",
            font=("Segoe UI", 26, "bold"),
            text_color="#60a5fa",
            fg_color="transparent"
        )
        m3u_icon.pack(side="left", padx=(0, 6))
        m3u_btn = ctk.CTkButton(
            buttons_frame,
            text="GET M3U",
            command=open_m3u,
            fg_color="#2563eb",
            text_color="#fff",
            hover_color="#1d4ed8",
            width=120,
            height=38,
            font=("Segoe UI", 15, "bold")
        )
        m3u_btn.pack(side="left", padx=(0, 24))
        # GET EPG (changed icon as per user request)
        epg_icon = ctk.CTkLabel(
            buttons_frame,
            text="📅",  # Changed from 🗓️ to 📅
            font=("Segoe UI", 26, "bold"),
            text_color="#60a5fa",
            fg_color="transparent"
        )
        epg_icon.pack(side="left", padx=(0, 6))
        epg_btn = ctk.CTkButton(
            buttons_frame,
            text="GET EPG",
            command=open_epg,
            fg_color="#2563eb",
            text_color="#fff",
            hover_color="#1d4ed8",
            width=120,
            height=38,
            font=("Segoe UI", 15, "bold")
        )
        epg_btn.pack(side="left", padx=(0, 8))

        # --- Created by arab21dwc clickable label with GitHub icon, right-aligned ---
        creator_frame = ctk.CTkFrame(statusbar_frame, fg_color="transparent")
        creator_frame.grid(row=0, column=7, padx=(12, 0), pady=0, sticky="e")
        def open_github_link():
            import webbrowser
            webbrowser.open_new("https://github.com/arab21dwc")
        github_icon = ctk.CTkLabel(
            creator_frame,
            text="",  # FontAwesome GitHub icon (if font supports it), fallback to emoji below
            font=("Segoe UI Symbol", 18, "bold"),
            text_color="#60a5fa",
            fg_color="transparent",
            cursor="hand2"
        )
        github_icon.pack(side="left", padx=(0, 4))
        github_icon.bind("<Button-1>", lambda e: open_github_link())
        created_by_label = ctk.CTkLabel(
            creator_frame,
            text="Created by arab21dwc",
            font=("Segoe UI", 13, "bold"),
            text_color="#60a5fa",
            cursor="hand2",
            fg_color="transparent"
        )
        created_by_label.pack(side="left", padx=(0, 0))
        created_by_label.bind("<Button-1>", lambda e: open_github_link())

        # Store for update
        self._api_statusbar_frame = statusbar_frame

    def _set_api_status_modern(self, status, latency=None, version=None):
        # status: "online", "offline", "error"
        # Modern, high-contrast, visually prominent status bar updates
        color = "#22c55e" if status == "online" else ("#facc15" if status == "error" else "#ef4444")
        text = "API: Online" if status == "online" else ("API: Error" if status == "error" else "API: Offline")
        self.api_status_var.set(text)
        # Draw larger colored dot
        self.api_status_dot.delete("all")
        self.api_status_dot.create_oval(4, 4, 18, 18, fill=color, outline=color)
        # Set status label color
        if status == "online":
            self.api_status_label.configure(text_color="#22c55e")
        elif status == "error":
            self.api_status_label.configure(text_color="#facc15")
        else:
            self.api_status_label.configure(text_color="#ef4444")
        # Set latency
        if latency is not None:
            self.api_latency_var.set(f"Latency: {latency} ms")
        elif status == "online":
            self.api_latency_var.set("Latency: -- ms")
        else:
            self.api_latency_var.set("")
        # Set version if provided
        if version is not None:
            self.api_version_var.set(f"Server Version: {version}")

    def _check_api_status(self):
        import time
        url = self.url_var.get().strip()
        api_key = self.api_key_var.get().strip() if hasattr(self, 'api_key_var') else ''
        def check():
            try:
                start = time.time()
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                # Health check
                resp = requests.get(url + "/api/health/", headers=headers, timeout=3)
                latency = int((time.time() - start) * 1000)
                # Version check (separate request)
                version = None
                try:
                    version_resp = requests.get(url + "/api/core/version/", headers=headers, timeout=3)
                    if version_resp.status_code == 200:
                        version_json = version_resp.json()
                        version = version_json.get("version", None)
                except Exception:
                    version = None
                if resp.status_code == 200:
                    self._set_api_status_modern("online", latency, version)
                else:
                    self._set_api_status_modern("error", None, version)
            except Exception:
                self._set_api_status_modern("offline", None, None)
            self.after(10000, self._check_api_status)
        threading.Thread(target=check, daemon=True).start()


    # History functionality removed as requested.


    # History right-click menu removed as requested.

    def _setup_help_menu(self):
        def show_help():
            if self.help_window and tk.Toplevel.winfo_exists(self.help_window):
                self.help_window.lift()
                return
            self.help_window = tk.Toplevel(self)
            self.help_window.title("Help & Manual")
            self.help_window.geometry("700x500")
            text = tk.Text(self.help_window, wrap=tk.WORD, font=("Segoe UI", 10))
            text.pack(fill=tk.BOTH, expand=True)
            help_content = (
                "Dispatcharr Channel Status GUI\n\n"
                "Features:\n"
                "- Analyze and monitor Dispatcharr channels/streams.\n"
                "- Color-coded status, stream info, and image preview.\n"
                "- Login with username/password or API key.\n"
                "- Save settings and credentials locally.\n"
                "- View channel/stream history.\n"
                "- API health and latency in status bar.\n\n"
                "Usage:\n"
                "- Configure server URL and API key or login.\n"
                "- Select channels and analyze.\n"
                "- Click 'Show Image' to preview stream snapshot.\n"
                "- See status bar for API/server health.\n\n"
                "Troubleshooting:\n"
                "- If images do not show, ensure Pillow and ffmpeg are installed.\n"
                "- If API errors, check your credentials and server URL.\n"
                "- For more, see README.md.\n"
            )
            text.insert(tk.END, help_content)
            text.config(state=tk.DISABLED)
        help_menu = self.nametowidget(self['menu']).children['!menu2']
        help_menu.add_separator()
        help_menu.add_command(label="Help / Manual", command=show_help, image=self._help_icon, compound=tk.LEFT)


    def on_tree_select(self, event):
        # Show details and preview for selected row
        selected = self.tree.selection()
        if not selected:
            self.details_text.configure(state="normal")
            self.details_text.delete(1.0, tk.END)
            self.details_text.configure(state="disabled")
            self.preview_canvas.delete("all")
            return
        item = selected[0]
        values = self.tree.item(item, 'values')
        channel_name = values[1] if len(values) > 1 else None
        if channel_name:
            self._update_preview_if_selected(channel_name)
    def __init__(self):
        self.config_data = load_config()
        super().__init__()
        # --- Initialize history before any threads or GUI setup ---
        self.history = {}  # {channel_id: [ {timestamp, status, codec, resolution, fps} ]}
        self.help_window = None
        self.api_status_var = tk.StringVar(value="API: Unknown")
        self.api_latency_var = tk.StringVar(value="Latency: -- ms")

        self.title("Dispatcharr Channel Status")
        try:
            self.state('zoomed')  # Start maximized (Windows/Linux)
        except Exception:
            self.attributes('-zoomed', True)  # Fallback for some platforms
        self.resizable(True, True)

        # --- Modern ttk theme ---
        # ...style setup removed, now handled by CustomTkinter...

        # --- Setup GUI ---
        self._build_gui()

        # --- Setup Help Menu, API Status Widgets, and Bindings ---
        self._setup_help_menu()
        self._add_api_status_widgets()
        # self.tree.bind('<Button-3>', self._on_tree_right_click)  # Removed: no right-click menu
        self._check_api_status()

        # Prompt for API token on startup, block channel loading until dialog is done and key is set
        def after_token_dialog():
            if self.api_key_var.get().strip():
                self.load_channels()
                self._tree_sort_column = "ID"
                self._tree_sort_reverse = False
                def sort_desc():
                    self.sort_by_column("ID")
                    self.sort_by_column("ID")
                self.after(100, sort_desc)
            else:
                self.after(100, self.open_token_dialog)
                self.after(200, after_token_dialog)

        def show_token_dialog_and_wait():
            if not self.api_key_var.get().strip():
                self.open_token_dialog()
                self.after(200, after_token_dialog)

        show_token_dialog_and_wait()

    def sort_by_column(self, col):
        # Get all items and their values for the column
        data = [(self.tree.set(k, col), k) for k in self.tree.get_children("")]
        # Try to sort as numbers, fallback to string
        try:
            data.sort(key=lambda t: float(t[0]) if t[0] not in ("", None) else float('-inf'), reverse=self._tree_sort_column == col and not self._tree_sort_reverse)
        except Exception:
            data.sort(key=lambda t: (t[0] or "").lower(), reverse=self._tree_sort_column == col and not self._tree_sort_reverse)
        # Rearrange items in sorted order
        for index, (val, k) in enumerate(data):
            self.tree.move(k, '', index)
        # Toggle sort order for next click
        if self._tree_sort_column == col:
            self._tree_sort_reverse = not self._tree_sort_reverse
        else:
            self._tree_sort_column = col
            self._tree_sort_reverse = False

    def analyze_selected(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showinfo("No Selection", "Please select one or more channels to analyze.")
            return
        selected_info = []  # List of (values, index)
        all_items = self.tree.get_children()
        for item in selected_items:
            values = self.tree.item(item, 'values')
            index = all_items.index(item)
            selected_info.append((values, index))
        self.safe_set_status("Analyzing selected streams...", "working")
        # Do not remove channels from the list when analyzing
        max_threads = self.max_threads_var.get() if hasattr(self, 'max_threads_var') else 4
        total = len(selected_info)
        self.progress_var.set(0)
        self.progress_bar.update()
        self.thread_status_var.set(f"Threads: 0/{max_threads}")
        def analyze_selected_bg():
            completed = [0]
            active_threads = [0]
            def update_progress():
                self.progress_var.set(completed[0]/total if total else 0)
                self.progress_bar.update()
                self.thread_status_var.set(f"Threads: {active_threads[0]}/{max_threads}")
            def task(values, index):
                active_threads[0] += 1
                self.after(0, update_progress)
                self._load_selected_data([values], index)
                completed[0] += 1
                active_threads[0] -= 1
                self.after(0, update_progress)
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
                futures = [executor.submit(task, values, index) for values, index in selected_info]
                concurrent.futures.wait(futures)
            self.after(0, lambda: self.thread_status_var.set(f"Threads: 0/{max_threads}"))
            self.after(0, lambda: self.progress_var.set(1))
        threading.Thread(target=analyze_selected_bg, daemon=True).start()

    def save_settings(self):
        self.config_data["DISPATCHARR_URL"] = self.url_var.get().strip()
        self.config_data["API_KEY"] = self.api_key_var.get().strip()
        save_config(self.config_data)
        messagebox.showinfo("Settings", "Settings saved! Reloading channels...")
        self.safe_set_status("Loading channels...", "working")
        self.load_channels()

    def load_channels(self):
        self.safe_set_status("Loading channels...", "working")
        self.tree.delete(*self.tree.get_children())

        def fetch_and_handle():
            try:
                self._fetch_channels()
            except Exception as e:
                msg = str(e)
                if (hasattr(e, 'response') and getattr(e, 'response', None) is not None and getattr(e.response, 'status_code', None) == 401) or '401' in msg or 'Unauthorized' in msg:
                    error_msg = "401 Client Error: Unauthorized. Please Refresh API Key From API Above."
                    self.safe_set_status(error_msg, "error")
                    messagebox.showerror("Unauthorized", error_msg)
                else:
                    self.safe_set_status(f"Error: {e}", "error")
                    messagebox.showerror("Error", f"Failed to fetch channels:\n{e}")

        threading.Thread(target=fetch_and_handle, daemon=True).start()

    def _fetch_channels(self):
        url = self.url_var.get().strip()
        api_key = self.api_key_var.get().strip()
        try:
            self.channels = fetch_channels(url, api_key)
        except Exception as e:
            # Show 401 Unauthorized in GUI with custom message
            msg = str(e)
            if (hasattr(e, 'response') and getattr(e, 'response', None) is not None and getattr(e.response, 'status_code', None) == 401) or '401' in msg or 'Unauthorized' in msg:
                error_msg = "401 Client Error: Unauthorized. Please Fetch Key From API Above."
            else:
                error_msg = f"Error: {e}"
            self.safe_set_status(error_msg, "error")
            messagebox.showerror("Error", error_msg)
            return
        # Logo download and display removed
        self.safe_set_status("Channels loaded. Click 'Analyze Streams' to check streams.", "ready")
        # Sort channels by ID ascending (1-1000000) before displaying
        def safe_int(val):
            try:
                return int(val)
            except Exception:
                return float('inf')
        sorted_channels = sorted(self.channels, key=lambda ch: safe_int(ch.get('id')))
        for ch in sorted_channels:
            self.tree.insert('', 'end', values=(ch.get('id'), ch.get('name'), '', '', '', '', ''))

    def refresh(self):
        # Analyze all channels in the list
        if not hasattr(self, 'channels') or not self.channels:
            self.safe_set_status("No channels loaded.", "error")
            return
        self.safe_set_status("Analyzing all streams...", "working")
        self.tree.delete(*self.tree.get_children())
        max_threads = self.max_threads_var.get() if hasattr(self, 'max_threads_var') else 4
        all_channels = self.channels
        seen_ids = set()
        all_info = []
        for idx, ch in enumerate(all_channels):
            channel_id = ch.get('id')
            if channel_id in seen_ids:
                continue
            seen_ids.add(channel_id)
            all_info.append(((ch.get('id'), ch.get('name')), idx))
        total = len(all_info)
        self.progress_var.set(0)
        self.progress_bar.update()
        self.thread_status_var.set(f"Threads: 0/{max_threads}")
        def analyze_all_bg():
            completed = [0]
            active_threads = [0]
            def update_progress():
                self.progress_var.set(completed[0]/total if total else 0)
                self.progress_bar.update()
                self.thread_status_var.set(f"Threads: {active_threads[0]}/{max_threads}")
            def task(values, index):
                active_threads[0] += 1
                self.after(0, update_progress)
                self._load_selected_data([values], index)
                completed[0] += 1
                active_threads[0] -= 1
                self.after(0, update_progress)
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
                futures = [executor.submit(task, values, index) for values, index in all_info]
                concurrent.futures.wait(futures)
            self.after(0, lambda: self.thread_status_var.set(f"Threads: 0/{max_threads}"))
            self.after(0, lambda: self.progress_var.set(1))
        threading.Thread(target=analyze_all_bg, daemon=True).start()

    # --- README Viewer in Help Menu ---
    def _setup_help_menu(self):
        # No-op: menu is not used in CustomTkinter UI
        pass

    def _load_selected_data(self, selected_values, index):
        url = self.url_var.get().strip()
        api_key = self.api_key_var.get().strip()
        try:
            channels = fetch_channels(url, api_key)
            channel_map = {str(ch.get('id')): ch for ch in channels}
        except Exception as e:
            self.safe_set_status(f"Error: {e}", "error")
            messagebox.showerror("Error", f"Failed to fetch channels:\n{e}")
            # Re-insert as offline for all selected
            for values in selected_values:
                channel_id = values[0]
                name = values[1]
                def insert_offline():
                    self.tree.insert('', index, values=(channel_id, name, "Offline", '', '', '', "Show Image"), tags=('offline',))
                self.after(0, insert_offline)
            self.safe_set_status("Done.", "ready")
            return

        for values in selected_values:
            channel_id = values[0]
            name = values[1]
            # Fetch streams for this channel
            try:
                channel_streams_url = f"{url}/api/channels/channels/{channel_id}/streams/"
                headers = {"Authorization": f"Bearer {api_key}"}
                resp = requests.get(channel_streams_url, headers=headers, timeout=10)
                resp.raise_for_status()
                channel_streams = resp.json()
                if isinstance(channel_streams, dict):
                    if 'results' in channel_streams:
                        channel_streams = channel_streams['results']
                    else:
                        for v in channel_streams.values():
                            if isinstance(v, list):
                                channel_streams = v
                                break
            except Exception as e:
                self.safe_set_status(f"Error fetching streams: {e}", "error")
                messagebox.showerror("Error", f"Failed to fetch streams for channel {name}:\n{e}")
                # Re-insert as offline
                def insert_offline():
                    self.tree.insert('', index, values=(channel_id, name, "Offline", '', '', '', "Show Image"), tags=('offline',))
                self.after(0, insert_offline)
                continue

            if not channel_streams:
                self.safe_set_status(f"No streams found for channel {name}", "error")
                # Re-insert as offline
                def insert_offline():
                    self.tree.insert('', index, values=(channel_id, name, "Offline", '', '', '', "Show Image"), tags=('offline',))
                self.after(0, insert_offline)
                continue

            # Only update preview once per analyze for this channel
            preview_updated = [False]

            for stream in channel_streams:
                stream_url = None
                codec = None
                resolution = None
                fps = None
                # Try to get info from API first
                for key in ['url', 'stream_url', 'src']:
                    if key in stream:
                        stream_url = stream[key]
                        break
                # Try to get codec, resolution, fps from API if present
                if 'codec' in stream:
                    codec = stream['codec']
                elif 'codec_name' in stream:
                    codec = stream['codec_name']
                if 'resolution' in stream:
                    resolution = stream['resolution']
                elif 'width' in stream and 'height' in stream:
                    resolution = f"{stream['width']}x{stream['height']}"
                if 'fps' in stream:
                    fps = stream['fps']
                elif 'frame_rate' in stream:
                    fps = stream['frame_rate']
                # If any are missing, use ffprobe
                if not codec or not resolution or not fps:
                    ff_codec, ff_res, ff_fps = ffprobe_stream(stream_url) if stream_url else (None, None, None)
                    if not codec:
                        codec = ff_codec
                    if not resolution:
                        resolution = ff_res
                    if not fps:
                        fps = ff_fps
                status = "Online" if codec and resolution and fps else "Offline"
                tag = 'online' if status == 'Online' else 'offline'
                show_image_text = "Show Image"
                # Insert at the original index
                def insert_and_select():
                    iid = self.tree.insert('', index, values=(channel_id, name, status, codec, resolution, fps, show_image_text), tags=(tag,))
                    self.tree.selection_set(iid)
                    self.tree.focus(iid)
                    self.tree.see(iid)
                self.after(0, insert_and_select)
                if stream_url:
                    capture_image_from_stream(stream_url, name)
                    # Only update preview once for this channel per analyze
                    if not preview_updated[0]:
                        self.after(0, self._update_preview_if_selected, name)
                        preview_updated[0] = True
        self.safe_set_status("Done.", "ready")

    def _load_data(self):
        url = self.url_var.get().strip()
        api_key = self.api_key_var.get().strip()
        try:
            # Step 1: Fetch channel list and build a mapping of id -> channel info
            channels = fetch_channels(url, api_key)
            channel_map = {str(ch.get('id')): ch for ch in channels}

            # Step 2: Fetch streams
            streams = fetch_streams(url, api_key)
        except Exception as e:
            self.status_label.config(text=f"Error: {e}")
            messagebox.showerror("Error", f"Failed to fetch data:\n{e}")
            return

        # Step 3: For each channel, fetch its streams and pair with channel name
        for ch in channels:
            channel_id = ch.get('id')
            name = ch.get('name') or f"Channel {channel_id}"
            # Fetch streams for this channel
            try:
                channel_streams_url = f"{url}/api/channels/channels/{channel_id}/streams/"
                headers = {"Authorization": f"Bearer {api_key}"}
                resp = requests.get(channel_streams_url, headers=headers)
                resp.raise_for_status()
                channel_streams = resp.json()
                # If the API returns a dict with a key like 'results', use that
                if isinstance(channel_streams, dict):
                    if 'results' in channel_streams:
                        channel_streams = channel_streams['results']
                    else:
                        for v in channel_streams.values():
                            if isinstance(v, list):
                                channel_streams = v
                                break
            except Exception as e:
                channel_streams = []

            for stream in channel_streams:
                stream_url = None
                codec = None
                resolution = None
                fps = None
                for key in ['url', 'stream_url', 'src']:
                    if key in stream:
                        stream_url = stream[key]
                        break
                if 'codec' in stream:
                    codec = stream['codec']
                elif 'codec_name' in stream:
                    codec = stream['codec_name']
                if 'resolution' in stream:
                    resolution = stream['resolution']
                elif 'width' in stream and 'height' in stream:
                    resolution = f"{stream['width']}x{stream['height']}"
                if 'fps' in stream:
                    fps = stream['fps']
                elif 'frame_rate' in stream:
                    fps = stream['frame_rate']
                if not codec or not resolution or not fps:
                    ff_codec, ff_res, ff_fps = ffprobe_stream(stream_url) if stream_url else (None, None, None)
                    if not codec:
                        codec = ff_codec
                    if not resolution:
                        resolution = ff_res
                    if not fps:
                        fps = ff_fps
                status = "Online" if codec and resolution and fps else "Offline"
                tag = 'online' if status == 'Online' else 'offline'
                show_image_text = "Show Image"
                self.tree.insert('', 'end', values=(channel_id, name, status, codec, resolution, fps, show_image_text), tags=(tag,))
                if stream_url:
                    capture_image_from_stream(stream_url, name)
                    # Responsive preview update: if this channel is selected, update preview
                    self.after(0, self._update_preview_if_selected, name)
        self.status_label.config(text="Done.")

    def on_tree_click(self, event):
        # Identify column and row
        region = self.tree.identify('region', event.x, event.y)
        if region != 'cell':
            return
        col = self.tree.identify_column(event.x)
        col_num = int(col.replace('#', '')) - 1
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        values = self.tree.item(row_id, 'values')
        if not values or len(values) < 2:
            return
        # Always update preview/details for any row click
        channel_name = values[1]
        self._update_preview_if_selected(channel_name)
        # Show Image is the last column
        if self.tree['columns'][col_num] == 'Show Image':
            self.show_channel_image(channel_name)

    # Image preview window removed as requested.

    def get_token_direct(self):
        url = self.url_var.get().strip()
        username = self.username_var.get().strip()
        password = self.password_var.get().strip()
        if not url or not username or not password:
            self.token_status.configure(text="Please enter server URL, username, and password.", text_color="#F87171")
            return
        self.token_status.configure(text="Requesting token...", text_color="#60A5FA")
        def do_request():
            try:
                resp = requests.post(f"{url}/api/accounts/token/", json={"username": username, "password": password}, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                token = data.get("access")
                if token:
                    self.api_key_var.set(token)
                    # Store username and password in config and update main vars
                    self.username_var.set(username)
                    self.password_var.set(password)
                    self.config_data["USERNAME"] = username
                    self.config_data["PASSWORD"] = password
                    save_config(self.config_data)
                    self.token_status.configure(text="Token received and set!", text_color="#4ADE80")
                else:
                    self.token_status.configure(text="No token in response.", text_color="#F87171")
            except Exception as e:
                self.token_status.configure(text=f"Error: {e}", text_color="#F87171")
        threading.Thread(target=do_request, daemon=True).start()

    def open_token_dialog(self):

        # Modern token dialog using CustomTkinter
        import customtkinter as ctk
        import tkinter as tk
        from tkinter import messagebox
        if hasattr(self, '_token_dialog') and self._token_dialog and tk.Toplevel.winfo_exists(self._token_dialog):
            self._token_dialog.lift()
            return
        self._token_dialog = tk.Toplevel(self)
        self._token_dialog.title("Enter API Token")
        self._token_dialog.geometry("420x220")
        self._token_dialog.resizable(False, False)
        frame = ctk.CTkFrame(self._token_dialog)
        frame.pack(fill="both", expand=True, padx=18, pady=18)
        ctk.CTkLabel(frame, text="Enter your Dispatcharr API Key", font=("Segoe UI", 16, "bold"), text_color="#2563eb").pack(pady=(0, 10))
        token_var = tk.StringVar(value=self.api_key_var.get())
        token_entry = ctk.CTkEntry(frame, textvariable=token_var, width=320, show="*")
        token_entry.pack(pady=6)
        show_var = tk.BooleanVar(value=False)
        def toggle_show():
            if show_var.get():
                token_entry.configure(show="")
                show_btn.configure(text="Hide")
            else:
                token_entry.configure(show="*")
                show_btn.configure(text="Show")
        show_btn = ctk.CTkButton(frame, text="Show", width=60, command=lambda: show_var.set(not show_var.get()))
        show_btn.pack(pady=2)
        show_var.trace_add('write', lambda *args: toggle_show())
        def save_token():
            val = token_var.get().strip()
            if not val:
                messagebox.showerror("Missing Token", "Please enter a valid API key.")
                return
            self.api_key_var.set(val)
            self.config_data["API_KEY"] = val
            save_config(self.config_data)
            self._token_dialog.destroy()
        save_btn = ctk.CTkButton(frame, text="Save and Continue", command=save_token, fg_color="#2563eb", text_color="#fff", font=("Segoe UI", 14, "bold"))
        save_btn.pack(pady=(12, 0))
        token_entry.focus_set()
        self._token_dialog.transient(self)
        self._token_dialog.grab_set()
        self.wait_window(self._token_dialog)

if __name__ == "__main__":
    app = ChannelStatusApp()
    app.mainloop()
