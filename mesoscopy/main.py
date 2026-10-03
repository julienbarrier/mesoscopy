"""
mesoscoPy - Experiment Runner
Main entry point for the application.
"""

import sys
from PyQt6.QtWidgets import QApplication

from mesoscopy.ui.error_handling import install_exception_hook
from mesoscopy.ui.main_window import MainWindow
from mesoscopy.core.constants import DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT


def main():
    """Launch the application."""
    app = QApplication(sys.argv)
    app.setStyle("Universal")
    
    window = MainWindow()
    install_exception_hook(window)  # an unexpected error is reported, it must not abort the application
    window.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
