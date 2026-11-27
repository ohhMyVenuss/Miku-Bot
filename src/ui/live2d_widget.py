"""Transparent, frameless, draggable QOpenGLWidget for rendering Live2D models."""

import logging
from typing import Optional

import live2d
from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QAction, QContextMenuEvent, QGuiApplication, QMouseEvent
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QApplication, QMenu

from src import config

logger = logging.getLogger(__name__)


class Live2DWidget(QOpenGLWidget):
    """Frameless, transparent, always-on-top desktop widget rendering a Live2D character."""

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
        self.setWindowTitle("Miku AI Desktop Companion")

        self.model: Optional[live2d.Model] = None
        self._gl_initialized = False
        self._drag_offset: Optional[QPoint] = None

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
        """Clear transparent buffer and draw the current Live2D frame."""
        live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)
        if self.model is None:
            return
        self.model.Update()
        self.model.Draw()

    # ------------------------------------------------------------------
    # Mouse Dragging & Context Menu
    # ------------------------------------------------------------------
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

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)

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
        """Stop render loop and release OpenGL/Live2D resources."""
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
