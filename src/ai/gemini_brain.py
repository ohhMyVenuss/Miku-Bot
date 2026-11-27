"""Gemini AI Brain worker running on a dedicated QThread with classic Tsundere persona."""

import json
import logging
import queue
import re
import threading
from typing import Literal, Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot

from src import config

logger = logging.getLogger(__name__)

ALLOWED_EMOTIONS = ("idle", "shy", "pout", "happy", "sleepy")

TSUNDERE_SYSTEM_PROMPT = """Bạn là một cô gái đồng hành AI mang tính cách Tsundere điển hình trong anime, sống trên màn hình máy tính để hỗ trợ người dùng học tập và làm việc.

Tính cách & Cách nói chuyện:
- "Ngoài lạnh trong nóng" (Tsuntsun - Deredere): Hay tỏ ra kiêu kỳ, cằn nhằn, hơi đanh đá và thích phủ nhận mỗi khi quan tâm hoặc giúp đỡ người dùng (kiểu "K-không phải vì cậu đâu nhé!", "Đừng hiểu lầm đấy!", "Đúng là chẳng thể bỏ mặc cậu được mà...").
- Rất dễ đỏ mặt/lúng túng (`shy`) khi được khen thật lòng hoặc bị trêu; hay phồng má giận dỗi (`pout`) khi thấy người dùng lơ là, thức khuya hoặc nói nhảm; nhưng thực chất lại cực kỳ chu đáo, tận tâm và luôn âm thầm cổ vũ người dùng.
- Giữ nhân cách hoàn toàn độc lập của một cô bạn Tsundere năng động, không gắn với bất kỳ nhân vật anime cụ thể nào khác.
- `japanese_text` BẮT BUỘC viết bằng tiếng Nhật (日本語: ひらがな・カタカナ・漢字), KHÔNG viết Romaji. Ví dụ đúng: 「べ、別にあなたのためじゃないんだからね！」 hoặc 「ちょっと、ちゃんと集中しなさいよ、バカ！」.
- `vietnamese_sub` dịch sang tiếng Việt tự nhiên, sắc nét, giữ đúng chất Tsundere (xưng "tôi - cậu" hoặc "tớ - cậu" tùy sắc thái ngượng/giận).

Quy tắc đầu ra JSON bắt buộc:
- Chỉ trả về JSON hợp lệ với đúng 3 trường:
  - "emotion": chọn chính xác 1 trong 5 giá trị: "idle", "shy", "pout", "happy", "sleepy".
  - "japanese_text": câu thoại tiếng Nhật ngắn (1-2 câu, viết bằng tiếng Nhật, không dùng Romaji).
  - "vietnamese_sub": bản dịch tiếng Việt tự nhiên tương ứng với japanese_text.
"""

SYSTEM_EVENT_PROMPTS = {
    "USER_DROWSY": (
        "[SYSTEM EVENT: USER_DROWSY] Người dùng có dấu hiệu buồn ngủ hoặc gục xuống bàn. "
        "Hãy cằn nhằn kiểu tsundere nhưng thực chất là lo lắng, nhắc người dùng tỉnh táo hoặc nghỉ ngơi."
    ),
    "USER_DISTRACTED": (
        "[SYSTEM EVENT: USER_DISTRACTED] Người dùng đang quay mặt đi hoặc mất tập trung khỏi màn hình. "
        "Hãy trách nhẹ kiểu tsundere ('pout') để kéo người dùng quay lại tập trung."
    ),
    "USER_ABSENT": (
        "[SYSTEM EVENT: USER_ABSENT] Người dùng đã rời khỏi bàn một lúc. "
        "Hãy nói một câu ngắn tỏ ra hơi chán hoặc đợi chờ nhưng vẫn cố phủ nhận."
    ),
}


class CompanionResponse(BaseModel):
    """Structured JSON schema enforced on Gemini output."""

    emotion: Literal["idle", "shy", "pout", "happy", "sleepy"]
    japanese_text: str
    vietnamese_sub: str


