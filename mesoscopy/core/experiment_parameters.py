"""Experiment parameters: the parameters chosen as relevant for a measurement (no Qt).

An experiment parameter is a QCoDeS parameter placed at the *root* of the station. It is either

* an *instrument* parameter: a ``DelegateParameter`` on a parameter somewhere in an instrument's tree,
  with a name, a gain, safe limits and a maximum ramp rate,
* a *derived* parameter: a get-only parameter computed from an expression of other experiment parameters, or
* a *root* parameter: a parameter the station file already declares at the root of the station
  (no instrument involved, e.g. an elapsed-time parameter); it is used as it is.

Parameters declared in the station file are added automatically: the ones under an instrument's
``add_parameters`` when that instrument is loaded, and the root ones as soon as the file is loaded.

The rest of the application (sweeps, measured parameters) only looks at these root parameters. The
registry owns their definitions, builds and removes the parameters as instruments come and go, and
saves the definitions next to the station file.
"""
import ast
import builtins
import json
import keyword
import math
import operator
import os
import re
from dataclasses import asdict, dataclass, field

import numpy as np
import qcodes.validators as vals
from PyQt6.QtCore import QObject, pyqtSignal
from qcodes.instrument import InstrumentBase
from qcodes.parameters import DelegateParameter, Parameter, ParameterBase
from scipy import constants as const

from mesoscopy.core.parameter_io import get_children
from mesoscopy.core.trace_parameter import AxisParameter, TraceParameter, is_trace
from mesoscopy.instrument.station_config import declared_parameters, root_parameter_names

OPERATORS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}
RAMP_INTER_DELAY = 0.1  # seconds; QCoDeS step = max ramp rate * inter_delay
RESERVED_NAMES = {"np", "numpy", "const"}
_SAFE_BUILTINS = {n: getattr(builtins, n) for n in
                  ("abs", "all", "any", "bool", "float", "int", "len", "max", "min", "pow", "round", "sum")}
_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# ----- station helpers -----
def instruments_of(station):
    """The instruments of a station ({name: instrument}); root parameters are left out."""
    if station is None:
        return {}
    return {name: c for name, c in station.components.items() if isinstance(c, InstrumentBase)}


def resolve_source(station, path):
    """The parameter at ``path`` (component names from the station root, e.g. ['dac', 'ch1']), or None."""
    if station is None or not path:
        return None
    node = station.components.get(path[0])
    if not isinstance(node, InstrumentBase):
        return None
    for name in path[1:]:
        node = get_children(node).get(name)
        if node is None:
            return None
    return node if isinstance(node, ParameterBase) else None


def expression_names(expression):
    """Names used in an expression, without the ones that are always available (np, const, builtins)."""
    tree = ast.parse(expression, mode="eval")
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    return names - RESERVED_NAMES - set(_SAFE_BUILTINS)


def validate_name(name, taken=()):
    """Raise ValueError unless ``name`` can be a root parameter name (a Python identifier, unique)."""
    if not _NAME_PATTERN.match(name or "") or keyword.iskeyword(name):
        raise ValueError("The name must be a Python identifier (letters, digits and underscores, "
                         "not starting with a digit).")
    if name in RESERVED_NAMES:
        raise ValueError(f"'{name}' is reserved.")
    if name in taken:
        raise ValueError(f"'{name}' is already used.")


# ----- definitions -----
@dataclass
class Breakout:
    """Stop the measurement when ``value <operator> threshold`` (on |value| if ``absolute``)."""
    enabled: bool = False
    operator: str = ">"
    threshold: float = 0.0
    absolute: bool = True

    def triggered(self, value):
        measured = abs(value) if self.absolute else value
        return bool(OPERATORS[self.operator](measured, self.threshold))

    def describe(self, name):
        shown = f"|{name}|" if self.absolute else name
        return f"{shown} {self.operator} {self.threshold:g}"


