"""
Driver extensions for the Source-Measurement Units (Keithley 2600 and 2400 family) and the SIM928.

They add a ``max_rate`` parameter (maximum sweeping rate). How an SMU is set up (mode, compliance
limits, ranges, NPLC, max rate) is not done in Python any more: it is described by the presets and
aliases of the station file. See _test_.station.yaml and docs/station_templates.yaml.
"""

from typing import Any, List
from qcodes.instrument import Instrument
from qcodes.parameters import Parameter

from qcodes.instrument_drivers.Keithley._Keithley_2600 import (
    Keithley2600Channel as KeithleyChannel, Keithley2600 as Keithley_2600)
from  qcodes.instrument_drivers.Keithley.Keithley_2450 import Keithley2450, Keithley2450Source as Source2450
from qcodes_contrib_drivers.drivers.StanfordResearchSystems.SIM928 import SIM928



# Classes to add a "max_rate" parameter to the Keithley channels

class Keithley2600Channel(KeithleyChannel):
    def __init__(self, parent: Instrument, name: str, channel: str) -> None:
        super().__init__(parent, name, channel)

        self.max_rate = Parameter(
            'max_rate',
            unit='V/s or A/s',
            get_cmd=None,
            set_cmd=None,
            label='maximum sweeping rate',
            instrument=self,
            initial_value=0
        )


class Keithley2600(Keithley_2600):
    def __init__(self, name: str, address: str, **kwargs: Any) -> None:
        super().__init__(name, address, **kwargs)

        self.channels: List[Keithley2600Channel] = []
        for ch in ['a', 'b']:
            ch_name = f'smu{ch}'
            channel = Keithley2600Channel(self, ch_name, ch_name)
            self.submodules[ch_name] = (channel)
            self.channels.append(channel)

class Keithley2400Source(Source2450):
    def __init__(self, parent: "Keithley2450", name:str, proper_function:str, **kwargs: Any) -> None:
        super().__init__(parent, name, proper_function, **kwargs)

        #self.function = self.parent.source_function
        #
        #self.add_parameter()
    
class Keithley2400(Keithley2450):
    def __init__(self, name: str, address: str, **kwargs: Any) -> None:
        super().__init__(name, address, **kwargs)

        self.add_parameter(
            'max_rate',
            unit='V/s or A/s',
            get_cmd = None,
            set_cmd = None,
            label='maximum sweeping rate',
            initial_value=0
        )
    
class SRS_SIM928(SIM928):
    def __init__(self,
                 name: str,
                 address: str,
                 slot_names=None,
                 **kwargs) -> None:
        super().__init__(name, address, slot_names, **kwargs)

        # TODO: rewrite SIM928 as an InstrumetChannel of SIM900, so that the
        # max_rate parameter can be applied independently on different channels.

        self.max_rate = Parameter(
            'max_rate',
            unit='V/s',
            get_cmd=None,
            set_cmd=None,
            label='maximum sweeping rate',
            instrument=self,
            initial_value=0
        )
