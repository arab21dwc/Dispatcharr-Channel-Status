import requests
import subprocess
import json
import getpass


import os

CONFIG_FILE = "dispatcharr_gui_config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {"DISPATCHARR_URL": "http://ServerURL:9191", "API_KEY": ""}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

DISPATCHARR_URL = None
API_KEY = None

def get_channels(dispatcharr_url, api_key):
    channels_url = f"{dispatcharr_url}/api/channels/channels/"
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(channels_url, headers=headers)
    resp.raise_for_status()
    return resp.json()

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

def fetch_channel_streams(dispatcharr_url, api_key, channel_id):
    channel_streams_url = f"{dispatcharr_url}/api/channels/channels/{channel_id}/streams/"
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
    return channel_streams

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

def prompt_for_token(dispatcharr_url):
    print("No API key found. Please login to get a token.")
    # Load last used username if available
    config = load_config()
    last_username = config.get("USERNAME", "")
    url = input(f"Dispatcharr URL [{dispatcharr_url}]: ") or dispatcharr_url
    username = input(f"Username [{last_username}]: ") or last_username
    password = getpass.getpass("Password: ")
    try:
        resp = requests.post(f"{url}/api/accounts/token/", json={"username": username, "password": password}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access")
        if token:
            print("Token received.")
            # Save username and password (not recommended for password, but for parity with GUI)
            config["USERNAME"] = username
            config["PASSWORD"] = password
            config["DISPATCHARR_URL"] = url
            config["API_KEY"] = token
            save_config(config)
            return token, url
        else:
            print("Failed to get token. Exiting.")
            exit(1)
    except Exception as e:
        print(f"Error fetching token: {e}")
        exit(1)

def main():
    global API_KEY, DISPATCHARR_URL
    config = load_config()
    dispatcharr_url = config.get("DISPATCHARR_URL", "http://ServerURL:9191")
    api_key = config.get("API_KEY", "")
    # Prompt for API key or login
    last_api_key = config.get("API_KEY", "")
    user_api_key = input(f"Enter API key (leave blank to login) [{last_api_key[:8]}...]: ").strip()
    if user_api_key:
        api_key = user_api_key
        config["API_KEY"] = api_key
        save_config(config)
    else:
        api_key, dispatcharr_url = prompt_for_token(dispatcharr_url)
    API_KEY = api_key
    DISPATCHARR_URL = dispatcharr_url
    channels = get_channels(DISPATCHARR_URL, API_KEY)
    for channel in channels:
        name = channel.get('name')
        channel_id = channel.get('id')
        print(f"Channel: {name} (ID: {channel_id})")
        try:
            channel_streams = fetch_channel_streams(DISPATCHARR_URL, API_KEY, channel_id)
        except Exception as e:
            print(f"  Error fetching streams: {e}")
            continue
        if not channel_streams:
            print("  No streams available.")
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
            print(f"  Status: {status}")
            print(f"  Codec: {codec}")
            print(f"  Resolution: {resolution}")
            print(f"  FPS: {fps}")

if __name__ == "__main__":
    main()