@dataclass
class ParameterDefinition:
    name: str
    kind: str = "instrument"                    # "instrument", "derived", "root" or "trace"
    source: list = field(default_factory=list)  # instrument kind: component names from the station root
    expression: str = ""                        # derived kind: expression of other experiment parameters
    unit: str = ""
    gain: float = 1.0                           # value = source value * gain
    min_value: float | None = None
    max_value: float | None = None
    max_ramp_rate: float | None = None          # unit per second
    breakout: Breakout = field(default_factory=Breakout)
    origin: str = "user"                        # "station" when it comes from the station file
    # trace kind: ``source`` is an array-valued parameter, measured over an axis
    axis_kind: str = "linspace"                 # "linspace" (start, stop, points) or "parameter" (the values of axis_source)
    axis_start: float = 0.0
    axis_stop: float = 1.0
    axis_points: int = 101
    axis_source: list = field(default_factory=list)  # parameter kind: component names from the station root
    axis_name: str = ""
    axis_unit: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data["breakout"] = Breakout(**data.get("breakout", {}))
        return cls(**data)

    def source_text(self):
        if self.kind == "root":
            return "station file"
        return ".".join(self.source) if self.kind in ("instrument", "trace") else self.expression

    def dismiss_key(self):
        """Identifies a station-declared parameter, to remember that the user removed it."""
        return f"root:{self.name}" if self.kind == "root" else "source:" + ".".join(self.source)


class BreakoutWatcher:
    """Checks the breakout conditions of the experiment parameters during a run.

    ``check`` is meant as dond's ``break_condition``. With several conditions, ``mode`` decides when the run
    stops: ``"any"`` (the default) as soon as one condition is true, ``"all"`` when every condition is true at
    the same time.
    A parameter that is part of the measurement was just read by dond, so its last value is used; the others
    are read. A reading that fails always stops the run, whatever the mode: a safety stop is safer than
    running blind.
    """

    MODES = ("any", "all")

    def __init__(self, items, measured_parameters=(), mode="any"):
        self._items = list(items)  # [(definition, parameter)]
        self._measured = {id(p) for p in measured_parameters}
        self.mode = mode if mode in self.MODES else "any"
        self.reason = None

    def check(self):
        if not self._items:
            return False
        hits = []
        for definition, parameter in self._items:
            try:
                value = float(parameter.get_latest() if id(parameter) in self._measured else parameter.get())
            except Exception as e:
                self.reason = f"breakout: could not read {definition.name} ({type(e).__name__}: {e})"
                return True
            if definition.breakout.triggered(value):
                hits.append((definition, value))
        if len(hits) == len(self._items) if self.mode == "all" else bool(hits):
            joiner = " and " if self.mode == "all" else " or "
            self.reason = "breakout: " + joiner.join(
                f"{d.breakout.describe(d.name)} (value {v:.4g})" for d, v in hits
            )
            return True
        return False


