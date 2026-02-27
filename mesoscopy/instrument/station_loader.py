"""Station loading from YAML config (no Qt)."""
import os
import yaml
import qcodes
from qcodes.logger import start_command_history_logger, start_logger


def get_instruments_from_yaml(config_file):
    """Extract all instrument names from the 'instruments:' section of the station YAML file."""
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        if config and 'instruments' in config:
            return list(config['instruments'].keys())
        return []
    except Exception as e:
        print(f"Error reading instruments from YAML: {e}")
        return []


def load_station_from_config(config_path):
    """
    Load a qcodes Station from a YAML config file.
    Starts command history logger and returns the station.
    """
    start_command_history_logger('../logs/')
    start_logger()
    return qcodes.Station(config_file=config_path)
