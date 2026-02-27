"""
mesoscoPy - Experiment Runner
Main entry point for the application.
"""

import sys
from PyQt6.QtWidgets import QApplication

from mesoscopy.ui.main_window import MainWindow
from mesoscopy.core.constants import DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT


def main():
    """Launch the application."""
    app = QApplication(sys.argv)
    app.setStyle("Universal")
    
    window = MainWindow()
    window.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
