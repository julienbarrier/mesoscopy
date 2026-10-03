"""
Driver extensions for lock-in amplifiers.

How a lock-in is set up (frequency, time constant, filter, master/slave wiring, ...) is not done in
Python any more: it is described by the presets and aliases of the station file. See the comments of
_test_.station.yaml and the templates in docs/station_templates.yaml.
"""

from typing import Optional, Any
from qcodes.parameters import Parameter
from qcodes.parameters import ParamRawDataType
from qcodes.validators import ComplexNumbers

import zhinst.qcodes


class ComplexSampleParameter(Parameter):
    def __init__(
        self, *args: Any, dict_parameter: Optional[Parameter] = None, **kwargs: Any
    ):
        super().__init__(*args, **kwargs)
        if dict_parameter is None:
            raise TypeError("ComplexCampleParameter requires a dict_parameter")
        self._dict_parameter = dict_parameter

    def get_raw(self) -> ParamRawDataType:
        values_dict = self._dict_parameter.get()
        return complex(values_dict["x"], values_dict["y"])


class MFLIWithComplexSample(zhinst.qcodes.MFLI):
    """
    This wrapper adds back a "complex sample" parameter to the demodulators such that
    we can use them in the way that we have done with "sample" parameter
    in version 0.2 of ZHINST-qcodes
    written by jenshnielsen: https://github.com/zhinst/zhinst-qcodes/issues/41
    """

    def __init__(self, name: str, serial: str, **kwargs: Any):
        super().__init__(
            name=name, serial=serial, **kwargs
        )
        for demod in self.demods:
            demod.add_parameter(
                "complex_sample",
                label="Vrms",
                vals=ComplexNumbers(),
                parameter_class=ComplexSampleParameter,
                dict_parameter=demod.sample,
                snapshot_value=False,
            )
