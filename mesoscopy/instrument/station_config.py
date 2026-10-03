"""Read what a station file declares (no Qt): instruments, root parameters and custom parameters."""
import importlib
from functools import lru_cache

import yaml
from qcodes.parameters import ParameterBase


def read_station_config(config_file):
    """The ``instruments`` section of a station file as a dict ({} if the file cannot be read)."""
    try:
        with open(config_file, "r") as f:
            config = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        print(f"Error reading the station file: {e}")
        return {}
    instruments = (config or {}).get("instruments") or {}
    return instruments if isinstance(instruments, dict) else {}


@lru_cache(maxsize=None)
def is_parameter_type(type_path):
    """True if a station entry's ``type`` is a QCoDeS parameter class (not an instrument class).

    The class is imported to find out; a type that cannot be imported counts as an instrument, so
    that the error shows up when the instrument is loaded.
    """
    try:
        module_name, _, class_name = type_path.rpartition(".")
        return issubclass(getattr(importlib.import_module(module_name), class_name), ParameterBase)
    except Exception:
        return False


def root_parameter_names(instruments_config):
    """Entries of the station file that are parameters living at the root of the station."""
    return [name for name, entry in instruments_config.items()
            if isinstance(entry, dict) and is_parameter_type(entry.get("type", ""))]


def instrument_names(instruments_config):
    """Entries of the station file that are real instruments."""
    parameters = set(root_parameter_names(instruments_config))
    return [name for name in instruments_config if name not in parameters]


def declared_parameters(instrument_entry):
    """Custom parameters an instrument entry declares under ``add_parameters``: {name: options}."""
    declared = (instrument_entry or {}).get("add_parameters") or {}
    return declared if isinstance(declared, dict) else {}
