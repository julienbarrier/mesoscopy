"""Station loading from YAML config (no Qt)."""
import gc
import time
import yaml
import qcodes
from qcodes.instrument import Instrument

from mesoscopy.core.logging_setup import ensure_logging
from mesoscopy.instrument.station_config import instrument_names, read_station_config, root_parameter_names


def get_instruments_from_yaml(config_file):
    """Names of the instruments of a station file (parameters declared at its root are not included)."""
    return instrument_names(read_station_config(config_file))


def load_station_from_config(config_path):
    """
    Load a qcodes Station from a YAML config file.
    Makes sure the QCoDeS logger runs (a logger started in a chosen folder is kept) and returns the station.
    """
    ensure_logging()
    return qcodes.station.Station(config_file=config_path)


def _wait_until_released(session, serial, timeout=5.0):
    """Wait for the zhinst data server to drop the device (disconnect_device returns immediately)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        connected = [d.lower() for d in session.devices.connected()]
        if serial.lower() not in connected:
            return
        time.sleep(0.1)


def disconnect_instrument(station, name):
    """
    Fully disconnect an instrument: remove it from the station, close it and free its name.

    Unlike ``instrument.close()`` alone, this still releases the instrument name in the qcodes
    registry when a driver's ``close()`` raises (otherwise reloading fails with
    "Another instrument has the name"), disconnects Zurich Instruments devices from the data
    server, and closes the zhinst session once no other instrument uses it.

    Returns (found, errors): ``found`` is False if no such instrument exists, ``errors`` is a
    list of messages for steps that failed (the instrument is released regardless).
    """
    instrument = station.components.get(name) or Instrument._all_instruments.get(name)
    if instrument is None:
        return False, []

    errors = []
    session = getattr(instrument, "session", None)  # zhinst: shared data-server session
    serial = getattr(instrument, "serial", None)

    # a) remove from station (and from its monitor list)
    station._monitor_parameters = [
        p for p in station._monitor_parameters if p.root_instrument is not instrument
    ]
    station.components.pop(name, None)

    # b) release the device on the data server so it is no longer "in use"
    if session is not None and serial:
        try:
            session.disconnect_device(serial)
            _wait_until_released(session, serial)
        except Exception as e:
            errors.append(f"{name}: disconnect device: {e}")

    # c) close the instrument; d) drop its name even if close() failed half-way
    try:
        instrument.close()
    except Exception as e:
        errors.append(f"{name}: close: {e}")
    finally:
        Instrument.remove_instance(instrument)

    # e) close the zhinst session if nothing else is using it
    if session is not None:
        still_used = any(
            getattr(other, "session", None) is session
            for other in Instrument._all_instruments.values()
        )
        if not still_used:
            try:
                session.close()
            except Exception as e:
                errors.append(f"{name}: close session: {e}")
            finally:
                Instrument.remove_instance(session)

    del instrument, session
    gc.collect()
    return True, errors
