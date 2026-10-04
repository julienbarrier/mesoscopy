# Changelog

All notable changes to mesoscoPy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0).

## [Unreleased]

## [0.2.0] - 2026-10-04

First release with a graphical interface to run experiments with QCoDeS at its backend. The program is started with the `mesoscopy`command.

### Added

#### Main interface

- six tabs in the order of the work: Data, Instruments, Parameter explorer, Measurement, Queue, Monitor. A tab opens when what it needs is there; the tooltip of a greyed-out tab says what is missing
- Settings window (File, Settings...): default folders, auto-load of the last station, measurement options (breakout mode, threads, ramp to 0 after a failure, retries, memory of the live plot), alarm threshold and action, status bar sparklines, QCoDeS configuration values (kept by the program, the QCoDeS file is not modified), layout
- About window (Help, About mesoscoPy; in the application menu on macOS) with the version and the versions of the main libraries
- the window layout, the folders, the station and the entries of the Measurement tab, the queue and the alarms are restored at the next start
- one instrument gateway: measurements and actions on the instruments never overlap, and periodic reads of an instrument that is busy are skipped
- the version number is defined once, in `mesoscopy/__init__.py`
- minimal installation: PyQt6, NumPy, Matplotlib, SciPy, PyYAML and QCoDeS; optional extras `zurich` (MFLI and contrib drivers) and `visa`
- documentation (Sphinx), tab by tab, with screenshots made by `docs/make_screenshots.py`; a quick overview, an installation page and a page on building the station file
- GitHub workflow that makes the screenshots from the program, builds the documentation and publishes it to the `docs` branch
- test suite (pytest, pytest-qt) with a GitHub workflow: unit tests of the core, the live data of a run, and the application tab by tab on simulated instruments, run without a screen

#### Data tab

- database folder and sample name; the databases are named after the sample (`<sample>_<NN>.db`) and the next one of the series starts when a database exceeds 750 MB, or with the *Upgrade database* button
- QCoDeS logging to a chosen folder and a log viewer (file, instrument, level and text filters, full record with traceback)
- experiment explorer: the experiments of a database, their runs, status and points
- coloured tags (six colours) and notes on runs, saved in the database as run metadata
- comparison of the snapshots of two runs (instrument values, experiment parameters, setup)
- loading the snapshot of a run: reconnects the instruments, restores their settings and the experiment parameters, and fills the Measurement tab, after a review of every change

#### Instruments tab

- loading a station file (QCoDeS station YAML), then the instruments, with the errors shown; the instruments loaded last time are preselected
- loading another station keeps the instruments whose entry is identical
- a coloured health dot per instrument, from a background `get_idn` check (the readings of the Monitor count as a check)
- reconnecting, disconnecting, and updating the snapshot of instruments; the experiment parameters the program changed are ramped to 0 first
- instrument panel: command log, raw commands for VISA instruments (refused during a measurement), snapshot
- saving the state of an instrument to a file and restoring it from a file or from a run
- drivers: Oxford Instruments ITC503, Oxford Instruments Mercury iTC, Montana Instruments Cryostation (`mesoscopy.instrument.temperature`); simulated instruments for trying the program without hardware (`mesoscopy.instrument.dummy`)

#### Parameter explorer tab

- browsing the parameters of the instruments, reading and setting them with their validator, step and inter-delay; group parameters are shown together and read and set as one
- experiment parameters: a name, a gain, safe limits, a maximum ramp rate and an optional breakout condition; the aliases of the station file (`add_parameters`) become experiment parameters when their instrument is loaded
- derived parameters computed from other experiment parameters
- traces: array parameters of a driver with their axis, and plain arrays given an axis
- restoring the previous value of a parameter, ramping all the parameters to 0, monitoring a parameter and putting an alarm on it

#### Measurement tab

- sweeps of one to four axes: LinSweep, LogSweep, ArraySweep and TogetherSweep; snake sweeps, repetitions and sweeps back and forth
- measured parameters with aliases, and traces; scalars and traces can be measured together
- time estimate on the Run button; Check setup, a dry run that checks the limits, the alarms, the ramp rates, the free disk space and the duration (an error stops the run and the queue)
- pause, stop, stop and ramp to 0, ramp to 0 when finished, stop on breakout conditions
- instruments that do not answer are retried a few times before a measurement fails; a failed measurement ramps the parameters it changed to 0
- advanced settings: actions before and after the measurement and after each point of an axis, with waiting helpers (`wait`, `wait_until`, `wait_below`, `wait_above`, `wait_stable`) that end on Stop and time out, and a menu of one-line pre-defined actions; reading back after setting; additional setpoints; several datasets; write period, threads, in-memory cache and log message; automatic export of the data and saving of the plots after each run (QCoDeS' export and `plot_dataset`)
- live plot fed by QCoDeS while the data is written, not read back from the database; maps and traces are one curve per sweep or trace with earlier curves faded; complex values as real and imaginary parts; colour-blind friendly colours; derivative, axis factors; nothing is redrawn while the tab is hidden or nothing changed
- filling Start and Stop from the plot: click, drag a range, the maximum or minimum of the curve or of its derivative, with marker lines; setting a safe limit of the plotted parameter from the plot
- tags and notes of a finished run from the right-click menu of the plot; the Data tab follows
- compact storage of finished maps (unique axis values and a 32-bit value matrix) and a limit, set in the Settings, on the memory used by the earlier runs

#### Queue tab

- measurements (recipes) run one after the other; reorder, duplicate, edit, run only one, skip, stop
- steps: wait for a time, wait until a parameter is below, above or stable, set a parameter, repeat a measurement until a condition holds
- series of a measurement over the values of a parameter
- the queue is saved at every change and restored after a crash or a power cut, to be started again by hand
- saving and loading a queue file; export as a Python script that runs the queue with plain QCoDeS `dond` calls

#### Monitor tab

- periodic reading of chosen parameters, the instruments that do not depend on each other read at the same time
- time traces of a chosen duration, sparklines in the status bar
- alarms on the limits of a parameter, with the actions message, pause, stop, and stop and ramp to 0
- a log file of the monitored values in the logs folder (`monitor_<database>_<date>.log`, one column per parameter), started again when the database or the monitored parameters change

## [0.1.1] - 2021-12-09

### Changed
- bug fixes

## [0.1.0] - 2021-11-17

### Added

- sweep functions include time estimate

## [0.1-alpha] - 2021-09-09

### Added

- fast, 1D and 2D sweep functions
- calculate sweep time
- generate measurement arrays
- load station and add instruments to station
- parameters to make dual gate sweeps
- loading and plotting functions
