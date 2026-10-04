# TODO

Open items only. What is done is in [CHANGELOG.md](CHANGELOG.md). Also see `docs/program/roadmap.rst` (*Limitations and roadmap*)

## Data tab
- [ ] Explorer: filter and sort the runs; export a selected run (`dataset.export("csv" | "netcdf")`); copy runs into another database (`extract_runs_into_db`).
- [ ] Plot a finished run with the same plot panel as the live one.
- [ ] More run metadata: operator and sample identifier next to the tag and the notes (`dataset.add_metadata`).

## Instruments tab
- [ ] "Load all instruments" and "Reload station file" buttons; a station-file validator with inline errors (QCoDeS ships the schema). All with default re-loading of all previous instruments upon restart.
- [ ] Auto-discovery: VISA resources (`pyvisa` `ResourceManager.list_resources()`) and LabOne devices (`ziDiscovery`), with "Add to station", directly updating the YAML file.
- [ ] Connection test before loading (ping, port, "device in use by ...").
- [ ] Instrument roles ("master lock-in", "gate source"), so that recipes and defaults refer to a role and not to a name.

## Parameter explorer tab
- [ ] `InstrumentModule` sections in the table (`GroupParameter` is done).
- [ ] Parameter features not exposed: `post_delay`, editing validators, `get_parser` / `set_parser`; test and support `MultiParameter` and `ArrayParameter` as measured parameters.
- [ ] Export parameters back to the station YAML file

## Measurement tab
- [ ] Colour-map view of a map in the live plot, with a slice selector, rows added as they arrive and following colour limits (the live data is already available from `dataset.cache`); line cuts, normalisation, fits.
- [ ] Run-to-run feedback, what is left: a fitted peak instead of the raw maximum, centre and span, a click on a map for both axes, undo of the last filled value, an automatic "set to the extremum of the last run" queue step.
- [ ] Time estimate learnt from past runs (measured time per point per recipe, including the first move, the instrument read time and the overheads), used for the run and the queue total.
- [ ] Sweeps as a function of time; adaptive sweeps.
- [ ] More of QCoDeS' `Measurement` API: `register_custom_parameter`, callbacks, `add_after_run`.
- [ ] MFLI: use the device's streaming / DAQ instead of one `get()` per point (see `MFLI_DAQ_PLAN.md`).
- [ ] Review the defaults of `write_period` and `in_memory_cache`; measure the per-point overhead.

## Queue tab
- [ ] Resume a measurement in the middle of a sweep after an interruption.
- [ ] Notifications (e-mail, Telegram, push) when a measurement or the queue finishes and when an alarm goes off.

## Monitor tab
- [ ] The QCoDeS Monitor web page, to follow the instrument status remotely.
- [ ] Decimate the history of a parameter on storage (it keeps 24 h of readings as they are, up to 100 000 points).

## Performance and refactoring
- [ ] Faster live plot for very large maps and traces (pyqtgraph, or Matplotlib with blitting and downsampling to the pixel width).
- [ ] One shared plot component for the Measurement tab, the Monitor and the Data tab viewer.
- [ ] Other QCoDeS functions not used yet: `load_by_guid`, `to_pandas_dataframe`, `Station.load_all_instruments`, editing more of `qcodes.config` than the options of the Settings window.
