# Dispatcharr Channel Status GUI

![image](https://github.com/user-attachments/assets/783612cc-7654-4157-aec8-fc5df5049002)

A modern, robust based GUI for monitoring and analyzing Dispatcharr IPTV channels.

## Features
- Modern CustomTkinter interface (no legacy Tkinter widgets except Treeview)
- Persistent right-panel channel preview with image and info
- Channel information tab: STATUS, CODEC, RESOLUTION, FPS
- EPG "Now Playing" display (auto-matches by channel name, robust to missing data)
- Analyze channels in-place (rows are never removed)
- Progress bar for analyze operations (not for EPG)
- Robust error handling and status reporting
- Modern status bar with API health, latency, and version
- GET M3U and GET EPG buttons

## Requirements
- Python 3.8+
- See `requirements.txt` for dependencies:
  - customtkinter
  - requests
  - pillow

## Usage
1. Install requirements:
   ```sh
   pip install -r requirements.txt
   ```
2. Run the GUI:
   ```sh
   python dispatcharr_channel_status_gui.py
   ```
3. Enter your Dispatcharr server URL and API key (or use username/password to fetch a token).
4. Click "Save Key And Load Channels" to load channels.
5. Select channels and click "Analyze Selected Streams" or "Analyze All Streams".
6. Select a channel to see its preview, info, and EPG "Now Playing" in the right panel.

## Notes
- EPG "Now Playing" is matched by channel name (case/space-insensitive, with fallback to partial match).
- No channel row is ever removed during analysis; status and info update in place.
- If you encounter errors, ensure your server is reachable and your API key is valid.

## Troubleshooting
- If images do not show, ensure `ffmpeg` and `pillow` are installed and available in your PATH.
- If API errors occur, check your credentials and server URL.
- For more, see the code and comments in `dispatcharr_channel_status_gui.py`.
