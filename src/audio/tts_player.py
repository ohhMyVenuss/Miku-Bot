"""Japanese TTS synthesis (VOICEVOX with edge-tts fallback) and real-time lip-sync playback."""

import asyncio
import io
import logging
import queue
import threading
from typing import Optional

import edge_tts
import numpy as np
import requests
import sounddevice as sd
import soundfile as sf
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot

from src import config

logger = logging.getLogger(__name__)


class TTSPlayer(QThread):
    """Background QThread that synthesizes Japanese speech and streams PCM for lip-sync."""

    speech_started = pyqtSignal(str)
    mouth_open_changed = pyqtSignal(float)
    speech_finished = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._queue: queue.Queue[Optional[tuple[str, str]]] = queue.Queue()
        self._stop_event = threading.Event()
        self._interrupt_event = threading.Event()
        self._speaker_id: int = config.VOICEVOX_SPEAKER_ID

    @pyqtSlot(int)
    def set_speaker_id(self, speaker_id: int) -> None:
        """Update the active VOICEVOX speaker ID."""
        self._speaker_id = int(speaker_id)
        logger.info("VOICEVOX speaker ID changed to %d", self._speaker_id)

    def speak(self, japanese_text: str, subtitle: str = "") -> None:
        """Enqueue a Japanese utterance with its display subtitle."""
        if not japanese_text.strip():
            return
        display_sub = subtitle.strip() or japanese_text.strip()
        self._queue.put((japanese_text.strip(), display_sub))

    def interrupt(self) -> None:
        """Interrupt the currently playing utterance without stopping the worker."""
        self._interrupt_event.set()

    def shutdown(self) -> None:
        """Stop playback, drain pending items, and terminate the worker thread cleanly."""
        self._stop_event.set()
        self._interrupt_event.set()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._queue.put(None)
        if self.isRunning():
            self.wait(3000)

    # ------------------------------------------------------------------
    # Synthesis backends
    # ------------------------------------------------------------------
    def synthesize(self, japanese_text: str) -> tuple[bytes, str]:
        """Synthesize Japanese text via VOICEVOX, falling back to edge-tts on failure.

        Returns:
            Tuple of (encoded_audio_bytes, backend_name).
        """
        try:
            audio_bytes = self._synthesize_voicevox(japanese_text)
            return audio_bytes, f"voicevox (speaker={self._speaker_id})"
        except (requests.RequestException, ValueError) as exc:
            logger.warning(
                "VOICEVOX unavailable at %s (%s). Falling back to edge-tts (%s, pitch=%s, rate=%s).",
                config.VOICEVOX_URL,
                exc,
                config.EDGE_TTS_VOICE,
                config.EDGE_TTS_PITCH,
                config.EDGE_TTS_RATE,
            )
            audio_bytes = self._synthesize_edge_tts(japanese_text)
            return audio_bytes, "edge-tts"

    def _synthesize_voicevox(self, text: str) -> bytes:
        """Call VOICEVOX local REST API (/audio_query -> /synthesis) to produce WAV bytes."""
        speaker_id = self._speaker_id
        query_resp = requests.post(
            f"{config.VOICEVOX_URL}/audio_query",
            params={"text": text, "speaker": speaker_id},
            timeout=(config.VOICEVOX_TIMEOUT_SEC, 5.0),
        )
        query_resp.raise_for_status()
        query_json = query_resp.json()

        synth_resp = requests.post(
            f"{config.VOICEVOX_URL}/synthesis",
            params={"speaker": speaker_id},
            json=query_json,
            timeout=(config.VOICEVOX_TIMEOUT_SEC, 15.0),
        )
        synth_resp.raise_for_status()
        if not synth_resp.content:
            raise ValueError("VOICEVOX returned empty audio content")
        return synth_resp.content

    def _synthesize_edge_tts(self, text: str) -> bytes:
        """Synthesize Japanese speech via edge-tts into MP3 bytes."""

        async def _collect() -> bytes:
            communicate = edge_tts.Communicate(
                text,
                voice=config.EDGE_TTS_VOICE,
                pitch=config.EDGE_TTS_PITCH,
                rate=config.EDGE_TTS_RATE,
            )
            chunks = bytearray()
            async for message in communicate.stream():
                if message.get("type") == "audio":
                    chunks.extend(message["data"])
            return bytes(chunks)

        audio_bytes = asyncio.run(_collect())
        if not audio_bytes:
            raise RuntimeError("edge-tts returned empty audio stream")
        return audio_bytes

    # ------------------------------------------------------------------
    # Audio decoding & streaming lip-sync
    # ------------------------------------------------------------------
    @staticmethod
    def _decode_audio(audio_bytes: bytes) -> tuple[np.ndarray, int]:
        """Decode WAV or MP3 bytes into float32 PCM array (frames, channels) and sample rate."""
        try:
            pcm, sample_rate = sf.read(
                io.BytesIO(audio_bytes), dtype="float32", always_2d=True
            )
            return pcm, int(sample_rate)
        except Exception as sf_exc:
            logger.debug("soundfile decode failed (%s), trying pydub fallback.", sf_exc)
            from pydub import AudioSegment

            segment = AudioSegment.from_file(io.BytesIO(audio_bytes))
            samples = np.array(segment.get_array_of_samples(), dtype=np.float32)
            peak = float(1 << (8 * segment.sample_width - 1))
            samples /= peak
            pcm = samples.reshape((-1, segment.channels))
            return pcm, int(segment.frame_rate)

    def _play_with_lipsync(self, pcm: np.ndarray, sample_rate: int, subtitle: str) -> None:
        """Stream PCM in ~16ms chunks via sounddevice and emit RMS mouth openness."""
        chunk_frames = max(1, int(sample_rate * config.LIPSYNC_CHUNK_MS / 1000))
        channels = pcm.shape[1]
        smoothed_mouth = 0.0
        smoothing = min(max(config.LIPSYNC_SMOOTHING, 0.0), 0.95)
        stream: Optional[sd.OutputStream] = None

        try:
            stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="float32",
            )
            stream.start()
            self.speech_started.emit(subtitle)

            total_frames = pcm.shape[0]
            for start in range(0, total_frames, chunk_frames):
                if self._stop_event.is_set() or self._interrupt_event.is_set():
                    break

                chunk = pcm[start : start + chunk_frames]
                stream.write(chunk)

                rms = float(np.sqrt(np.mean(np.square(chunk))))
                raw_open = min(1.0, max(0.0, rms * config.LIPSYNC_RMS_GAIN))
                smoothed_mouth = (
                    smoothed_mouth * smoothing + raw_open * (1.0 - smoothing)
                )
                self.mouth_open_changed.emit(float(smoothed_mouth))
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception as exc:
                    logger.debug("OutputStream cleanup warning: %s", exc)
            self.mouth_open_changed.emit(0.0)
            self.speech_finished.emit()

    # ------------------------------------------------------------------
    # QThread main loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Process queued speech requests until shutdown is requested."""
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if item is None:
                break

            japanese_text, subtitle = item
            self._interrupt_event.clear()

            try:
                audio_bytes, backend = self.synthesize(japanese_text)
                logger.info("Synthesized speech via %s (%d bytes)", backend, len(audio_bytes))
                pcm, sample_rate = self._decode_audio(audio_bytes)
                if not self._stop_event.is_set():
                    self._play_with_lipsync(pcm, sample_rate, subtitle)
            except Exception as exc:
                logger.error("TTS playback failed: %s", exc)
                self.mouth_open_changed.emit(0.0)
                self.speech_finished.emit()
