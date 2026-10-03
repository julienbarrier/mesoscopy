"""The About dialog: what the program is, its version and what it is built with."""
import platform
import sys
from importlib import metadata

from PyQt6.QtCore import QT_VERSION_STR, Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

import mesoscopy

AUTHOR = "Julien Barrier"
LICENSE = "MIT License"
DOCS_URL = "https://mpilde.github.io/mesoscopy/"
REPOSITORY_URL = "https://github.com/mpilde/mesoscopy"
DESCRIPTION = "A graphical user interface to run experiments in mesoscopic physics. Based on QCoDeS."


def _version(package):
    try:
        return metadata.version(package)
    except metadata.PackageNotFoundError:
        return "not installed"


def built_with():
    """[(name, version)] of the program's main building blocks, as installed here."""
    return [("Python", platform.python_version()), ("Qt", QT_VERSION_STR), ("PyQt6", _version("PyQt6")),
            ("QCoDeS", _version("qcodes")), ("NumPy", _version("numpy")), ("Matplotlib", _version("matplotlib"))]


def about_html(settings_file=""):
    rows = "".join(f"<tr><td>{name}&nbsp;&nbsp;</td><td>{version}</td></tr>" for name, version in built_with())
    return (
        f"<h2>mesoscoPy</h2><p><b>Version {mesoscopy.__version__}</b></p><p>{DESCRIPTION}</p>"
        f"<p>&copy; 2026 {AUTHOR}. {LICENSE}.</p>"
        f'<p><a href="{DOCS_URL}">Documentation</a> &middot; <a href="{REPOSITORY_URL}">Source code</a></p>'
        f"<p><b>Built with</b></p><table>{rows}</table>"
        + (f"<p><small>Settings: {settings_file}</small></p>" if settings_file else "")
    )


class AboutDialog(QDialog):
    def __init__(self, parent=None, settings_file=""):
        super().__init__(parent)
        self.setWindowTitle("About mesoscoPy")
        layout = QVBoxLayout(self)
        self.label = QLabel(about_html(settings_file))
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setOpenExternalLinks(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self.setMinimumWidth(380)
