"""Dummy instruments for testing mesoscopy without hardware (see _test_.station.yaml)."""
import numpy as np
from qcodes.instrument import Instrument
from qcodes.instrument_drivers.mock_instruments import GeneratedSetPoints
from qcodes.parameters import ParameterWithSetpoints
from qcodes.validators import Arrays, Ints, Numbers


class DummyMeter(Instrument):
    """Meter whose readings depend on the gates of another instrument, so that sweeps show a signal.

    ``source`` is the *name* of the instrument whose gates ``ch1`` and ``ch2`` are read at every
    reading (a name, because a station YAML file cannot pass instrument objects).
        v1 = 5 * exp(-ch1**2) + noise     (a peak at ch1 = 0)
        v2 = sin(ch2) + noise
    """

    def __init__(self, name, source, noise=0.01, **kwargs):
        super().__init__(name, **kwargs)
        self._source_name = source
        self._noise = noise
        for parameter, reading in (("v1", self._read_v1), ("v2", self._read_v2)):
            self.add_parameter(parameter, unit="V", label=f"Dummy {parameter}", get_cmd=reading)

    def get_idn(self):
        """Fixed identity: there is no device to ask '*IDN?'."""
        return {"vendor": "mesoscopy", "model": "DummyMeter", "serial": "dummy", "firmware": "1.0"}

    def _gate(self, gate):
        return Instrument.find_instrument(self._source_name).parameters[gate]()

    def _noise_value(self):
        return float(np.random.normal(0, self._noise))

    def _read_v1(self):
        return 5 * np.exp(-self._gate("ch1") ** 2) + self._noise_value()

    def _read_v2(self):
        return np.sin(self._gate("ch2")) + self._noise_value()


class DummySpectrum(Instrument):
    """A spectrum analyser: a peak whose frequency follows the gate ``ch1`` of another instrument.

    It gives the same spectrum in two ways, to try both kinds of trace:
        spectrum   an array parameter WITHOUT axis (to be measured as a user-defined trace)
        trace      a ParameterWithSetpoints over ``frequency`` (measured as it is, like a real driver's)
    ``source`` is the *name* of the instrument whose gate ``ch1`` moves the peak (as for DummyMeter).
    """

    def __init__(self, name, source, points=64, noise=0.02, **kwargs):
        super().__init__(name, **kwargs)
        self._source_name = source
        self._noise = noise
        self.add_parameter("n_points", initial_value=int(points), get_cmd=None, set_cmd=None, vals=Ints(2, 100_000))
        self.add_parameter("f_start", initial_value=0.0, unit="Hz", get_cmd=None, set_cmd=None, vals=Numbers())
        self.add_parameter("f_stop", initial_value=1000.0, unit="Hz", get_cmd=None, set_cmd=None, vals=Numbers())
        self.add_parameter(
            "frequency", parameter_class=GeneratedSetPoints, startparam=self.f_start, stopparam=self.f_stop,
            numpointsparam=self.n_points, unit="Hz", label="Frequency", vals=Arrays(shape=(self.n_points.get_latest,)),
        )
        self.add_parameter("spectrum", unit="V", label="Spectrum", get_cmd=self._spectrum,
                           vals=Arrays(shape=(self.n_points.get_latest,)))
        self.add_parameter(
            "trace", parameter_class=ParameterWithSetpoints, setpoints=(self.frequency,), unit="V", label="Trace",
            get_cmd=self._spectrum, vals=Arrays(shape=(self.n_points.get_latest,)),
        )

    def get_idn(self):
        return {"vendor": "mesoscopy", "model": "DummySpectrum", "serial": "dummy", "firmware": "1.0"}

    def _spectrum(self):
        axis = np.linspace(self.f_start(), self.f_stop(), self.n_points())
        gate = Instrument.find_instrument(self._source_name).parameters["ch1"]()
        center = 300 + 400 * np.clip(gate, 0, 1)
        return np.exp(-((axis - center) / 40.0) ** 2) + np.random.normal(0, self._noise, axis.shape)
