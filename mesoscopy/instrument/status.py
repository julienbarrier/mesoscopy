"""Instrument identity and health helpers (no Qt)."""

IDN_FIELDS = ("vendor", "model", "serial", "firmware")


def get_identity(instrument):
    """
    Query ``instrument.get_idn()`` and return a dict of strings with the keys
    vendor, model, serial, firmware. Raises if the instrument does not answer,
    which is what makes this usable as a health check.
    """
    idn = instrument.get_idn()
    identity = {key: "" if idn.get(key) is None else str(idn.get(key)) for key in IDN_FIELDS}
    if not identity["model"] or identity["model"].startswith("<class"):
        identity["model"] = type(instrument).__name__
    return identity
