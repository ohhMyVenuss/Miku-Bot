"""Transparent, frameless, draggable QOpenGLWidget for rendering Live2D models."""

import logging
from typing import Optional

import live2d
from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QContextMenuEvent,
    QGuiApplication,
    QKeySequence,
    QMouseEvent,
    QMoveEvent,
    QShortcut,
)
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QApplication, QInputDialog, QMenu

from src import config

logger = logging.getLogger(__name__)

# Neutral defaults for parameters modulated by emotion states
_EMOTION_PARAM_DEFAULTS: dict[str, float] = {
    "cheek": 0.0,
    "mouth_form": 1.0,
    "eye_left_open": 1.0,
    "eye_right_open": 1.0,
    "eye_left_smile": 0.0,
    "eye_right_smile": 0.0,
    "angle_x": 0.0,
    "angle_y": 0.0,
    "angle_z": 0.0,
    "brow_left_y": 0.0,
    "brow_right_y": 0.0,
    "brow_left_angle": 0.0,
    "brow_right_angle": 0.0,
}

# Target parameter overrides for each supported emotion state
EMOTION_PRESETS: dict[str, dict[str, float]] = {
    "idle": {},
    "shy": {
        "cheek": 1.0,
        "angle_z": 8.0,
        "angle_y": -6.0,
        "eye_left_smile": 0.5,
        "eye_right_smile": 0.5,
        "mouth_form": 0.55,
        "brow_left_y": 0.25,
        "brow_right_y": 0.25,
    },
    "pout": {
        "mouth_form": -1.0,
        "brow_left_y": -0.35,
        "brow_right_y": -0.35,
        "brow_left_angle": -0.55,
        "brow_right_angle": -0.55,
        "cheek": 0.25,
        "angle_z": -6.0,
    },
    "happy": {
        "mouth_form": 1.0,
        "eye_left_smile": 0.85,
        "eye_right_smile": 0.85,
        "cheek": 0.35,
        "brow_left_y": 0.35,
        "brow_right_y": 0.35,
        "angle_y": 4.0,
    },
    "sleepy": {
        "eye_left_open": 0.28,
        "eye_right_open": 0.28,
        "brow_left_y": -0.2,
        "brow_right_y": -0.2,
        "angle_y": -8.0,
        "angle_z": 5.0,
        "mouth_form": 0.0,
    },
}


