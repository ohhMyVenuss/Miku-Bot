"""Application configuration, paths, and Live2D parameter mappings."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base project directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env if present
load_dotenv(BASE_DIR / ".env")

# Asset & Model paths
ASSETS_DIR = BASE_DIR / "assets"
MODEL_DIR = ASSETS_DIR / "model" / "hiyori"
MODEL_JSON_PATH = MODEL_DIR / "hiyori_pro_t11.model3.json"

# Window & Rendering settings
WINDOW_WIDTH = 420
WINDOW_HEIGHT = 560
RENDER_FPS = 60
EMOTION_LERP_SPEED = 0.12
EMOTION_RESET_DELAY_MS = 3500

# TTS & Lip-Sync settings (Phase 2)
VOICEVOX_URL = os.getenv("VOICEVOX_URL", "http://127.0.0.1:50021").rstrip("/")
VOICEVOX_SPEAKER_ID = int(os.getenv("VOICEVOX_SPEAKER_ID", "8"))
VOICEVOX_TIMEOUT_SEC = 1.5
VOICEVOX_SPEAKER_PRESETS = [
    ("Kasukabe Tsumugi (Trẻ, dễ thương)", 8),
    ("Shikoku Metan - Amaama (Ngọt ngào)", 0),
    ("Meimei Himari (Dịu dàng)", 14),
    ("Zundamon - Amaama (Nhí nhảnh)", 1),
]
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "ja-JP-NanamiNeural")
EDGE_TTS_PITCH = os.getenv("EDGE_TTS_PITCH", "+12Hz")
EDGE_TTS_RATE = os.getenv("EDGE_TTS_RATE", "+4%")
LIPSYNC_CHUNK_MS = 16
LIPSYNC_RMS_GAIN = 4.5
LIPSYNC_SMOOTHING = 0.45
SUBTITLE_HIDE_DELAY_MS = 5000

# AI & Gemini Brain settings (Phase 3)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip() or "gemini-3.5-flash-lite"
GEMINI_FALLBACK_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-4-hydrogen",
]
GEMINI_TIMEOUT_MS = 12000
GEMINI_HISTORY_TURNS = 8

# Speech-to-Text settings (Phase 3)
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
STT_SAMPLE_RATE = 16000
STT_HOTKEY = "<ctrl>+<shift>+<space>"

# Live2D Parameter IDs (verified from hiyori_pro_t11.cdi3.json)
# Swap these mappings when changing to a Nakano Miku model.
LIVE2D_PARAMS = {
    # Mouth
    "mouth_open": "ParamMouthOpenY",
    "mouth_form": "ParamMouthForm",
    # Eyes
    "eye_left_open": "ParamEyeLOpen",
    "eye_right_open": "ParamEyeROpen",
    "eye_left_smile": "ParamEyeLSmile",
    "eye_right_smile": "ParamEyeRSmile",
    "eyeball_x": "ParamEyeBallX",
    "eyeball_y": "ParamEyeBallY",
    # Face / Blush / Head Angles
    "cheek": "ParamCheek",
    "angle_x": "ParamAngleX",
    "angle_y": "ParamAngleY",
    "angle_z": "ParamAngleZ",
    # Eyebrows
    "brow_left_y": "ParamBrowLY",
    "brow_right_y": "ParamBrowRY",
    "brow_left_angle": "ParamBrowLAngle",
    "brow_right_angle": "ParamBrowRAngle",
    "brow_left_form": "ParamBrowLForm",
    "brow_right_form": "ParamBrowRForm",
    # Body & Breathing
    "body_angle_x": "ParamBodyAngleX",
    "body_angle_y": "ParamBodyAngleY",
    "body_angle_z": "ParamBodyAngleZ",
    "breath": "ParamBreath",
}
