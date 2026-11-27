"""Entry point for the AI Desktop Companion (Phase 3)."""

import logging
import random
import sys

import live2d
from PyQt6.QtGui import QSurfaceFormat
from PyQt6.QtWidgets import QApplication

from src.ai.gemini_brain import GeminiBrain
from src.audio.stt_listener import STTListener
from src.audio.tts_player import TTSPlayer
from src.ui.live2d_widget import Live2DWidget
from src.ui.subtitle_box import SubtitleBox

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

SAMPLE_TSUNDERE_LINES = [
    (
        "べ、別に…あなたのために心配したわけじゃないんだからね！",
        "K-không phải tôi lo cho cậu đâu nhé, đừng có hiểu lầm đấy!",
    ),
    (
        "はぁ…本当に放っておけないんだから。わからないなら教えてあげるわよ。",
        "Haizz... Đúng là chẳng thể bỏ mặc cậu được mà. Không hiểu thì để tôi chỉ cho.",
    ),
    (
        "ちょっと！よそ見ばっかりして、ちゃんと集中しなさいよ、バカ！",
        "Này! Cứ nhìn đi đâu thế hả, lo tập trung vào đi chứ, đồ ngốc!",
    ),
    (
        "ま、まあ…今日のあなたは、ちょっとだけ頑張ってるんじゃない？べ、別に褒めてるわけじゃないけど！",
        "Th-thì... hôm nay cậu cũng có chút cố gắng đấy chứ? K-không phải tôi khen cậu đâu nhé!",
    ),
    (
        "眠いなら少し休めば？…倒れられたりしたら、こっちが困るんだから。",
        "Buồn ngủ thì nghỉ một chút đi? ...Cậu mà ngã ra đấy thì tôi phiền lắm đấy.",
    ),
    (
        "な、何よその顔は！じろじろ見ないでってば！",
        "C-cái vẻ mặt đó là sao hả! Đừng có nhìn chằm chằm tôi như thế chứ!",
    ),
    (
        "ほら、これでも飲んで気合い入れなさい。…たまたま余ってただけだからね。",
        "Nè, uống tạm đi rồi lấy lại tinh thần đi. ...Chỉ là tiện tay dư ra thôi đấy nhé.",
    ),
    (
        "むぅ…またサボろうとしてるでしょ？お見通しなんだからね！",
        "Hừm... Lại định lười biếng nữa đúng không? Tôi nhìn thấu hết rồi đấy nhé!",
    ),
    (
        "べ、別に待ってたわけじゃないし！ただ暇だっただけなんだから！",
        "Tôi đ-đâu có đợi cậu đâu! Chỉ là đang rảnh rỗi chút thôi mà!",
    ),
    (
        "しょうがないわね…今回だけ特別に、最後まで付き合ってあげる。",
        "Đành chịu vậy... Chỉ lần này đặc biệt tôi sẽ ở cùng cậu đến lúc xong việc đấy.",
    ),
]


def configure_opengl_surface() -> None:
    """Configure default OpenGL surface format with 8-bit alpha for transparency."""
    fmt = QSurfaceFormat()
    fmt.setAlphaBufferSize(8)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)


def main() -> int:
    configure_opengl_surface()
    live2d.init()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    widget = Live2DWidget()
    subtitle_box = SubtitleBox(anchor_widget=widget)
    tts_player = TTSPlayer()
    gemini_brain = GeminiBrain()
    stt_listener = STTListener()

    # 1. Wire TTS lifecycle & lip-sync signals to UI
    tts_player.speech_started.connect(widget.on_speech_started)
    tts_player.speech_started.connect(subtitle_box.show_subtitle)
    tts_player.mouth_open_changed.connect(widget.set_mouth_open)
    tts_player.speech_finished.connect(widget.on_speech_finished)
    tts_player.speech_finished.connect(subtitle_box.schedule_hide)

    # 2. Keep subtitle bubble anchored and allow live VOICEVOX speaker switching
    widget.position_changed.connect(subtitle_box.reposition)
    widget.speaker_changed.connect(tts_player.set_speaker_id)

    # 3. Wire STT -> Gemini -> Emotion + TTS + Subtitle pipeline
    def send_user_message(text: str) -> None:
        subtitle_box.show_status("Đang suy nghĩ...")
        gemini_brain.ask_user_message(text)

    def on_stt_listening_started() -> None:
        widget.set_listening_state(True)
        subtitle_box.show_status("Đang nghe... (bấm Ctrl+Shift+Space để dừng)")

    def on_stt_listening_stopped() -> None:
        widget.set_listening_state(False)
        subtitle_box.show_status("Đang nhận diện giọng nói...")

    def on_stt_error(message: str) -> None:
        widget.set_listening_state(False)
        subtitle_box.show_status(message)
        subtitle_box.schedule_hide()

    def on_gemini_response(payload: dict) -> None:
        emotion = payload.get("emotion", "idle")
        jp_text = payload.get("japanese_text", "")
        vi_sub = payload.get("vietnamese_sub", "")
        widget.set_emotion(emotion)
        tts_player.speak(jp_text, vi_sub)

    def on_gemini_error(message: str) -> None:
        subtitle_box.show_status(f"Lỗi AI: {message}")
        subtitle_box.schedule_hide()

    widget.talk_toggle_requested.connect(stt_listener.toggle_listening)
    widget.quick_chat_requested.connect(send_user_message)

    stt_listener.listening_started.connect(on_stt_listening_started)
    stt_listener.listening_stopped.connect(on_stt_listening_stopped)
    stt_listener.text_transcribed.connect(send_user_message)
    stt_listener.stt_error.connect(on_stt_error)

    gemini_brain.response_ready.connect(on_gemini_response)
    gemini_brain.error_occurred.connect(on_gemini_error)

    # 4. Phase 2 quick TTS test trigger (Right-click menu or Ctrl+T)
    last_line_idx = -1

    def speak_random_sample_line() -> None:
        nonlocal last_line_idx
        candidates = [i for i in range(len(SAMPLE_TSUNDERE_LINES)) if i != last_line_idx]
        idx = random.choice(candidates) if candidates else 0
        last_line_idx = idx
        jp_text, vi_sub = SAMPLE_TSUNDERE_LINES[idx]
        tts_player.speak(jp_text, vi_sub)

    widget.test_speak_requested.connect(speak_random_sample_line)

    cleaned_up = False

    def shutdown_all() -> None:
        nonlocal cleaned_up
        if cleaned_up:
            return
        cleaned_up = True
        logger.info("Shutting down companion resources...")
        stt_listener.shutdown()
        gemini_brain.shutdown()
        tts_player.shutdown()
        subtitle_box.close()
        widget.cleanup()
        live2d.dispose()

    app.aboutToQuit.connect(shutdown_all)

    tts_player.start()
    gemini_brain.start()
    stt_listener.start()
    widget.show()

    exit_code = app.exec()
    shutdown_all()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