class Live2DWidget(QOpenGLWidget):
    """Frameless, transparent, always-on-top desktop widget rendering a Live2D character."""

    position_changed = pyqtSignal()
    test_speak_requested = pyqtSignal()
    speaker_changed = pyqtSignal(int)
    talk_toggle_requested = pyqtSignal()
    quick_chat_requested = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # Frameless, always-on-top, transparent window setup
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self.setFixedSize(config.WINDOW_WIDTH, config.WINDOW_HEIGHT)
        self.setWindowTitle("AI Desktop Companion")

        self.model: Optional[live2d.Model] = None
        self._gl_initialized = False
        self._drag_offset: Optional[QPoint] = None
        self._active_speaker_id: int = config.VOICEVOX_SPEAKER_ID
        self._is_listening: bool = False

        # Real-time lip-sync state
        self._target_mouth_open: float = 0.0
        self._current_mouth_open: float = 0.0
        self._is_speaking: bool = False

        # Smooth emotion interpolation state
        self._target_emotion: str = "idle"
        self._target_emotion_blend: float = 0.0
        self._current_emotion_blend: float = 0.0
        self._target_emotion_params: dict[str, float] = dict(_EMOTION_PARAM_DEFAULTS)
        self._current_emotion_params: dict[str, float] = dict(_EMOTION_PARAM_DEFAULTS)

        self._emotion_reset_timer = QTimer(self)
        self._emotion_reset_timer.setSingleShot(True)
        self._emotion_reset_timer.timeout.connect(lambda: self.set_emotion("idle"))

        # Local window shortcuts
        self._test_speak_shortcut = QShortcut(QKeySequence("Ctrl+T"), self)
        self._test_speak_shortcut.activated.connect(self.test_speak_requested.emit)

        self._quick_chat_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        self._quick_chat_shortcut.activated.connect(self.open_quick_chat)

        # 60 FPS render loop
        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self.update)
        self._render_timer.start(max(1, 1000 // config.RENDER_FPS))

        self.reset_position()

    def reset_position(self) -> None:
        """Move the widget to the default bottom-right area of the primary screen."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        x = avail.right() - self.width() - 40
        y = avail.bottom() - self.height() - 20
        self.move(x, y)

    # ------------------------------------------------------------------
    # Emotion & Lip-Sync Slots
    # ------------------------------------------------------------------
    @pyqtSlot(str)
    def set_emotion(self, emotion: str) -> None:
        """Smoothly transition Live2D facial parameters to a target emotion."""
        normalized = (emotion or "idle").strip().lower()
        if normalized not in EMOTION_PRESETS:
            logger.warning("Unknown emotion '%s', falling back to 'idle'.", emotion)
            normalized = "idle"

        self._emotion_reset_timer.stop()
        self._target_emotion = normalized
        self._target_emotion_blend = 0.0 if normalized == "idle" else 1.0

        next_params = dict(_EMOTION_PARAM_DEFAULTS)
        next_params.update(EMOTION_PRESETS[normalized])
        self._target_emotion_params = next_params
        logger.info("Emotion set to: %s", normalized)

    @pyqtSlot(bool)
    def set_listening_state(self, is_listening: bool) -> None:
        """Track microphone listening state for context menu labels."""
        self._is_listening = is_listening

    @pyqtSlot(str)
    def on_speech_started(self, _subtitle: str) -> None:
        """Mark avatar as actively speaking so lip-sync overrides idle mouth motion."""
        self._emotion_reset_timer.stop()
        self._is_speaking = True

    @pyqtSlot(float)
    def set_mouth_open(self, value: float) -> None:
        """Update target mouth openness [0.0, 1.0] from TTS audio RMS."""
        self._target_mouth_open = min(1.0, max(0.0, float(value)))

    @pyqtSlot()
    def on_speech_finished(self) -> None:
        """Reset lip-sync and schedule smooth return to idle emotion."""
        self._is_speaking = False
        self._target_mouth_open = 0.0
        if self._target_emotion != "idle":
            self._emotion_reset_timer.start(config.EMOTION_RESET_DELAY_MS)

    @pyqtSlot()
    def open_quick_chat(self) -> None:
        """Prompt the user for a text message to send directly to Gemini."""
        text, ok = QInputDialog.getText(
            self,
            "Quick Chat",
            "Nhập tin nhắn:",
        )
        if ok and text.strip():
            self.quick_chat_requested.emit(text.strip())

    # ------------------------------------------------------------------
    # OpenGL Lifecycle
    # ------------------------------------------------------------------
    def initializeGL(self) -> None:
        """Initialize OpenGL bindings and load the Live2D model."""
        try:
            live2d.glInit()
            self._gl_initialized = True
        except RuntimeError as exc:
            logger.warning("live2d.glInit() skipped or failed: %s", exc)

        if not config.MODEL_JSON_PATH.exists():
            logger.error("Model file not found: %s", config.MODEL_JSON_PATH)
            return

        self.model = live2d.Model()
        self.model.LoadModelJson(str(config.MODEL_JSON_PATH))
        self.model.SetAutoBreath(True)
        self.model.SetAutoBlink(True)

        dpr = self.devicePixelRatioF()
        self.model.Resize(int(self.width() * dpr), int(self.height() * dpr))
        logger.info("Loaded Live2D model: %s", config.MODEL_JSON_PATH.name)

    def resizeGL(self, w: int, h: int) -> None:
        """Resize the Live2D viewport when widget dimensions change."""
        if self.model is not None:
            dpr = self.devicePixelRatioF()
            self.model.Resize(int(w * dpr), int(h * dpr))

    def paintGL(self) -> None:
        """Clear transparent buffer, update motion/emotion/lip-sync, and draw frame."""
        live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
        if self.model is None:
            return

        self.model.Update()

        # Smoothly interpolate active emotion blend and parameter targets
        lerp_speed = config.EMOTION_LERP_SPEED
        self._current_emotion_blend += (
            self._target_emotion_blend - self._current_emotion_blend
        ) * lerp_speed
        if self._target_emotion == "idle" and self._current_emotion_blend < 0.005:
            self._current_emotion_blend = 0.0

        for key, target_val in self._target_emotion_params.items():
            cur_val = self._current_emotion_params[key]
            self._current_emotion_params[key] = cur_val + (target_val - cur_val) * lerp_speed

        if self._current_emotion_blend > 0.0:
            for key, cur_val in self._current_emotion_params.items():
                if (
                    key in ("eye_left_open", "eye_right_open")
                    and self._target_emotion_params[key] == 1.0
                    and abs(cur_val - 1.0) < 0.02
                ):
                    continue
                param_id = config.LIVE2D_PARAMS.get(key)
                if param_id:
                    self.model.SetParamById(
                        param_id,
                        cur_val,
                        self._current_emotion_blend,
                    )

        # Smoothly interpolate mouth openness and apply AFTER Update()
        # so idle motions cannot overwrite mouth movement while speaking.
        self._current_mouth_open += (
            self._target_mouth_open - self._current_mouth_open
        ) * 0.55
        if not self._is_speaking and self._current_mouth_open < 0.005:
            self._current_mouth_open = 0.0

        if self._is_speaking or self._current_mouth_open > 0.0:
            self.model.SetParamById(
                config.LIVE2D_PARAMS["mouth_open"],
                self._current_mouth_open,
            )

        self.model.Draw()

    # ------------------------------------------------------------------
    # Mouse Dragging & Context Menu
    # ------------------------------------------------------------------
    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        self.position_changed.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def _select_speaker(self, speaker_id: int) -> None:
        self._active_speaker_id = speaker_id
        self.speaker_changed.emit(speaker_id)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)

        talk_label = (
            "Stop Talking\tCtrl+Shift+Space"
            if self._is_listening
            else "Talk (Mic)\tCtrl+Shift+Space"
        )
        talk_action = QAction(talk_label, self)
        talk_action.triggered.connect(self.talk_toggle_requested.emit)
        menu.addAction(talk_action)

        quick_chat_action = QAction("Quick Chat (Text)...\tCtrl+Enter", self)
        quick_chat_action.triggered.connect(self.open_quick_chat)
        menu.addAction(quick_chat_action)

        test_speak_action = QAction("Test Speak (Tsundere)\tCtrl+T", self)
        test_speak_action.triggered.connect(self.test_speak_requested.emit)
        menu.addAction(test_speak_action)

        voice_menu = menu.addMenu("VOICEVOX Speaker")
        speaker_group = QActionGroup(voice_menu)
        speaker_group.setExclusive(True)
        for label, speaker_id in config.VOICEVOX_SPEAKER_PRESETS:
            action = QAction(f"{label} [ID {speaker_id}]", voice_menu, checkable=True)
            action.setChecked(speaker_id == self._active_speaker_id)
            action.triggered.connect(
                lambda _checked, sid=speaker_id: self._select_speaker(sid)
            )
            speaker_group.addAction(action)
            voice_menu.addAction(action)

        menu.addSeparator()

        reset_action = QAction("Reset Position", self)
        reset_action.triggered.connect(self.reset_position)
        menu.addAction(reset_action)

        menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(quit_action)

        menu.exec(event.globalPos())

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------
    def cleanup(self) -> None:
        """Stop timers and release OpenGL/Live2D resources."""
        if self._emotion_reset_timer.isActive():
            self._emotion_reset_timer.stop()
        if self._render_timer.isActive():
            self._render_timer.stop()

        if self.model is not None:
            self.makeCurrent()
            try:
                self.model.DestroyRenderer()
            except Exception as exc:
                logger.debug("DestroyRenderer warning: %s", exc)
            finally:
                self.doneCurrent()
            self.model = None

        if self._gl_initialized:
            try:
                live2d.glRelease()
            except Exception as exc:
                logger.debug("glRelease warning: %s", exc)
            self._gl_initialized = False

    def quit_app(self) -> None:
        """Clean up resources and exit the application."""
        self.cleanup()
        QApplication.quit()

    def closeEvent(self, event) -> None:
        self.cleanup()
        super().closeEvent(event)
