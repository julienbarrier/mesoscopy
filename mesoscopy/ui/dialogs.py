"""File and folder selection dialogs."""
import os
from PyQt6.QtWidgets import QFileDialog


class FileDialogs:
    """File and folder selection dialogs."""

    def __init__(self, parent_window):
        self.parent_window = parent_window

    def select_folder(self, name="Station"):
        """Open folder selection dialog."""
        folder = QFileDialog.getExistingDirectory(
            self.parent_window, 
            f"Select {name} Folder", 
            "./"
        )
        if folder:
            if name == "Station":
                self.parent_window.station_folder_display.setText(folder)
            elif name == "Database":
                self.parent_window.db_folder_display.setText(folder)
            elif name == "Logs":
                self.parent_window.logs_folder_display.setText(folder)
        return folder

    def select_db_folder(self):
        """Select database folder."""
        folder = self.select_folder(name="Database")
        # Populate database file dropdown when folder is selected
        if folder:
            self.parent_window.populate_db_files()
        return folder

    def select_station_folder(self):
        """Select station folder."""
        folder = self.select_folder(name="Station")
        # Populate station file dropdown when folder is selected
        if folder:
            self.parent_window.populate_station_files()
        return folder
    
    def select_logs_folder(self):
        """Select logs folder."""
        folder = self.select_folder(name="Logs")
        return folder
