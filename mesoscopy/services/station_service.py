"""The station in use, and what is monitored (no widgets)."""
from PyQt6.QtCore import QObject, pyqtSignal

from mesoscopy.core.experiment_parameters import instruments_of


class StationService(QObject):
    """Holds the QCoDeS station of the application and tells the tabs when it changes.

    ``stationChanged``: another station was loaded (or the first one).
    ``instrumentsChanged``: instruments were connected, disconnected or reloaded.
    ``monitoredChanged``: a parameter was added to or removed from the monitored ones (the list QCoDeS' own
    monitor uses, ``station._monitor_parameters``: the station also prunes it when an instrument is closed).
    """

    stationChanged = pyqtSignal()
    instrumentsChanged = pyqtSignal()
    monitoredChanged = pyqtSignal()
    instrumentsAlive = pyqtSignal(object)  # names of instruments that just answered a read (the monitor's): no need to ask get_idn

    def __init__(self):
        super().__init__()
        self.station = None
        self.station_file = None  # absolute path of the station file in use
        self.monitor_period = 5.0   # seconds between two readings of the Monitor tab (it sets it); a measurement follows it
        self.monitor_active = True  # the Monitor tab reads (its "Monitoring" box)

    def instruments(self):
        """The instruments of the station ({name: instrument})."""
        return instruments_of(self.station)

    def set_station(self, station, station_file, announce=True):
        """Use ``station``. With ``announce=False`` the signal is left for ``announce_station``, when the loading
        of the station is complete."""
        self.station, self.station_file = station, station_file
        if announce:
            self.stationChanged.emit()

    def announce_station(self):
        self.stationChanged.emit()

    def notify_instruments_changed(self):
        self.instrumentsChanged.emit()

    # ----- monitored parameters -----
    def monitored(self):
        return list(self.station._monitor_parameters) if self.station else []

    def is_monitored(self, parameter):
        return any(p is parameter for p in self.monitored())

    def add_monitored(self, parameter):
        """Monitor ``parameter`` (a no-op if it already is)."""
        if self.station is None or self.is_monitored(parameter):
            return False
        self.station._monitor_parameters.append(parameter)
        self.monitoredChanged.emit()
        return True

    def remove_monitored(self, parameter):
        if self.station is None:
            return
        self.station._monitor_parameters[:] = [p for p in self.station._monitor_parameters if p is not parameter]
        self.monitoredChanged.emit()
