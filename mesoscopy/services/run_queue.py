"""The run queue: Measurement tab setups (recipes) run one after another (no widgets).

The queue keeps the list of recipes and their fate. To run one it asks the Measurement tab, through the hooks the main
window gives it, to take the recipe and build the request, hands the request to the run controller, and goes on
with the next recipe when ``runFinished`` says the run has ended. The tabs show the list and the state by subscribing to
the signals, and ask for things through the methods (they do not hold each other).
"""
import copy
import threading
from dataclasses import dataclass, field
from typing import Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from mesoscopy.core import queue_steps, recipes
from mesoscopy.core.gateway import USER, parameter_instruments
from mesoscopy.core.wait_tools import WaitTools

# the fate of a recipe
WAITING, RUNNING, DONE, STOPPED, FAILED, SKIPPED = "waiting", "running", "done", "stopped", "failed", "skipped"
FINISHED = (DONE, STOPPED, FAILED, SKIPPED)
# the state of the queue: idle, running (recipes are being run), stopping (halting after the current point)
IDLE, ACTIVE, HALTING = "idle", "running", "stopping"

RETRY_MS = 300  # while the instruments are busy (a ramp to 0 after the previous run), try again after this time


@dataclass(eq=False)  # two items with the same recipe are still two items
class QueueItem:
    state: dict                          # the recipe: ``SweepTab.get_state()`` data
    status: str = WAITING
    message: str = ""                    # why it failed, or how it ended
    run_ids: list = field(default_factory=list)  # the runs it wrote

    @property
    def title(self):
        return recipes.title(self.state)


@dataclass
class QueueHooks:
    """What the queue asks of the Measurement tab (the main window gives it)."""
    apply_state: Callable[[dict], list]  # set the tab up from a recipe; returns the problems found
    build_request: Callable[[], object]  # RunRequest from the fields; raises ValueError


