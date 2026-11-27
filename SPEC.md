Project Specification: Miku AI Desktop Companion (PoC)

1. Overview

Build a lightweight, interactive AI Desktop Companion application in Python for Windows. The application renders a Live2D character on a frameless, transparent, always-on-top desktop window, tracks the user's facial expressions and focus state via PC webcam, listens to voice input, responds in Japanese with a Nakano Miku persona (with Vietnamese subtitles), and performs real-time audio lip-sync.

Current Workspace State: The repository currently contains only the Live2D runtime model of Hiyori Momose (used as a placeholder avatar before swapping to Nakano Miku later). All application code, environment configuration, and directory scaffolding must be created from scratch.

2. Tech Stack & Environment Constraints

Python Version: Python 3.10 or 3.11 (strictly avoid 3.12+ due to live2d-py and mediapipe wheel compatibility on Windows). Use a local .venv.

UI & Live2D Rendering: PyQt6 (QOpenGLWidget) + live2d-py (Cubism 3/4 runtime).

Computer Vision: opencv-python + mediapipe (Face Mesh).

LLM Brain: google-genai SDK using model gemini-2.5-flash.

Speech-to-Text (STT): faster-whisper (tiny or base model) + sounddevice + Push-to-Talk hotkey (or Silero VAD).

Text-to-Speech (TTS): Local VOICEVOX Engine REST API (http://127.0.0.1:50021), with edge-tts (ja-JP-NanamiNeural) as an automatic fallback if VOICEVOX is not running.

Audio Playback & Lip-Sync: sounddevice + numpy (real-time RMS calculation).

3. Target Directory Structure

Create and organize the codebase using this modular architecture:

.
├── .env                    # GEMINI_API_KEY, VOICEVOX_URL, VOICEVOX_SPEAKER_ID
├── .env.example            # Template for environment variables
├── .gitignore
├── SPEC.md
├── requirements.txt
├── main.py                 # Entry point: wires PyQt6 UI, Vision, Audio, and AI signals
├── assets/
│   └── model/              # Move or reference the existing Hiyori Momose runtime folder here
└── src/
    ├── config.py           # Loads .env, paths, thresholds (EAR, FPS, hotkey)
    ├── ui/
    │   ├── live2d_widget.py # Transparent, frameless, draggable QOpenGLWidget + Live2D controller
    │   └── subtitle_box.py  # Floating speech bubble displaying Vietnamese subtitles
    ├── vision/
    │   └── face_tracker.py  # QThread: OpenCV + MediaPipe (smile, drowsiness/EAR, head pose, presence)
    ├── audio/
    │   ├── stt_listener.py  # QThread: Mic capture + Faster-Whisper transcription
    │   └── tts_player.py    # QThread: VOICEVOX/edge-tts + sounddevice playback + RMS signal emitter
    └── ai/
        └── gemini_brain.py  # Gemini API client with Nakano Miku system prompt & strict JSON output


4. Pre-Flight Inspection (Mandatory First Step)

Before writing any Live2D rendering code:

Scan the workspace to locate the existing Hiyori Momose model files (*.model3.json, *.moc3, *.cdi3.json).

Read the *.cdi3.json file to extract the exact Parameter IDs for:

Mouth opening (typically ParamMouthOpenY)

Mouth form/smile (ParamMouthForm)

Eye openness (ParamEyeLOpen, ParamEyeROpen)

Cheek blush (ParamCheek)

Head angles (ParamAngleX, ParamAngleY, ParamAngleZ)

Store the detected model path and parameter mapping cleanly in src/config.py so swapping to a Nakano Miku model later requires changing only config.py.

5. Core Functional Requirements

A. Live2D Desktop Window (src/ui/)

Frameless (FramelessWindowHint), transparent background (WA_TranslucentBackground), always on top (WindowStaysOnTopHint).

Left-click and drag to reposition the character anywhere on the screen; right-click context menu for basic controls (Talk, Toggle Vision, Reset Position, Quit).

Smooth parameter interpolation (lerp) when transitioning between emotions so movements look natural, not jerky.

Supported emotion states:

idle: Gentle breathing, automatic blinking, physics active.

shy / blush: Increase ParamCheek, slight head tilt, softer eye/mouth expression.

pout: Slightly furrowed brows, closed/pouty mouth (ParamMouthForm negative).

happy: Smiling mouth form, cheerful eyes.

sleepy: Half-closed or closed eyes when user is absent.

Subtitle bubble (subtitle_box.py): Semi-transparent dark rounded overlay positioned near the avatar, auto-hides 5 seconds after speech finishes.

B. Lip-Sync & Japanese Voice (src/audio/tts_player.py)

Call VOICEVOX local API (/audio_query -> /synthesis) to synthesize Japanese text into WAV bytes.

If http://127.0.0.1:50021 is unreachable, log a warning and automatically fall back to edge-tts (ja-JP-NanamiNeural).

Stream audio playback via sounddevice in ~16ms chunks (60 FPS).

Compute RMS amplitude for each chunk, normalize to [0.0, 1.0], and emit a PyQt signal mouth_open_changed(float) to update ParamMouthOpenY in real time. Reset to 0.0 when playback ends.

C. AI Brain & Persona (src/ai/gemini_brain.py)

Use google-genai (gemini-2.5-flash) with structured JSON output (response_mime_type="application/json").

Persona: Nakano Miku (Gotoubun no Hanayome). Quiet, slightly shy, sincere, caring study partner, occasionally references Sengoku-period generals (Oda Nobunaga, Takeda Shingen, etc.) when encouraging the user.

Required JSON Schema:

{
  "emotion": "idle | shy | pout | happy | sleepy",
  "japanese_text": "Short, natural spoken Japanese response (1-2 sentences)",
  "vietnamese_sub": "Natural Vietnamese translation of the response"
}


Support two triggers:

User Conversation: Responds to transcribed voice/text input.

Proactive Focus Reminder: Receives a system event (e.g., USER_DROWSY, USER_DISTRACTED) and generates a short in-character reminder without requiring user input.

D. Computer Vision & Focus Tracking (src/vision/face_tracker.py)

Run on a dedicated QThread capped at 3–5 FPS to minimize CPU usage.

Using MediaPipe Face Mesh landmarks, detect and emit debounced signals (avoid spamming):

Smile detected -> emit user_smiled -> avatar briefly switches to shy/blush.

Drowsiness detected (Eye Aspect Ratio < threshold for > 3 seconds) -> emit user_drowsy -> trigger AI focus reminder with pout or worried reaction.

Distraction detected (head turned away continuously for > 10 seconds) -> emit user_distracted -> trigger AI focus reminder.

User absent (no face detected for > 60 seconds) -> emit user_absent -> switch avatar to sleepy.

Include a cooldown timer (e.g., 60 seconds) between proactive AI reminders so the companion is not annoying.

E. Voice Input (src/audio/stt_listener.py)

Support Push-to-Talk (e.g., hold or toggle Ctrl+Shift+Space or click a mini mic button / right-click menu) to record audio from the default microphone.

Transcribe speech using faster-whisper (support Vietnamese and Japanese auto-detection) and forward the text to gemini_brain.py.

6. Execution Plan (Build & Verify Phase by Phase)

Implement strictly one phase at a time. Verify each phase runs cleanly before proceeding to the next.

Phase 1 — Project Setup & Live2D Window:

Inspect the Hiyori model files, set up .venv (Python 3.10/3.11), create requirements.txt, .env.example, and src/config.py.

Build src/ui/live2d_widget.py and main.py to render Hiyori in a transparent, draggable, always-on-top window.

Verification: App launches, Hiyori renders with transparency, blinks/moves smoothly, and can be dragged around the screen.

Phase 2 — Japanese TTS & Real-Time Lip-Sync:

Implement src/audio/tts_player.py and src/ui/subtitle_box.py.

Add a temporary test hotkey/menu item to speak a sample Japanese sentence.

Verification: Audio plays cleanly through PC speakers, subtitle appears, and Hiyori's mouth moves in sync with the audio volume.

Phase 3 — Gemini AI Brain & Voice Input (STT):

Implement src/ai/gemini_brain.py and src/audio/stt_listener.py.

Connect STT -> Gemini -> Emotion change + TTS + Subtitle.

Verification: Speaking into the mic produces an in-character Japanese voice reply, Vietnamese subtitle, and matching Live2D emotion.

Phase 4 — Webcam Vision & Focus Reminders:

Implement src/vision/face_tracker.py and connect its signals to the UI and Gemini proactive reminder flow.

Verification: Smiling triggers blush; closing eyes/looking away triggers a debounced focus reminder without freezing the UI.

7. Engineering Rules

Never block the PyQt6 Main Thread: All camera reads, Whisper inference, Gemini API calls, and TTS requests must run in background QThread workers communicating via Qt pyqtSignal.

Graceful Degradation: If the webcam, microphone, or VOICEVOX is unavailable, log a clear message and keep the rest of the app functional rather than crashing.

Clean Shutdown: Properly release OpenCV video capture, stop audio streams, and terminate worker threads on app exit.