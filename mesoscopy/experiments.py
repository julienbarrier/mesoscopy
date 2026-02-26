import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../XW423/measurements')))

import qcodes
from qcodes import Parameter, ScaledParameter, validators as vals
from qcodes.dataset import dond, do1d, LinSweep
from qcodes.logger import start_command_history_logger, start_logger
import numpy as np
import time

from PyQt6.QtWidgets import QLineEdit, QSpinBox, QDoubleSpinBox

from functions.parameters import RampParameter
from functions.instruments import (
    configure_MFLI, configure_sr_lockin, configure_smu_2614B_gate,
    configure_MFLI_osc_master
)


class Experiment:
    name = "Base Experiment"
    parameters = []

    def __init__(self, station, db_file, exp_name, sample_name):
        self.station = station
        self.db_file = db_file
        self.exp_name = exp_name
        self.sample_name = sample_name
        qcodes.initialise_or_create_database_at(self.db_file)
        self.exp = qcodes.load_or_create_experiment(
            experiment_name=self.exp_name,
            sample_name=self.sample_name
        )

    def run(self, subscribers=[], **kwargs):
        raise NotImplementedError

    @staticmethod
    def get_widget(param_def):
        param_type = param_def.get('type', 'str')
        if param_type == 'int':
            return QSpinBox()
        elif param_type == 'float':
            return QDoubleSpinBox()
        else:
            return QLineEdit()


class TestContactsExperiment(Experiment):
    name = "Test Contacts"
    parameters = [
        {'name': 'v_drive', 'type': 'float', 'default': 0.001},
        {'name': 'start_freq', 'type': 'float', 'default': 48.0},
        {'name': 'stop_freq', 'type': 'float', 'default': 2000.0},
        {'name': 'n_points', 'type': 'int', 'default': 488},
        {'name': 'time_constant', 'type': 'float', 'default': 0.1},
        {'name': 'sweep_delay', 'type': 'float', 'default': 0.4},
        {'name': 'contact_pair', 'type': 'str', 'default': "16-1"},
    ]

    def run(self, v_drive, start_freq, stop_freq, n_points, time_constant, sweep_delay, contact_pair, subscribers=[]):
        lockin1 = self.station.load_mf6996()
        lockin2 = self.station.load_mf30779()

        # Setup lockins
        lockin1.sigouts[0].on(1)
        lockin1.sigouts[0].amplitudes[1].value(v_drive)
        lockin1.sigouts[0].offset(0)
        lockin1.triggers.out[0].source(1)

        lockin1.demods[0].enable(1)
        lockin1.demods[0].order(4)
        lockin1.demods[0].timeconstant(time_constant)
        lockin2.demods[0].adcselect(0)

        lockin2.extrefs[0].enable(1)
        lockin2.demods[1].adcselect(2)
        lockin2.demods[0].enable(1)
        lockin2.demods[0].order(4)
        lockin2.demods[0].timeconstant(time_constant)
        lockin2.demods[0].adcselect(1)

        lockin2.currins[0].autorange()
        lockin1.sigins[0].autorange()

        current = Parameter(
            name='current',
            label='Current',
            unit='A',
            get_cmd= lambda: abs(lockin2.demods[0].complex_sample())
        )

        Z_mag = Parameter(
            name='Z_magnitude',
            label='Impedance Magnitude',
            unit='Ohm',
            get_cmd= lambda: abs(lockin1.demods[0].complex_sample() / lockin2.demods[0].complex_sample())
        )

        Z_phase = Parameter(
            name='Z_phase',
            label='Impedance Phase',
            unit='rad',
            get_cmd= lambda: np.angle(lockin1.demods[0].complex_sample()) - np.angle(lockin2.demods[0].complex_sample())
        )
        
        sweeper = LinSweep(lockin1.oscs[0].freq, start_freq, stop_freq, n_points, sweep_delay)
        dond(
            sweeper,
            Z_mag, Z_phase, lockin1.demods[0].complex_sample, lockin2.demods[0].complex_sample, current,
            exp=self.exp,
            measurement_name=f'Contact {contact_pair} impedance measurement',
            show_progress=True,
            subscribers=subscribers
        )


class TestGatesExperiment(Experiment):
    name = "Test Gates"
    parameters = []

    def run(self, subscribers=[]):
        # Default values for removed parameters
        sweep_delay = 0.6
        sweep_rate = 0.15
        max_gate_voltage = 10.0
        n_points = 101
        
        SMU = self.station.load_SMU_2614B()

        for smu in [SMU.smua, SMU.smub]:
            configure_smu_2614B_gate(
                smu, mode='voltage', limiti=10e-9,
                limitv=max_gate_voltage,
                measurerange_i=1e-7, measurerange_v=20,
                sourcerange_v=20, nplc=5, output=False)

        top_gate_leakage = ScaledParameter(
            SMU.smua.curr, name='gate_leakage',
            gain = 1, unit = 'A')
        
        top_gate_voltage = RampParameter(
            'top_gate_voltage', SMU.smua.volt,
            rate=sweep_rate, delay=.01,
            vals=vals.Numbers(-max_gate_voltage, max_gate_voltage))

        measurement_name = f'test top gate range to {max_gate_voltage} V, \
            {sweep_rate}V/s, {n_points} points'

        do1d(
            top_gate_voltage,
            0, max_gate_voltage, n_points, sweep_delay,
            top_gate_leakage,
            measurement_name=measurement_name,
            exp=self.exp,
            show_progress=True,
            break_condition=lambda: top_gate_leakage.get_latest() > .06e-9,
            subscribers=subscribers
        )
        top_gate_voltage(0)