# ----- the registry -----
class ParameterRegistry(QObject):
    """Definitions of the experiment parameters and the root parameters built from them.

    ``parametersChanged`` is emitted whenever the definitions or the parameters built from them may have changed
    (after ``attach``, ``sync``, ``add``, ``update``, ``remove``): the tabs that show experiment parameters
    subscribe to it instead of being told one by one."""

    parametersChanged = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.station = None
        self.path = None
        self.definitions = {}  # name -> ParameterDefinition, in creation order
        self._built = {}       # name -> parameter placed at the root of the station
        self._errors = {}      # name -> why a definition could not be built
        self._owned = set()    # names of the parameters this registry added to the station (and may remove)
        self.station_config = {}  # the ``instruments`` section of the station file
        self.dismissed = set()    # station-declared parameters the user removed: not added again
        self.last_error = ""

    # ----- station and persistence -----
    @staticmethod
    def path_for_station_file(station_file):
        stem = station_file[:-len(".station.yaml")] if station_file.endswith(".station.yaml") else station_file
        return stem + ".parameters.json"

    def attach(self, station, path=None, station_config=None):
        """Use a (new) station; definitions saved at ``path`` are loaded.

        ``station_config`` is the ``instruments`` section of the station file: the parameters it
        declares are added as experiment parameters (see ``sync``).
        """
        self.station, self.path = station, path
        self.station_config = dict(station_config or {})
        self._built, self._errors, self._owned = {}, {}, set()
        self.definitions, self.dismissed, self.last_error = {}, set(), ""
        if path and os.path.isfile(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                self.dismissed = set(data.get("dismissed", []))
                for item in data.get("parameters", []):
                    definition = ParameterDefinition.from_dict(item)
                    self.definitions[definition.name] = definition
            except (OSError, ValueError, TypeError) as e:
                self.last_error = f"Could not read {os.path.basename(path)}: {e}"
        self.sync()

    def save(self):
        """Write the definitions next to the station file. The file is written whole under another name and then put
        in place, so that a write that fails half way (a synchronised folder that stops answering, a full disk) leaves
        the previous file intact. A failure is reported in ``last_error``; the next ``save`` tries again."""
        if not self.path:
            return
        temporary = f"{self.path}.tmp"
        try:
            with open(temporary, "w") as f:
                json.dump({"parameters": [d.to_dict() for d in self.definitions.values()],
                           "dismissed": sorted(self.dismissed)}, f, indent=2)
            os.replace(temporary, self.path)
            self.last_error = ""
        except OSError as e:
            self.last_error = (f"Could not save {os.path.basename(self.path)}: {e}. The parameters stay defined in "
                               "the application; they are saved again at the next change.")
            try:
                os.remove(temporary)
            except OSError:
                pass

    # ----- queries -----
    def parameters(self):
        """The available root parameters ({name: parameter})."""
        return {name: p for name, p in self._built.items()}

    def is_available(self, name):
        return name in self._built

    def find_by_source(self, path):
        return next((d for d in self.definitions.values()
                     if d.kind == "instrument" and list(d.source) == list(path)), None)

    def dependents(self, name):
        """Derived definitions that use the parameter ``name``."""
        return [d.name for d in self.definitions.values()
                if d.kind == "derived" and name in self._expression_names(d)]

    def breakout_items(self):
        """[(definition, parameter)] of the available parameters that have a breakout condition."""
        return [(d, self._built[d.name]) for d in self.definitions.values()
                if d.breakout.enabled and d.name in self._built]

    def error(self, name):
        """Why the definition ``name`` could not be built (empty when there is no problem)."""
        return self._errors.get(name, "")

    def status(self, name):
        if name in self._built:
            return "ready"
        if name in self._errors:
            return f"error: {self._errors[name]}"
        definition = self.definitions[name]
        if definition.kind == "root":
            return "not in the station"
        if definition.kind in ("instrument", "trace"):
            return f"waiting for {definition.source[0]}" if definition.source else "no source"
        missing = [n for n in self._expression_names(definition) if n not in self._built]
        return "waiting for " + ", ".join(missing) if missing else "waiting"

    # ----- changes -----
    def validate(self, definition, editing=False):
        """Raise ValueError if ``definition`` could not be added (or, when ``editing``, replace its namesake)."""
        if not editing:
            validate_name(definition.name, taken=set(self.definitions) | set(instruments_of(self.station)))
        self._check(definition)

    def add(self, definition):
        self.validate(definition)
        self.definitions[definition.name] = definition
        self.sync()
        if definition.name in self._errors:  # it could not be built: do not keep (or save) it
            error = self._errors.pop(definition.name)
            del self.definitions[definition.name]
            raise ValueError(f"Could not create '{definition.name}': {error}")
        self.save()

    def update(self, definition):
        """Replace the definition with the same name."""
        name = definition.name
        if name not in self.definitions:
            raise ValueError(f"No parameter named '{name}'.")
        self._check(definition)
        previous = self.definitions[name]
        self._unbuild(name)
        self._errors.pop(name, None)
        self.definitions[name] = definition
        self.sync()
        if name in self._errors:  # it could not be built: go back to the previous definition
            error = self._errors.pop(name)
            self.definitions[name] = previous
            self.sync()
            raise ValueError(f"Could not change '{name}': {error}")
        self.save()

    def remove(self, name):
        users = self.dependents(name)
        if users:
            raise ValueError(f"'{name}' is used by {', '.join(users)}: remove those first.")
        definition = self.definitions.get(name)
        self._unbuild(name)
        self.definitions.pop(name, None)
        self._errors.pop(name, None)
        if definition is not None and definition.origin == "station":
            self.dismissed.add(definition.dismiss_key())  # declared in the station file: do not bring it back
        self.save()
        self.parametersChanged.emit()

    def has_dismissed(self):
        return bool(self.dismissed)

    def restore_dismissed(self):
        """Bring back the station-declared parameters that were removed."""
        self.dismissed = set()
        self.sync()
        self.save()

    def _check(self, definition):
        if definition.kind == "derived":
            if not definition.expression.strip():
                raise ValueError("Enter an expression.")
            try:
                names = expression_names(definition.expression)
                compile(definition.expression, "<expression>", "eval")
            except SyntaxError as e:
                raise ValueError(f"Invalid expression: {e.msg}") from None
            unknown = [n for n in names if n not in self.definitions or n == definition.name]
            if unknown:
                raise ValueError(f"Unknown parameter(s) in the expression: {', '.join(sorted(unknown))}. "
                                 f"Available: {', '.join(sorted(set(self.definitions) - {definition.name})) or 'none'}.")
            self._check_cycle(definition)
        elif definition.kind == "instrument" and not definition.source:
            raise ValueError("The parameter has no source.")
        elif definition.kind == "trace":
            self._check_trace(definition)
        self._check_values(definition)

    @staticmethod
    def _check_trace(definition):
        """A trace needs the array parameter it reads and an axis: start, stop and points, or another parameter."""
        if not definition.source:
            raise ValueError("The trace has no source.")
        if definition.axis_kind == "parameter":
            if not definition.axis_source:
                raise ValueError("Select the parameter that gives the axis.")
        elif definition.axis_kind == "linspace":
            for what, value in (("start", definition.axis_start), ("stop", definition.axis_stop)):
                if value is None or not math.isfinite(value):
                    raise ValueError(f"The axis {what} must be a finite number.")
            if int(definition.axis_points) < 2:
                raise ValueError("The axis needs at least 2 points.")
        else:
            raise ValueError(f"Unknown axis kind '{definition.axis_kind}'.")

    @staticmethod
    def _check_values(definition):
        """Numbers of a definition: all finite, a non-zero gain, minimum strictly below maximum."""
        def finite(value, what):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{what} must be a finite number.")

        finite(definition.gain, "The gain")
        finite(definition.min_value, "The minimum")
        finite(definition.max_value, "The maximum")
        finite(definition.max_ramp_rate, "The maximum ramp rate")
        if definition.breakout.enabled:
            finite(definition.breakout.threshold, "The breakout threshold")
        if definition.gain == 0:
            raise ValueError("The gain cannot be 0.")
        if None not in (definition.min_value, definition.max_value) and definition.min_value >= definition.max_value:
            raise ValueError("The minimum must be below the maximum.")
        if definition.max_ramp_rate is not None and definition.max_ramp_rate <= 0:
            raise ValueError("The maximum ramp rate must be positive.")
        if definition.breakout.operator not in OPERATORS:
            raise ValueError(f"Unknown breakout operator '{definition.breakout.operator}'.")

    def _check_cycle(self, definition):
        definitions = dict(self.definitions, **{definition.name: definition})

        def visit(name, trail):
            if name in trail:
                raise ValueError("The expressions depend on each other in a loop.")
            d = definitions.get(name)
            if d is not None and d.kind == "derived":
                for dep in expression_names(d.expression):
                    visit(dep, trail | {name})

        visit(definition.name, frozenset())

    # ----- keeping the station in step -----
    @staticmethod
    def _expression_names(definition):
        try:
            return expression_names(definition.expression)
        except SyntaxError:
            return set()

    def sync(self):
        """Build the parameters whose source is available and remove those whose source is gone (then emit
        ``parametersChanged``).

        Call after instruments are loaded or disconnected. Definitions are kept either way.
        Parameters the station file declares are added first, so they are experiment parameters as soon
        as their instrument (or the file itself, for root parameters) is loaded.
        """
        if self.station is None:
            return
        try:
            self._sync()
        finally:
            self.parametersChanged.emit()

    def _sync(self):
        if self._discover_station_parameters():
            self.save()
        self._errors = {}  # recomputed below: a definition that failed is tried again, the situation may have changed
        changed = True
        while changed:  # removing a parameter can invalidate the ones derived from it
            changed = False
            for name, parameter in list(self._built.items()):
                definition = self.definitions.get(name)
                if definition is None or not self._still_valid(definition, parameter):
                    self._unbuild(name)
                    changed = True
        progress = True
        while progress:  # building a parameter can make a derived one possible
            progress = False
            for name, definition in self.definitions.items():
                if name not in self._built and name not in self._errors:
                    try:
                        self._check_values(definition)
                        parameter = self._try_build(definition)
                        if parameter is not None and definition.kind != "root" and not self._used_as_is(parameter, definition):
                            self.station.add_component(parameter, update_snapshot=False)
                            self._owned.add(name)
                    except Exception as e:  # a bad definition must never break the application
                        self._errors[name] = str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"
                        continue
                    if parameter is not None:
                        self._built[name] = parameter
                        progress = True

    def _still_valid(self, definition, parameter):
        if definition.kind == "root":
            return self.station.components.get(definition.name) is parameter
        if definition.kind == "instrument":
            source = resolve_source(self.station, definition.source)
            if self._used_as_is(parameter, definition):  # a trace of the driver: the parameter itself
                return source is parameter
            return source is getattr(parameter, "source", None)
        if definition.kind == "trace":
            return resolve_source(self.station, definition.source) is getattr(parameter, "source", None) and (
                definition.axis_kind != "parameter"
                or resolve_source(self.station, definition.axis_source) is parameter._dependencies.get("axis")
            )
        return all(self._built.get(n) is obj for n, obj in getattr(parameter, "_dependencies", {}).items())

    def _unbuild(self, name):
        parameter = self._built.pop(name, None)
        if parameter is None:
            return
        if name in self._owned:  # a root parameter from the station file is not ours to remove
            self._owned.discard(name)
            try:
                self.station.remove_component(name)
            except KeyError:
                pass
        self.station._monitor_parameters[:] = [p for p in self.station._monitor_parameters if p is not parameter]

    def _try_build(self, definition):
        if definition.kind == "root":
            component = self.station.components.get(definition.name)
            return component if isinstance(component, ParameterBase) else None
        if definition.kind == "instrument":
            source = resolve_source(self.station, definition.source)
            if source is not None and is_trace(source):
                return source  # a trace of the driver is measured as it is: a delegate would lose its axis
            return None if source is None else self._build_delegate(definition, source)
        if definition.kind == "trace":
            return self._build_trace(definition)
        names = self._expression_names(definition)
        if not names or any(n not in self._built for n in names):
            return None
        return self._build_derived(definition, {n: self._built[n] for n in names})

    # ----- parameters declared in the station file -----
    def _free_name(self, preferred, instrument):
        """The root name of a parameter declared on ``instrument``: always prefixed with the instrument name,
        so that instruments sharing the same aliases (freq, time_constant, ...) are named consistently."""
        base = f"{instrument}_{re.sub(r'\W', '_', preferred)}"
        used = set(self.definitions) | set(self.station.components) | RESERVED_NAMES
        candidate, index = base, 2
        while candidate in used or not _NAME_PATTERN.match(candidate) or keyword.iskeyword(candidate):
            candidate, index = f"{base}_{index}", index + 1
        return candidate

    def _discover_station_parameters(self):
        """Add the parameters the station file declares and that are not known yet. True if any was added."""
        added = False
        known = {d.dismiss_key() for d in self.definitions.values()} | self.dismissed
        # parameters at the root of the station (no instrument): available once the file is loaded
        for name in root_parameter_names(self.station_config):
            component = self.station.components.get(name)
            definition = ParameterDefinition(name=name, kind="root", origin="station",
                                             unit=getattr(component, "unit", "") or "")
            if isinstance(component, ParameterBase) and name not in self.definitions \
                    and definition.dismiss_key() not in known:
                self.definitions[name] = definition
                added = True
        # custom parameters of an instrument (add_parameters): available once the instrument is loaded
        for instrument in instruments_of(self.station):
            for declared, options in declared_parameters(self.station_config.get(instrument)).items():
                path = [instrument, *declared.split(".")]
                parameter = resolve_source(self.station, path)
                key = "source:" + ".".join(path)
                if parameter is None or key in known:
                    continue
                options = options if isinstance(options, dict) else {}
                limits = options.get("limits") or (None, None)
                step, delay = options.get("step"), options.get("inter_delay")
                name = self._free_name(declared.split(".")[-1], instrument)
                self.definitions[name] = ParameterDefinition(
                    name=name, source=path, origin="station", unit=options.get("unit") or parameter.unit or "",
                    min_value=limits[0], max_value=limits[1],
                    max_ramp_rate=step / delay if step and delay else None,
                )
                added = True
        return added

    @staticmethod
    def _build_delegate(definition, source):
        kwargs = {"label": definition.name, "unit": definition.unit or source.unit}
        if definition.gain != 1:
            kwargs["scale"] = 1 / definition.gain  # QCoDeS divides: source = value * scale
        numeric = source.vals is None or isinstance(source.vals, (vals.Numbers, vals.Ints))
        if source.settable and numeric:
            low = -np.inf if definition.min_value is None else definition.min_value
            high = np.inf if definition.max_value is None else definition.max_value
            kwargs["vals"] = vals.Numbers(low, high)
            if definition.max_ramp_rate:
                kwargs["inter_delay"] = RAMP_INTER_DELAY
                kwargs["step"] = definition.max_ramp_rate * RAMP_INTER_DELAY
        return DelegateParameter(definition.name, source=source, **kwargs)

    @staticmethod
    def _used_as_is(parameter, definition):
        """True for a trace of a driver: it belongs to its instrument, not to the root of the station."""
        return definition.kind == "instrument" and is_trace(parameter) and not hasattr(parameter, "source")

    def _build_trace(self, definition):
        """The array parameter measured over its axis; None while the parameters it needs are not available."""
        source = resolve_source(self.station, definition.source)
        axis_source = resolve_source(self.station, definition.axis_source) if definition.axis_kind == "parameter" else None
        if source is None or (definition.axis_kind == "parameter" and axis_source is None):
            return None
        axis = AxisParameter(
            definition.axis_name or f"{definition.name}_axis", definition.axis_name or "", definition.axis_unit,
            definition.axis_start, definition.axis_stop, definition.axis_points, axis_source,
        )
        return TraceParameter(definition.name, source, axis, label=definition.name, unit=definition.unit)

    @staticmethod
    def _build_derived(definition, dependencies):
        code = compile(definition.expression, "<expression>", "eval")

        def compute():
            namespace = {"__builtins__": _SAFE_BUILTINS, "np": np, "numpy": np, "const": const}
            namespace.update({name: parameter.get() for name, parameter in dependencies.items()})
            return eval(code, namespace)

        parameter = Parameter(definition.name, get_cmd=compute, set_cmd=False, label=definition.name,
                              unit=definition.unit)
        parameter._dependencies = dependencies  # the objects it was built from, to notice when they change
        return parameter
