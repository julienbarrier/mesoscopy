"""Which instruments of the station in use the next station keeps (no Qt)."""


def plan_handover(loaded, old_entries, new_entries):
    """(keep, drop): the names of the loaded instruments the new station can keep and those it cannot.

    ``loaded`` is {name: instrument}; ``old_entries`` and ``new_entries`` are the ``instruments`` sections of the
    station files. An instrument is kept, still connected, when the new file has an entry of the same name that is
    identical (same driver, address, presets and aliases): it would be loaded exactly as it is. Any other
    instrument is not needed any more and is disconnected, which also frees its name for the new station.
    """
    keep, drop = [], []
    for name in loaded:
        entry = new_entries.get(name)
        (keep if entry is not None and entry == old_entries.get(name) else drop).append(name)
    return sorted(keep), sorted(drop)
