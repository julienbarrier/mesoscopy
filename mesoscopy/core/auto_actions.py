"""Per-run auto-actions, with QCoDeS only: export the data of a run and save its plots.

* Export uses QCoDeS' own automatic export: ``qcodes.config.dataset.export_automatic``, ``export_type`` and
  ``export_path`` (the files are named by ``export_prefix`` and ``export_name_elements``). ``export_settings`` sets them
  for the duration of one run and puts the previous values back, so the QCoDeS configuration file is not touched.
* Plots are made by ``qcodes.dataset.plot_dataset`` on a figure of their own (no pyplot, so it is safe in the measurement
  thread) and saved next to the exported data.

This module needs nothing but QCoDeS and matplotlib: "Export as Python" copies it into the script.
"""
import contextlib
import re
from pathlib import Path

import qcodes
from matplotlib.figure import Figure
from qcodes.dataset import plot_dataset
from qcodes.dataset.export_config import get_data_export_path

EXPORT_TYPES = ("csv", "netcdf")
PLOT_FORMATS = ("png", "pdf", "svg")


@contextlib.contextmanager
def export_settings(export=None, export_type="", export_path=""):
    """For the block: ``export`` True/False switches QCoDeS' automatic export on/off (None: leave it as configured),
    ``export_type`` ("csv" or "netcdf") and ``export_path`` (a folder; empty: the configured one) say how. The
    configuration is restored afterwards."""
    section = qcodes.config.dataset
    keys = ("export_automatic", "export_type", "export_path")
    before = {key: section[key] for key in keys}
    try:
        if export is not None:
            section.export_automatic = bool(export)
        if export:
            section.export_type = export_type if export_type in EXPORT_TYPES else (before["export_type"] or "csv")
            if export_path:
                section.export_path = str(export_path)
        yield
    finally:
        for key, value in before.items():
            section[key] = value


def plot_folder():
    """Where the plots go: the export folder of the QCoDeS configuration (``export_path``)."""
    return get_data_export_path()


def _axes_needed(dataset):
    """One axes per measured parameter, two for a complex one (real and imaginary parts)."""
    top = dataset.description.interdeps.top_level_parameters
    return max(sum(2 if p.type == "complex" else 1 for p in top), 1)


def save_dataset_plots(datasets, fmt="png", folder=None):
    """Plot each dataset with ``plot_dataset`` and save the figure as ``plot_<run id>_<name>.<fmt>`` in ``folder`` (default:
    the export folder). Returns the paths written; a dataset that cannot be plotted is skipped."""
    folder = Path(folder) if folder else plot_folder()
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for dataset in datasets:
        try:
            count = _axes_needed(dataset)
            figure = Figure(figsize=(7, 4 * count))
            plot_dataset(dataset, axes=[figure.add_subplot(count, 1, i + 1) for i in range(count)])
            figure.tight_layout()
            name = re.sub(r"[^A-Za-z0-9-]+", "_", dataset.name).strip("_") or "run"
            path = folder / f"plot_{dataset.captured_run_id}_{name}.{fmt if fmt in PLOT_FORMATS else 'png'}"
            figure.savefig(path, dpi=150)
            written.append(path)
        except Exception as e:
            print(f"Could not save the plot of run {getattr(dataset, 'captured_run_id', '?')}: {type(e).__name__}: {e}")
    return written
