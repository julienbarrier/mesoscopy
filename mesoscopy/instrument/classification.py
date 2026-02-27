"""Instrument classification helpers (lock-in, SMU) for station components."""

LOCKIN_CLASS_NAMES = ('MFLI', 'HF2LI', 'SR830', 'SR860', 'SR865')
SMU_2CHANNEL_CLASS_NAMES = ('Keithley2600', 'Keithley_2600', 'Keithley2614B')
SMU_1CHANNEL_CLASS_NAMES = ('Keithley2450', 'Keithley2400', 'Keithley1450')


def is_lockin(instrument):
    """True if instrument is a lock-in (MFLI, HF2LI, SR830, SR860, SR865)."""
    name = instrument.__class__.__name__
    return any(t in name for t in LOCKIN_CLASS_NAMES)


def is_smu_2channel(instrument):
    """True if SMU has two channels (e.g. Keithley 2600: smua, smub)."""
    name = instrument.__class__.__name__
    return any(t in name for t in SMU_2CHANNEL_CLASS_NAMES)


def is_smu_1channel(instrument):
    """True if SMU has one channel (e.g. Keithley 2450)."""
    name = instrument.__class__.__name__
    return any(t in name for t in SMU_1CHANNEL_CLASS_NAMES)


def classify_loaded_instruments(station):
    """
    Classify loaded station components into lock-ins and SMU channels.
    Returns (lockin_names, smu_channel_list).
    smu_channel_list entries are display names like "inst.smua", "inst.smub", or "inst" for single-channel.
    """
    lockin_names = []
    smu_channel_list = []
    if not station or not hasattr(station, 'components'):
        return lockin_names, smu_channel_list
    for name, comp in station.components.items():
        if not hasattr(comp, '__class__'):
            continue
        if is_lockin(comp):
            lockin_names.append(name)
        elif is_smu_2channel(comp):
            smu_channel_list.append(f"{name}.smua")
            smu_channel_list.append(f"{name}.smub")
        elif is_smu_1channel(comp):
            smu_channel_list.append(name)
    return lockin_names, smu_channel_list