class RunQueue(QObject):
    """The list of recipes and the run of it. See the module documentation."""

    changed = pyqtSignal()               # the list, or the status of an item, changed
    stateChanged = pyqtSignal(str)       # IDLE, ACTIVE or HALTING
    queueFinished = pyqtSignal(str)      # the queue ended: a sentence saying how
    # requests to the Measurement tab (it owns the fields)
    addCurrentRequested = pyqtSignal()
    replaceRequested = pyqtSignal(object)   # QueueItem to replace by the current setup
    editRequested = pyqtSignal(object)      # QueueItem to load in the tab, to edit

    def __init__(self, services):
        super().__init__()
        self.services = services
        self.items = []
        self.state = IDLE
        self.stop_on_failure = True
        self.hooks = None
        self.current = None              # the QueueItem being run
        self._session = None
        self._skipping = False
        self._only = None                # the one item a "run only this" asked for
        self._step_stop = threading.Event()  # ends the step in progress (Stop, Skip, closing)
        # what the last session left, if it ended while the queue was running (a crash, a power cut): read before the
        # autosave below overwrites it
        self.crash_data = self._read_crash()
        services.run.runFinished.connect(self._on_run_finished)
        services.run.runIdsKnown.connect(self._on_run_ids)
        self.changed.connect(self._autosave)
        self.stateChanged.connect(lambda _state: self._autosave())

    @property
    def active(self):
        return self.state != IDLE

    # ================= the list =================
    def _refuse(self, text):
        self.services.status.show(text, 4000)
        return False

    def add(self, state):
        """Append a recipe. Returns the item, or None (with a message) when the recipe cannot be run."""
        found = recipes.problems(state)
        if found:
            self._refuse("Cannot add to the queue: " + " and ".join(found) + ".")
            return None
        item = QueueItem(copy.deepcopy(state))
        self.items.append(item)
        self.changed.emit()
        return item

    def insert(self, states, index=None):
        """Put recipes and steps at ``index`` (the end by default). Returns the items, or None (with a message) when one
        of them cannot be run."""
        for state in states:
            found = recipes.problems(state)
            if found:
                self._refuse("Cannot add to the queue: " + " and ".join(found) + ".")
                return None
        items = [QueueItem(copy.deepcopy(state)) for state in states]
        at = len(self.items) if index is None else max(0, min(index, len(self.items)))
        self.items[at:at] = items
        self.changed.emit()
        return items

    @property
    def step_running(self):
        """The item in progress is a step (a wait, a set), not a measurement."""
        return self.current is not None and queue_steps.is_step(self.current.state)

    def update(self, item, state):
        """Replace the recipe of a waiting item."""
        if item not in self.items or item.status == RUNNING:
            return self._refuse("That item is running: it cannot be changed.")
        found = recipes.problems(state)
        if found:
            return self._refuse("Cannot update the item: " + " and ".join(found) + ".")
        item.state = copy.deepcopy(state)
        item.status, item.message, item.run_ids = WAITING, "", []
        self.changed.emit()
        return True

    def remove(self, items):
        """Remove items (the one being run stays)."""
        keep_running = [i for i in items if i.status == RUNNING]
        if keep_running:
            self._refuse("The item being run cannot be removed: use Skip or Stop.")
        before = len(self.items)
        self.items = [i for i in self.items if i not in items or i.status == RUNNING]
        if len(self.items) != before:
            self.changed.emit()

    def duplicate(self, item):
        if item in self.items:
            copy_item = QueueItem(copy.deepcopy(item.state))
            self.items.insert(self.items.index(item) + 1, copy_item)
            self.changed.emit()
            return copy_item

    def move(self, item, new_index):
        """Put an item at another place (the running one is not moved)."""
        if item not in self.items or item.status == RUNNING:
            return
        self.items.remove(item)
        self.items.insert(max(0, min(new_index, len(self.items))), item)
        self.changed.emit()

    def clear_finished(self):
        before = len(self.items)
        self.items = [i for i in self.items if i.status not in FINISHED]
        if len(self.items) != before:
            self.changed.emit()

    def reset(self, items):
        """Make finished items wait again."""
        for item in items:
            if item.status in FINISHED:
                item.status, item.message, item.run_ids = WAITING, "", []
        self.changed.emit()

    def waiting(self):
        return [i for i in self.items if i.status == WAITING]

    # ================= saving and restoring =================
    def to_data(self):
        """The queue as plain data (what a session remembers)."""
        return {"items": [i.state for i in self.items], "stop_on_failure": self.stop_on_failure}

    def to_text(self):
        return recipes.dump_queue([i.state for i in self.items], self.stop_on_failure)

    def replace_from_text(self, text):
        """Replace the queue by a queue file's content. Raises ValueError if it is not one."""
        states, stop = recipes.load_queue(text)
        self.set_items(states, stop)

    def set_items(self, states, stop_on_failure=True):
        if self.active:
            return self._refuse("The queue is running: stop it first.")
        self.items = [QueueItem(copy.deepcopy(s)) for s in states]
        self.stop_on_failure = bool(stop_on_failure)
        self.changed.emit()
        return True

    def restore_data(self, data):
        """Set the queue from ``to_data()`` (a session): finished items are not kept, everything waits."""
        if isinstance(data, dict):
            self.set_items([s for s in data.get("items") or [] if isinstance(s, dict)], data.get("stop_on_failure", True))

    # ================= surviving a crash =================
    def _autosave(self):
        """Write the queue and the fate of its items after every change. ``active`` stays true while it runs: if the
        next start finds it so, the application did not end cleanly."""
        try:
            self.services.settings.set_queue_autosave({
                "active": self.active, "stop_on_failure": self.stop_on_failure,
                "items": [{"state": i.state, "status": i.status, "message": i.message, "run_ids": list(i.run_ids)}
                          for i in self.items],
            })
        except Exception as e:  # keeping a copy is a convenience: never disturb the queue
            print(f"Could not save the queue: {e}")

    def _read_crash(self):
        data = self.services.settings.queue_autosave()
        items = data.get("items")
        if data.get("active") and isinstance(items, list) and any(
                isinstance(i, dict) and i.get("status") == RUNNING for i in items):
            return data
        return None

    def mark_clean(self):
        """The application is closing: an item still running is ended by that, and the queue is not 'active' any more."""
        self._step_stop.set()
        if self.current is not None:
            self._set_item(self.current, STOPPED, "the application was closed")
            self.current = None
        self.state = IDLE
        self._autosave()

    def restore_after_crash(self, rerun_interrupted=True):
        """Put the queue of the interrupted session back. Finished items keep their fate; the one that was running
        waits again (``rerun_interrupted``) or is marked stopped. Nothing starts: the instruments must be loaded first."""
        data, self.crash_data = self.crash_data, None
        if not data or self.active:
            return False
        self.items = []
        for entry in data.get("items", []):
            if not isinstance(entry, dict) or not isinstance(entry.get("state"), dict):
                continue
            item = QueueItem(copy.deepcopy(entry["state"]), run_ids=[i for i in entry.get("run_ids", []) if isinstance(i, int)])
            status = entry.get("status")
            if status == RUNNING:
                item.status, item.message = (WAITING, "interrupted by a crash: it will run again") if rerun_interrupted \
                    else (STOPPED, "interrupted by a crash")
                if rerun_interrupted:
                    item.run_ids = []  # the partial run stays in the database but is not this item's result
            else:
                item.status = status if status in FINISHED else WAITING
                item.message = str(entry.get("message", ""))
            self.items.append(item)
        self.stop_on_failure = bool(data.get("stop_on_failure", True))
        self.changed.emit()
        return True

    def interrupted_summary(self):
        """(items finished, items, title of the one that was running) of the interrupted session, or None."""
        data = self.crash_data
        if not data:
            return None
        items = [i for i in data.get("items", []) if isinstance(i, dict) and isinstance(i.get("state"), dict)]
        running = next((i for i in items if i.get("status") == RUNNING), None)
        return (len([i for i in items if i.get("status") in FINISHED]), len(items),
                recipes.title(running["state"]) if running else "")

    # ================= running =================
    def start(self, only=None):
        """Run the waiting items one after the other, or only ``only``. Returns True if it started."""
        status = self.services.status
        if self.active:
            return self._refuse("The queue is already running.")
        if self.hooks is None:
            return self._refuse("The Measurement tab is not available.")
        if self.services.station.station is None:
            return self._refuse("Please load a station first.")
        if only is not None:
            self._only = only
            if only.status in FINISHED:
                self.reset([only])
        else:
            self._only = None
        if not self._pending():
            return self._refuse("Nothing is waiting in the queue.")
        self._skipping = False
        self._set_state(ACTIVE)
        waiting_for = self.services.run.running  # a measurement started by hand: the queue follows it
        status.show("The queue starts when the measurement in progress has ended." if waiting_for
                    else "Running the queue...")
        self._advance()
        return True

    def _pending(self):
        return [self._only] if self._only is not None and self._only.status == WAITING else (
            [] if self._only is not None else self.waiting())

    def _set_state(self, state):
        if state != self.state:
            self.state = state
            self.stateChanged.emit(state)

    def _advance(self):
        """Start the next waiting item, or end the queue."""
        if self.state != ACTIVE:
            if self.state == HALTING and self.current is None:
                self._end("The queue was stopped.")
            return
        pending = self._pending()
        if not pending:
            return self._end("The queue is finished.")
        gateway = self.services.gateway
        if self.services.run.running or gateway.busy():  # a measurement in progress, or a ramp to 0 after it
            QTimer.singleShot(RETRY_MS, self._advance)
            return
        item = pending[0]
        self.current = item
        self._set_item(item, RUNNING, "")
        item.run_ids = []
        if queue_steps.is_step(item.state):
            return self._run_step(item)
        try:
            problems = self.hooks.apply_state(item.state)
            if problems:
                raise ValueError("; ".join(problems))
            request = self.hooks.build_request()
        except ValueError as e:
            return self._item_failed(item, str(e))
        if not self.services.run.start(request):
            return self._item_failed(item, self.services.run.last_problem or gateway.last_refusal
                                     or "the measurement could not start (see the status bar)")
        self._session = self.services.run.session

    # ----- steps: waits, sets, repeat-until -----
    def _run_step(self, item):
        """Run a step in the instrument gateway: it ends by itself, or when the queue is stopped or skipped."""
        services = self.services
        parameters = services.registry.parameters()
        step = item.state[queue_steps.STEP_KEY]
        names = set()  # the instruments it touches; a condition may read any of them
        if step["kind"] == "repeat_until":
            names = None
        else:
            for name in queue_steps.parameter_names(item.state):
                if name in parameters:
                    names |= parameter_instruments(parameters[name])
        self._step_stop = threading.Event()
        stop = self._step_stop
        tools = WaitTools(stopped=stop.is_set, announce=lambda text: services.status.show(text, 8000))
        job = services.gateway.submit(queue_steps.execute, item.state, dict(parameters), tools, services.restore,
                                      kind=USER, instruments=names, label=f"Queue step: {recipes.title(item.state)}")
        if job is None:
            return self._item_failed(item, services.gateway.last_refusal or "the step could not start")
        job.signals.result.connect(lambda outcome, i=item: self._step_done(i, outcome))
        job.signals.error.connect(lambda err, i=item: self._step_failed(i, err))

    def _step_done(self, item, outcome):
        if item is not self.current:
            return
        self.current = None
        if outcome == "stopped":
            skipped, self._skipping = self._skipping, False
            self._set_item(item, SKIPPED if skipped else STOPPED, "skipped by the user" if skipped else "stopped by the user")
            return self._after_item(stopped_by_user=not skipped)
        message = ""
        if outcome == "repeat":
            message = self._repeat_measurement(item)
            if message is None:
                return self._item_failed(item, "there is no measurement before it to repeat")
        self._skipping = False
        self._set_item(item, DONE, message)
        self._after_item()

    def _step_failed(self, item, err):
        if item is not self.current:
            return
        self.current, self._skipping = None, False
        error = err[1]
        self._set_item(item, FAILED, f"{type(error).__name__}: {error}")
        self._after_item(failed=True)

    def _repeat_measurement(self, item):
        """The condition of a repeat-until step is not met: queue the measurement before it, and the step, again."""
        index = self.items.index(item)
        before = next((i for i in reversed(self.items[:index]) if not queue_steps.is_step(i.state)), None)
        if before is None:
            return None
        again = copy.deepcopy(item.state)
        again[queue_steps.STEP_KEY]["count"] = int(item.state[queue_steps.STEP_KEY].get("count", 0)) + 1
        self.items[index + 1:index + 1] = [QueueItem(copy.deepcopy(before.state)), QueueItem(again)]
        return (f"condition not met: repeating '{recipes.title(before.state)}' "
                f"({again[queue_steps.STEP_KEY]['count']} of {again[queue_steps.STEP_KEY].get('max_repeats')})")

    def _item_failed(self, item, message):
        self._set_item(item, FAILED, message)
        self.current, self._session = None, None
        self._after_item(failed=True)

    def _on_run_ids(self, run_ids):
        if self.current is not None and self._session is not None:
            self.current.run_ids.extend(run_ids)

    def _on_run_finished(self, session):
        item = self.current
        if item is None or session is not self._session:
            return  # a run that does not come from the queue
        self.current, self._session = None, None
        stopped_by_user = session.stopped and not self._skipping
        if session.failed:
            self._set_item(item, FAILED, "the measurement failed (see the status bar)")
        elif self._skipping:
            self._set_item(item, SKIPPED, "skipped by the user")
        elif session.stopped:
            self._set_item(item, STOPPED, "stopped by the user")
        elif session.reason:
            self._set_item(item, DONE, f"ended on a breakout condition: {session.reason}")
        else:
            self._set_item(item, DONE, "")
        self._skipping = False
        # the tabs handle the end of the run first (unlock their inputs): go on afterwards
        self._after_item(failed=session.failed or bool(session.reason and not session.stopped),
                         stopped_by_user=stopped_by_user)

    def _after_item(self, failed=False, stopped_by_user=False):
        if stopped_by_user or self.state == HALTING:
            self._end("The queue was stopped.")
        elif failed and self.stop_on_failure:
            self._end("The queue stopped: a measurement failed or hit a breakout condition.")
        else:
            QTimer.singleShot(0, self._advance)

    def _end(self, text):
        self._only = None
        self._set_state(IDLE)
        self.services.status.show(text, 8000)
        self.queueFinished.emit(text)
        self.changed.emit()

    def _set_item(self, item, status, message):
        item.status, item.message = status, message
        self.changed.emit()

    # ================= controlling =================
    def skip(self):
        """End the measurement in progress cleanly (what is written stays) and go on with the next item."""
        if self.state == ACTIVE and self.step_running:
            self._skipping = True
            self._step_stop.set()
        elif self.state == ACTIVE and self.current is not None and self.services.run.running:
            self._skipping = True
            self.services.run.stop()

    def stop(self):
        """End the measurement in progress cleanly and do not start another one."""
        if not self.active:
            return
        self._set_state(HALTING)
        if self.step_running:
            self._step_stop.set()  # the step ends, and with it the queue
        elif self.current is not None and self.services.run.running:
            self.services.run.stop()
        else:
            self._end("The queue was stopped.")

    def progress(self):
        """(items finished, items in this pass, fraction of the item in progress) for the overall bar."""
        run = self.services.run
        fraction = 0.0
        if self.current is not None and run.session is not None and run.running:
            progress = run.session.progress
            whole = progress.total * progress.repetitions
            fraction = min(progress.done / whole, 1.0) if whole else 0.0
        counted = self.items if self._only is None else [self._only]
        finished = len([i for i in counted if i.status in FINISHED])
        return finished, len(counted), fraction
