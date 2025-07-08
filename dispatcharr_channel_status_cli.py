import argparse
import json
import os
import re
import requests
import subprocess
from pprint import pprint

CONFIG_FILE = "dispatcharr_gui_config.json"

# --- Utility functions (shared with GUI) ---
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

def fetch_channels(dispatcharr_url, api_key):
    channels_url = f"{dispatcharr_url}/api/channels/channels/"
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(channels_url, headers=headers)
    resp.raise_for_status()
    return resp.json()

def sanitize_filename(name):
    return re.sub(r'[^\w\-_\. ]', '_', name).strip()

def capture_image_from_stream(stream_url, channel_name):
    folder = "captured"
    if not os.path.exists(folder):
        os.makedirs(folder)
    filename = os.path.join(folder, sanitize_filename(channel_name) + ".jpg")
    cmd = [
        "ffmpeg", "-y", "-i", stream_url, "-frames:v", "1", "-q:v", "2", filename
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=10)
    except Exception:
        pass
    return filename

def get_token(url, username, password):
    resp = requests.post(f"{url}/api/accounts/token/", json={"username": username, "password": password}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("access")

# --- CLI logic ---
def main():
    parser = argparse.ArgumentParser(description="Dispatcharr Channel Status CLI Tool")
    parser.add_argument('--url', help='Dispatcharr server URL')
    parser.add_argument('--api-key', help='API key/token')
    parser.add_argument('--username', help='Username for login (to fetch token)')
    parser.add_argument('--password', help='Password for login (to fetch token)')
    parser.add_argument('--save-settings', action='store_true', help='Save current settings to config file')
    parser.add_argument('--list-channels', action='store_true', help='List all channels')
    parser.add_argument('--analyze', nargs='*', help='Analyze channels by ID or name (comma separated or multiple args)')
    parser.add_argument('--analyze-all', action='store_true', help='Analyze all channels')
    parser.add_argument('--show-image', help='Show captured image for channel (by name)')
    parser.add_argument('--capture-images', action='store_true', help='Capture images for analyzed streams')
    args = parser.parse_args()

    config = load_config()
    url = args.url or config.get("DISPATCHARR_URL")
    api_key = args.api_key or config.get("API_KEY")

    # Token fetch
    if args.username and args.password:
        print("Requesting token...")
        token = get_token(url, args.username, args.password)
        if token:
            print("Token received.")
            api_key = token
            config["API_KEY"] = token
            config["USERNAME"] = args.username
            config["PASSWORD"] = args.password
            if args.save_settings:
                save_config(config)
        else:
            print("Failed to get token.")
            return

    if args.save_settings:
        config["DISPATCHARR_URL"] = url
        config["API_KEY"] = api_key
        save_config(config)
        print("Settings saved.")

    # List channels
    if args.list_channels:
        channels = fetch_channels(url, api_key)
        print("Channels:")
        for ch in channels:
            print(f"  ID: {ch.get('id')}, Name: {ch.get('name')}")
        return

    # Analyze channels
    if args.analyze or args.analyze_all:
        channels = fetch_channels(url, api_key)
        if args.analyze_all:
            selected = channels
        else:
            # Match by ID or name
            sel = set()
            for arg in args.analyze:
                for s in arg.split(','):
                    sel.add(s.strip())
            selected = [ch for ch in channels if str(ch.get('id')) in sel or (ch.get('name') and ch.get('name') in sel)]
        if not selected:
            print("No channels selected.")
            return
        for ch in selected:
            channel_id = ch.get('id')
            name = ch.get('name')
            print(f"\nAnalyzing Channel: {name} (ID: {channel_id})")
            try:
                channel_streams_url = f"{url}/api/channels/channels/{channel_id}/streams/"
                headers = {"Authorization": f"Bearer {api_key}"}
                resp = requests.get(channel_streams_url, headers=headers)
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
                print(f"  Error fetching streams: {e}")
                continue
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
                print(f"    Status: {status}")
                print(f"    Codec: {codec}")
                print(f"    Resolution: {resolution}")
                print(f"    FPS: {fps}")
                if args.capture_images and stream_url:
                    filename = capture_image_from_stream(stream_url, name)
                    print(f"    Image captured: {filename}")
    # Show image
    if args.show_image:
        from PIL import Image
        folder = "captured"
        filename = os.path.join(folder, sanitize_filename(args.show_image) + ".jpg")
        if not os.path.exists(filename):
            print(f"Image not found: {filename}")
            return
        try:
            img = Image.open(filename)
            img.show()
        except Exception as e:
            print(f"Failed to open image: {e}")

if __name__ == "__main__":
    main()
