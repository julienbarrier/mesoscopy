"""Services: the shared, widget-free state and behaviour of the application.

The main window builds one ``Services`` and gives it to every tab. A tab reads what it needs from it and subscribes
to its signals (``registry.parametersChanged``, ``station.instrumentsChanged``, ``run.runStateChanged`` ...); tabs do
not hold each other, nor the main window.
"""
from dataclasses import dataclass

from mesoscopy.core.app_settings import AppSettings
from mesoscopy.core.experiment_parameters import ParameterRegistry
from mesoscopy.core.gateway import InstrumentGateway
from mesoscopy.core.restore_history import RestoreHistory
from mesoscopy.services.alarms import AlarmService
from mesoscopy.services.data_service import DataService
from mesoscopy.services.experiment_names import ExperimentNamesService
from mesoscopy.services.ramp import RampService
from mesoscopy.services.measuring import Measuring
from mesoscopy.services.run_controller import RunController
from mesoscopy.services.run_queue import RunQueue
from mesoscopy.services.station_service import StationService
from mesoscopy.services.status import StatusMessages


@dataclass
class Services:
    settings: AppSettings
    gateway: InstrumentGateway
    status: StatusMessages
    station: StationService
    registry: ParameterRegistry
    data: DataService
    restore: RestoreHistory   # the values to put back, from the Parameter explorer
    ramp: RampService = None   # ``ramp`` and ``run`` need the others: set by ``create_services``
    run: RunController = None
    experiments: ExperimentNamesService = None
    queue: RunQueue = None     # the recipes run one after another
    measuring: Measuring = None  # a measurement is going on: the controls that are unavailable meanwhile
    alarms: AlarmService = None   # the alarms on parameters


def create_services(settings=None, parent=None):
    """The services of a running application. ``settings`` defaults to the user's remembered settings."""
    services = Services(
        settings=settings or AppSettings(), gateway=InstrumentGateway(parent), status=StatusMessages(),
        station=StationService(), registry=ParameterRegistry(), data=DataService(), restore=RestoreHistory(),
    )
    services.station.stationChanged.connect(services.restore.clear)  # the values of another station mean nothing here
    services.ramp = RampService(services)
    services.run = RunController(services)
    services.experiments = ExperimentNamesService(services)
    services.queue = RunQueue(services)
    services.measuring = Measuring(services)
    services.alarms = AlarmService(services)
    services.station.instrumentsChanged.connect(services.alarms.sync)  # an alarm follows its parameter
    services.registry.parametersChanged.connect(services.alarms.sync)
    return services
