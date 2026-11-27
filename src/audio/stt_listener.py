"""Speech-to-Text listener using sounddevice, faster-whisper, and global hotkey."""

import logging
import queue
import threading
from typing import Optional

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from pynput import keyboard
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot

from src import config

logger = logging.getLogger(__name__)


class STTListener(QThread):
    """Background QThread for mic recording (toggle/PTT) and Faster-Whisper transcription."""

    listening_started = pyqtSignal()
    listening_stopped = pyqtSignal()
    text_transcribed = pyqtSignal(str)
    stt_error = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._audio_queue: queue.Queue[Optional[np.ndarray]] = queue.Queue()
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()

        self._is_listening = False
        self._frames: list[np.ndarray] = []
        self._stream: Optional[sd.InputStream] = None
        self._model: Optional[WhisperModel] = None
        self._hotkey_listener: Optional[keyboard.GlobalHotKeys] = None

    @property
    def is_listening(self) -> bool:
        with self._state_lock:
            return self._is_listening

    def start_global_hotkey(self) -> None:
        """Register the global Ctrl+Shift+Space toggle hotkey safely."""
        if self._hotkey_listener is not None:
            return
        try:
            self._hotkey_listener = keyboard.GlobalHotKeys(
                {config.STT_HOTKEY: self.toggle_listening}
            )
            self._hotkey_listener.start()
            logger.info("Registered global STT hotkey: %s", config.STT_HOTKEY)
        except Exception as exc:
            logger.warning("Could not register global STT hotkey: %s", exc)
            self._hotkey_listener = None

    def _stop_global_hotkey(self) -> None:
        if self._hotkey_listener is not None:
            try:
                self._hotkey_listener.stop()
            except Exception as exc:
                logger.debug("Hotkey listener stop warning: %s", exc)
            self._hotkey_listener = None

    @pyqtSlot()
    def toggle_listening(self) -> None:
        """Toggle microphone recording on or off."""
        if self.is_listening:
            self.stop_listening()
        else:
            self.start_listening()

    @pyqtSlot()
    def start_listening(self) -> None:
        """Open default microphone stream and start recording audio frames."""
        with self._state_lock:
            if self._is_listening or self._stop_event.is_set():
                return

            self._frames = []

            def _audio_callback(indata, _frames_count, _time_info, status) -> None:
                if status:
                    logger.debug("Mic input status: %s", status)
                self._frames.append(indata.copy())

            try:
                stream = sd.InputStream(
                    samplerate=config.STT_SAMPLE_RATE,
                    channels=1,
                    dtype="float32",
                    callback=_audio_callback,
                )
                stream.start()
                self._stream = stream
                self._is_listening = True
            except Exception as exc:
                logger.error("Failed to open microphone: %s", exc)
                self._stream = None
                self._is_listening = False
                self.stt_error.emit(f"Không thể mở micro: {exc}")
                return

        logger.info("Microphone recording started.")
        self.listening_started.emit()

    @pyqtSlot()
    def stop_listening(self) -> None:
        """Stop microphone recording and queue captured audio for transcription."""
        with self._state_lock:
            if not self._is_listening:
                return
            self._is_listening = False
            stream = self._stream
            self._stream = None
            frames = self._frames
            self._frames = []

        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:
                logger.debug("InputStream close warning: %s", exc)

        logger.info("Microphone recording stopped.")
        self.listening_stopped.emit()

        if not frames:
            self.stt_error.emit("Không thu được âm thanh từ micro.")
            return

        audio_np = np.concatenate(frames, axis=0).flatten().astype(np.float32)
        duration_sec = len(audio_np) / float(config.STT_SAMPLE_RATE)
        if duration_sec < 0.25:
            self.stt_error.emit("Đoạn ghi âm quá ngắn, hãy nói lâu hơn một chút.")
            return

        self._audio_queue.put(audio_np)

    def _ensure_model(self) -> WhisperModel:
        """Load Faster-Whisper model on CPU (int8) if not yet initialized."""
        if self._model is None:
            logger.info(
                "Loading faster-whisper model '%s' (cpu, %s)...",
                config.WHISPER_MODEL_SIZE,
                config.WHISPER_COMPUTE_TYPE,
            )
            self._model = WhisperModel(
                config.WHISPER_MODEL_SIZE,
                device="cpu",
                compute_type=config.WHISPER_COMPUTE_TYPE,
            )
            logger.info("Faster-Whisper model ready.")
        return self._model

    def load_model(self) -> WhisperModel:
        """Public helper to verify/preload the Whisper model."""
        return self._ensure_model()

    def _transcribe_audio(self, audio_np: np.ndarray) -> str:
        """Transcribe 16kHz mono float32 audio (supports Vietnamese & Japanese auto-detect)."""
        model = self._ensure_model()
        try:
            segments, info = model.transcribe(
                audio_np,
                language=None,
                beam_size=3,
                vad_filter=True,
            )
        except Exception as vad_exc:
            logger.debug("VAD transcribe failed (%s), retrying without VAD.", vad_exc)
            segments, info = model.transcribe(
                audio_np,
                language=None,
                beam_size=3,
                vad_filter=False,
            )

        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip()).strip()
        logger.info(
            "Transcribed [%s, p=%.2f]: %s",
            getattr(info, "language", "unknown"),
            getattr(info, "language_probability", 0.0),
            text,
        )
        return text

    def shutdown(self) -> None:
        """Stop hotkey listener, mic stream, and worker thread cleanly."""
        self._stop_global_hotkey()
        if self.is_listening:
            with self._state_lock:
                self._is_listening = False
                stream = self._stream
                self._stream = None
                self._frames = []
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception as exc:
                    logger.debug("Shutdown mic stream warning: %s", exc)

        self._stop_event.set()
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break
        self._audio_queue.put(None)
        if self.isRunning():
            self.wait(5000)

    def run(self) -> None:
        """Preload Whisper model and transcribe queued audio buffers."""
        self.start_global_hotkey()
        try:
            self._ensure_model()
        except Exception as exc:
            logger.warning("Preloading faster-whisper failed: %s", exc)

        while not self._stop_event.is_set():
            try:
                audio_np = self._audio_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if audio_np is None:
                break

            try:
                text = self._transcribe_audio(audio_np)
                if text:
                    self.text_transcribed.emit(text)
                else:
                    self.stt_error.emit("Không nhận diện được lời nói, bạn thử nói lại nhé.")
            except Exception as exc:
                logger.error("STT transcription error: %s", exc)
                self.stt_error.emit(f"Lỗi nhận diện giọng nói: {exc}")