class GateGateMappingExperiment(Experiment):
    name = "Gate-Gate Mapping"
    parameters = [
        {'name': 'max_top_gate_voltage', 'type': 'float', 'default': 7.0},
        {'name': 'max_back_gate_voltage', 'type': 'float', 'default': 6.5},
        {'name': 'n_points', 'type': 'int', 'default': 201},
        {'name': 'v_drive', 'type': 'float', 'default': 0.2},
        {'name': 'frequency', 'type': 'float', 'default': 377.778},
        {'name': 'time_constant', 'type': 'float', 'default': 0.03},
        {'name': 'sweep_rate', 'type': 'float', 'default': 0.6},
        {'name': 'filter_order', 'type': 'int', 'default': 4},
        {'name': 'magnetic_field', 'type': 'float', 'default': 0.0},
    ]

    def run(self, max_top_gate_voltage, max_back_gate_voltage, n_points, v_drive,
            frequency, time_constant, sweep_rate, filter_order, magnetic_field, subscribers=[]):
        
        # Load instruments
        sr860_1 = self.station.load_sr860_1()
        sr860_2 = self.station.load_sr860_2()
        mf30779 = self.station.load_mf30779()
        mf6996 = self.station.load_mf6996()
        hf1450 = self.station.load_hf1450()
        SMU = self.station.load_SMU_2614B()
        cryostation = self.station.load_cryostation()
        
        # Instrument lists
        SR_LOCKINS = [sr860_1, sr860_2]
        MFLI_LOCKINS = [mf30779, mf6996, hf1450]
        DEMOD_INDICES = [0, 3]
        master_lockin = mf6996

        # SMU configuration
        SMU_CONFIG = {
            'mode': 'voltage', 'limiti': 10e-9, 'limitv': 15,
            'measurerange_i': 1e-7, 'measurerange_v': 20,
            'sourcerange_v': 20, 'nplc': 5, 'output': True
        }

        FILTER_SETTLING_TIME_MULTIPLIERS = {
            1: 3.0, 2: 4.7, 3: 6.3, 4: 7.8,
            5: 9.2, 6: 11, 7: 12, 8: 13
        }
        sweep_delay = time_constant * FILTER_SETTLING_TIME_MULTIPLIERS.get(filter_order, 7.8)

        # Configure instruments
        filter_slope = filter_order * 6 if filter_order < 6 else 24
        configure_MFLI_osc_master(master_lockin, osc_idx=0, frequency=frequency)
        for lockin in SR_LOCKINS:
            configure_sr_lockin(lockin, time_constant=time_constant, filter_slope=filter_slope)
        for lockin in MFLI_LOCKINS:
            for demod_idx in DEMOD_INDICES:
                configure_MFLI(
                    lockin, demod_idx=demod_idx, time_constant=time_constant, order=filter_order,
                    V_drive=v_drive if lockin == mf30779 else None,
                    adcselect=1 if lockin == mf6996 else 0
                )
        for smu in [SMU.smua, SMU.smub]:
            configure_smu_2614B_gate(smu, **SMU_CONFIG)
        
        time.sleep(1)

        # Set magnetic field
        cryostation.magnet_field(magnetic_field)
        time.sleep(abs(magnetic_field - cryostation.magnet_field()) / cryostation.magnet_ramp_rate() + 5)

        # Define parameters
        top_gate_leakage = ScaledParameter(SMU.smua.curr, name='top_gate_leakage', gain=1, unit='A')
        back_gate_leakage = ScaledParameter(SMU.smub.curr, name='back_gate_leakage', gain=1, unit='A')
        top_gate_voltage = RampParameter(
            'top_gate_voltage', SMU.smua.volt, rate=sweep_rate, delay=0.01,
            vals=vals.Numbers(-max_top_gate_voltage, max_top_gate_voltage)
        )
        back_gate_voltage = RampParameter(
            'back_gate_voltage', SMU.smub.volt, rate=sweep_rate, delay=0.01,
            vals=vals.Numbers(-max_back_gate_voltage, max_back_gate_voltage)
        )

        measured_params = {
            '5-2': sr860_1.complex_voltage, '14-16': sr860_2.complex_voltage,
            'curr(1)': mf6996.demods[0].complex_sample, '16-4': mf30779.demods[0].complex_sample,
            '10-13': hf1450.demods[0].complex_sample, '13-7': hf1450.demods[3].complex_sample,
            'voltage_topgate': SMU.smua.volt, 'voltage_backgate': SMU.smub.volt,
            'leakage_topgate': top_gate_leakage, 'leakage_backgate': back_gate_leakage
        }

        top_sweep = LinSweep(top_gate_voltage, -max_top_gate_voltage, max_top_gate_voltage, n_points, sweep_delay)
        back_sweep = LinSweep(back_gate_voltage, -max_back_gate_voltage, max_back_gate_voltage, n_points, sweep_delay)

        dond(
            top_sweep, back_sweep,
            *measured_params.values(),
            exp=self.exp,
            measurement_name=f'gate_gate_map_B{magnetic_field:.2f}T',
            show_progress=True,
            break_condition=lambda: any(abs(p.get_latest()) > 3e-10 for p in [top_gate_leakage, back_gate_leakage]),
            subscribers=subscribers
        )
        top_gate_voltage(0)
        back_gate_voltage(0)
