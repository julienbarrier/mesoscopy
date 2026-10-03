"""The QCoDeS configuration values the settings dialog offers (no widgets).

They are read from and written to ``qcodes.config`` while the application runs; the application remembers the ones
the user changed and sets them again at each start. The user's ``qcodesrc.json`` is not modified.
"""
import json
import os
from dataclasses import dataclass

import qcodes as qc
import qcodes.logger.logger as qcodes_logger

LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
NONE_CHOICE = "(none)"


@dataclass(frozen=True)
class Option:
    key: str                  # "section.name" in qcodes.config
    label: str
    kind: str                 # "bool", "choice", "text", "number"
    help: str = ""
    choices: tuple = ()       # kind "choice"; NONE_CHOICE stands for None


OPTIONS = (
    Option("logger.console_level", "Console log level", "choice", "Lowest level of the messages printed to the console.",
           tuple(LEVELS)),
    Option("logger.file_level", "Log file level", "choice",
           "Lowest level written to the log file. DEBUG also records every command sent to the instruments.",
           tuple(LEVELS)),
    Option("dataset.write_in_background", "Write data in the background", "bool",
           "Write the measured data to the database from a separate thread."),
    Option("dataset.write_period", "Write period (s)", "number", "How often dond saves the data to the database."),
    Option("dataset.in_memory_cache", "In-memory cache", "bool", "Keep the data of a run in memory for fast plotting."),
    Option("dataset.export_automatic", "Export every run automatically", "bool",
           "Write each finished run to a file next to the database."),
    Option("dataset.export_type", "Export format", "choice", "Format of the automatic export.",
           (NONE_CHOICE, "csv", "netcdf")),
    Option("dataset.export_prefix", "Export file prefix", "text", "Start of the name of the exported files."),
    Option("dataset.export_path", "Export folder", "text",
           "Where exported files go. {db_location} stands for the folder of the database."),
    Option("station.enable_forced_reconnect", "Allow forced reconnect", "bool",
           "When an instrument with the same name exists, close it and connect again instead of failing."),
)


def _section(key):
    section, name = key.split(".", 1)
    return section, name


def get_value(key):
    section, name = _section(key)
    return qc.config[section][name]


def default_value(key):
    section, name = _section(key)
    return qc.config.defaults[section][name]


def set_value(key, value):
    """Set a configuration value now. A logger level also reaches the handlers that run already."""
    section, name = _section(key)
    qc.config[section][name] = value
    if key in ("logger.console_level", "logger.file_level"):
        apply_logger_levels()


def apply_logger_levels():
    """Give the running QCoDeS log handlers the levels of the configuration."""
    for handler, option in ((qcodes_logger.console_handler, "console_level"), (qcodes_logger.file_handler, "file_level")):
        if handler is not None:
            handler.setLevel(qc.config.logger[option])


def apply_overrides(overrides):
    """Set the values the user chose in a previous session. Returns the keys that could not be set."""
    failed = []
    known = {option.key for option in OPTIONS}
    for key, value in overrides.items():
        if key not in known:
            continue
        try:
            set_value(key, value)
        except Exception:
            failed.append(key)
    return failed


USE_THREADS_KEY = "dataset.use_threads"


def user_file_value(key):
    """(True, value) when a QCoDeS configuration file of the user (home folder, QCODES_CONFIG, current folder) sets
    ``key``, else (False, None). The one read last wins, as in QCoDeS (home, then environment, then current folder)."""
    section, name = _section(key)
    found, value = False, None
    for path in (qc.config.home_file_name, qc.config.env_file_name, qc.config.cwd_file_name):
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path) as f:
                data = json.load(f)
            value, found = data[section][name], True
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return found, value


def default_use_threads():
    """Whether dond reads the measured parameters in threads when the user has not chosen: on, unless the user's
    QCoDeS configuration file sets ``dataset.use_threads``."""
    found, value = user_file_value(USE_THREADS_KEY)
    return bool(value) if found else True


def effective_use_threads(settings):
    """dond's ``use_threads``: what the user chose in the Settings, else the default."""
    chosen = settings.use_threads
    return default_use_threads() if chosen is None else chosen
