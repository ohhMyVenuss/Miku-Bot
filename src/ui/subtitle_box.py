"""Floating translucent speech bubble widget for displaying status and subtitles."""

from PyQt6.QtCore import QTimer, Qt, pyqtSlot
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from src import config


class SubtitleBox(QWidget):
    """Frameless, always-on-top dark translucent speech bubble anchored to the avatar."""

    def __init__(self, anchor_widget: QWidget | None = None, parent=None) -> None:
        super().__init__(parent)
        self._anchor_widget = anchor_widget

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(340)
        self._label.setMinimumWidth(140)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_style(is_status=False)
        layout.addWidget(self._label)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        self.hide()

    def _apply_style(self, is_status: bool) -> None:
        text_color = "#93C5FD" if is_status else "#F8FAFC"
        border_color = (
            "rgba(147, 197, 253, 95)" if is_status else "rgba(255, 255, 255, 48)"
        )
        self._label.setStyleSheet(
            f"""
            QLabel {{
                background-color: rgba(18, 20, 30, 215);
                color: {text_color};
                border: 1px solid {border_color};
                border-radius: 14px;
                padding: 10px 14px;
                font-family: "Segoe UI", sans-serif;
                font-size: 13px;
                font-weight: 500;
            }}
            """
        )

    def set_anchor(self, anchor_widget: QWidget) -> None:
        """Bind an anchor widget whose position this bubble follows."""
        self._anchor_widget = anchor_widget
        if self.isVisible():
            self.reposition()

    @pyqtSlot(str)
    def show_status(self, text: str) -> None:
        """Display a transient processing status (e.g., listening/thinking)."""
        clean_text = text.strip()
        if not clean_text:
            return
        self._hide_timer.stop()
        self._apply_style(is_status=True)
        self._label.setText(clean_text)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()

    @pyqtSlot(str)
    def show_subtitle(self, text: str) -> None:
        """Display subtitle text immediately and cancel any pending auto-hide."""
        clean_text = text.strip()
        if not clean_text:
            return
        self._hide_timer.stop()
        self._apply_style(is_status=False)
        self._label.setText(clean_text)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()

    @pyqtSlot()
    def schedule_hide(self) -> None:
        """Schedule hiding the subtitle bubble 5 seconds after speech ends."""
        self._hide_timer.start(config.SUBTITLE_HIDE_DELAY_MS)

    @pyqtSlot()
    def reposition(self) -> None:
        """Place the bubble near the anchor widget while staying inside screen bounds."""
        if self._anchor_widget is None:
            return

        anchor_geo = self._anchor_widget.frameGeometry()
        bubble_size = self.sizeHint()
        w = bubble_size.width()
        h = bubble_size.height()

        x = anchor_geo.center().x() - (w // 2)
        y = anchor_geo.top() - h + 24

        screen = (
            QGuiApplication.screenAt(anchor_geo.center())
            or QGuiApplication.primaryScreen()
        )
        if screen is not None:
            avail = screen.availableGeometry()
            if y < avail.top() + 8:
                y = anchor_geo.top() + 10
            x = max(avail.left() + 8, min(x, avail.right() - w - 8))
            y = max(avail.top() + 8, min(y, avail.bottom() - h - 8))

        self.move(x, y)
