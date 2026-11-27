"""Application configuration, paths, and Live2D parameter mappings."""

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