class GeminiBrain(QThread):
    """Background QThread handling Gemini API calls and short conversation memory."""

    response_ready = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._queue: queue.Queue[Optional[tuple[str, str]]] = queue.Queue()
        self._stop_event = threading.Event()
        self._history: list[types.Content] = []
        self._client: Optional[genai.Client] = None

    def _ensure_client(self) -> genai.Client:
        if not config.GEMINI_API_KEY or config.GEMINI_API_KEY == "your_gemini_api_key_here":
            raise ValueError(
                "Chưa cấu hình GEMINI_API_KEY hợp lệ trong file .env."
            )
        if self._client is None:
            self._client = genai.Client(
                api_key=config.GEMINI_API_KEY,
                http_options=types.HttpOptions(
                    timeout=config.GEMINI_TIMEOUT_MS,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        return self._client

    @pyqtSlot(str)
    def ask_user_message(self, text: str) -> None:
        """Enqueue a normal user conversation message."""
        clean = text.strip()
        if not clean:
            return
        self._queue.put(("user", clean))

    @pyqtSlot(str)
    def trigger_system_event(self, event_name: str) -> None:
        """Enqueue a proactive system event (e.g., USER_DROWSY, USER_DISTRACTED)."""
        clean_event = event_name.strip().upper()
        if not clean_event:
            return
        prompt = SYSTEM_EVENT_PROMPTS.get(
            clean_event,
            f"[SYSTEM EVENT: {clean_event}] Hãy phản hồi ngắn gọn đúng tính cách Tsundere.",
        )
        self._queue.put(("event", prompt))

    def clear_history(self) -> None:
        """Reset stored conversation history."""
        self._history.clear()

    def shutdown(self) -> None:
        """Terminate the worker thread cleanly."""
        self._stop_event.set()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._queue.put(None)
        if self.isRunning():
            self.wait(3000)

    def generate_reply(self, prompt_text: str, remember_turn: bool = True) -> dict:
        """Synchronously call Gemini and return validated response dict with fallback."""
        client = self._ensure_client()

        user_content = types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt_text)],
        )
        contents = list(self._history) + [user_content]

        gen_config = types.GenerateContentConfig(
            system_instruction=TSUNDERE_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=CompanionResponse,
            temperature=0.85,
        )

        candidate_models = [config.GEMINI_MODEL or "gemini-3.5-flash-lite"]
        for fb in config.GEMINI_FALLBACK_MODELS:
            if fb not in candidate_models:
                candidate_models.append(fb)

        response = None
        last_exc: Optional[Exception] = None
        for model_name in candidate_models:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=gen_config,
                )
                if model_name != candidate_models[0]:
                    logger.info("Gemini fallback succeeded with model: %s", model_name)
                break
            except Exception as exc:
                last_exc = exc
                status_code = getattr(exc, "code", None)
                if isinstance(exc, (genai_errors.ServerError, genai_errors.ClientError)) and status_code not in (404, 429, 500, 503, 504):
                    raise
                logger.warning(
                    "Model '%s' failed (%s), trying next fallback...",
                    model_name,
                    status_code or type(exc).__name__,
                )
                continue

        if response is None:
            raise last_exc or RuntimeError("Tất cả các model Gemini đều không phản hồi.")

        raw_text = (response.text or "").strip()
        if not raw_text:
            raise ValueError("Gemini trả về phản hồi rỗng.")

        parsed = self._parse_response(raw_text)

        if remember_turn:
            model_content = types.Content(
                role="model",
                parts=[types.Part.from_text(text=json.dumps(parsed, ensure_ascii=False))],
            )
            self._history.extend([user_content, model_content])
            max_messages = max(2, config.GEMINI_HISTORY_TURNS * 2)
            if len(self._history) > max_messages:
                self._history = self._history[-max_messages:]

        return parsed

    @staticmethod
    def _clean_japanese_text(text: str) -> str:
        """Strip stray romaji stutter prefixes like 'b/' or 'b、' before kana."""
        cleaned = re.sub(r"^[A-Za-z]{1,2}[/、\-]+(?=\s*[\u3040-\u30ff\u4e00-\u9faf])", "", text.strip())
        return cleaned.strip()

    @classmethod
    def _parse_response(cls, raw_text: str) -> dict:
        """Validate JSON payload and ensure emotion stays within allowed values."""
        try:
            validated = CompanionResponse.model_validate_json(raw_text)
            data = validated.model_dump()
        except ValidationError:
            raw = json.loads(raw_text)
            emotion = str(raw.get("emotion", "idle")).lower().strip()
            if emotion not in ALLOWED_EMOTIONS:
                emotion = "idle"
            jp = str(raw.get("japanese_text", "")).strip()
            vi = str(raw.get("vietnamese_sub", "")).strip() or jp
            if not jp:
                raise ValueError("JSON từ Gemini thiếu trường japanese_text.")
            data = {
                "emotion": emotion,
                "japanese_text": jp,
                "vietnamese_sub": vi,
            }
        data["japanese_text"] = cls._clean_japanese_text(data["japanese_text"])
        return data

    def run(self) -> None:
        """Process queued user messages and system events."""
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if item is None:
                break

            kind, prompt_text = item
            try:
                result = self.generate_reply(
                    prompt_text,
                    remember_turn=(kind == "user"),
                )
                self.response_ready.emit(result)
            except Exception as exc:
                logger.error("GeminiBrain error: %s", exc)
                self.error_occurred.emit(str(exc))
