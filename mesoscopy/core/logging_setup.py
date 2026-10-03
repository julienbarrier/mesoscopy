"""QCoDeS file logging in a folder chosen by the user (no Qt)."""
import os

import qcodes.logger.logger as qcodes_logger


def start_file_logging(folder):
    """Start the QCoDeS logger (console and file) with the log file in ``folder``. Returns the log file path.

    The file is the one QCoDeS would write in ``~/.qcodes/logs``, named ``<yymmdd>-<pid>-qcodes.log`` and
    rotated at midnight, with the same format. Calling it again (with another folder) moves the logging there.
    """
    path = os.path.join(folder, qcodes_logger.generate_log_file_name())
    original = qcodes_logger.get_log_file_name
    qcodes_logger.get_log_file_name = lambda: path  # start_logger takes the file name from this function
    try:
        qcodes_logger.start_logger()
    finally:
        qcodes_logger.get_log_file_name = original
    return path


def ensure_logging():
    """Make sure the QCoDeS logger runs, without moving it if it was started already (e.g. in a chosen folder)."""
    if qcodes_logger.file_handler is None:
        qcodes_logger.start_logger()
