"""Entry point for the Miku AI Desktop Companion (Phase 1)."""

import logging
import sys

import live2d
from PyQt6.QtGui import QSurfaceFormat
from PyQt6.QtWidgets import QApplication

from src.ui.live2d_widget import Live2DWidget

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


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
    widget.show()

    exit_code = app.exec()
    widget.cleanup()
    live2d.dispose()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
