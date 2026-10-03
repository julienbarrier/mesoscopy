"""Progress bookkeeping of a running measurement: elapsed and remaining time (no Qt)."""
import time


class RunProgress:
    """Counts the measured points of a run.

    ``total`` is the number of points of one run, ``repetitions`` how many runs follow each other.
    ``step`` is meant to be called once per point from the worker thread (it is attached as a
    post-action of the innermost sweep); the GUI thread reads the timing properties.
    """

    def __init__(self, total_points, inner_points):
        self.total = total_points
        self.inner_points = inner_points  # points of the innermost (fastest) sweep
        self.x_default = None             # dataset name proposed for the plot's x axis
        self.repetitions = 1              # the measurement is run this many times, one after the other
        self.done = 0
        self.started_at = None            # all times are on the run clock, which stands still while paused
        self.first_point_at = None
        self.finished_at = None
        self._paused_total = 0.0
        self._paused_since = None

    def _clock(self):
        """Seconds of running time: the monotonic clock minus the time spent paused."""
        now = time.monotonic()
        paused = self._paused_total + (now - self._paused_since if self._paused_since is not None else 0.0)
        return now - paused

    def start(self):
        self.started_at = self._clock()

    def pause(self):
        """The run is waiting: elapsed and remaining time stand still until ``resume``."""
        if self._paused_since is None:
            self._paused_since = time.monotonic()

    def resume(self):
        if self._paused_since is not None:
            self._paused_total += time.monotonic() - self._paused_since
            self._paused_since = None

    @property
    def paused(self):
        return self._paused_since is not None

    def step(self):
        if self.first_point_at is None:
            self.first_point_at = self._clock()
        self.done += 1

    def finish(self):
        self.finished_at = self._clock()

    def elapsed(self):
        """Seconds of running time since the run started (frozen once finished); None before start."""
        if self.started_at is None:
            return None
        return (self.finished_at if self.finished_at is not None else self._clock()) - self.started_at

    def remaining(self):
        """Estimated seconds left from the pace of the points so far; None if not known yet."""
        if self.finished_at is not None:
            return 0.0
        if self.done == 0 or self.first_point_at is None:
            return None
        pace = (self._clock() - self.first_point_at) / self.done
        return max(self.total * self.repetitions - self.done, 0) * pace

    def run_done(self):
        """Points done in the repetition in progress: the progress of the axes starts again with each repetition."""
        if self.done <= 0 or self.total <= 0:
            return self.done
        return (self.done - 1) % self.total + 1

    def repetition(self):
        """Number (from 1) of the repetition in progress."""
        if self.done <= 0 or self.total <= 0:
            return 1
        return min((self.done - 1) // self.total + 1, self.repetitions)


def axis_positions(done, sizes):
    """Where each loop of a nested sweep is, given the number of points done.

    ``sizes`` are the points of each axis, outermost first. Returns, per axis, the 1-based index
    of the point in progress (all 0 before the first point). The innermost axis varies fastest.
    """
    if done <= 0:
        return [0] * len(sizes)
    remaining = min(done, _total(sizes)) - 1
    indices = []
    for size in reversed(sizes):
        indices.append(remaining % size + 1)
        remaining //= size
    return indices[::-1]


def _total(sizes):
    total = 1
    for size in sizes:
        total *= size
    return total


def estimate_seconds(axes):
    """Run time of nested sweeps from their delays: ``axes`` = [(points, delay), ...], outermost first.

    Each point of an axis waits its delay and then runs the whole inner loop. The acquisition
    time of the instruments is not known and not included.
    """
    seconds = 0.0
    for points, delay in reversed(axes):
        seconds = points * (max(delay, 0.0) + seconds)
    return seconds


def format_estimate(seconds):
    """Duration in the most convenient units: '10s', '2min 30s', '23min', '3h 5min', '1d 3h 5min'.

    Seconds are only given below 10 minutes.
    """
    if seconds < 0.5:
        return "<1s"
    if seconds < 600:
        total = int(round(seconds))
        minutes, secs = divmod(total, 60)
        parts = ([f"{minutes}min"] if minutes else []) + ([f"{secs}s"] if secs or not minutes else [])
        return " ".join(parts)
    minutes_total = int(round(seconds / 60))
    days, rest = divmod(minutes_total, 24 * 60)
    hours, minutes = divmod(rest, 60)
    parts = [f"{days}d"] if days else []
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}min")
    return " ".join(parts)
