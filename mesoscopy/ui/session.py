"""The fields whose entries are remembered between sessions."""


class SessionFields:
    """A registry of (key, getter, setter): ``capture`` reads every field into one JSON-compatible dict, ``restore``
    sets them again, in the order they were registered (a folder before the files it lists).

    A field that cannot be read or set is skipped: an old or damaged session must never stop the application.
    """

    def __init__(self):
        self._fields = {}

    def register(self, key, getter, setter):
        self._fields[key] = (getter, setter)

    def capture(self):
        data = {}
        for key, (getter, _) in self._fields.items():
            try:
                data[key] = getter()
            except Exception as e:
                print(f"Session: could not read {key}: {e}")
        return data

    def restore(self, data):
        """Set the fields from ``capture`` data. Returns the keys that could not be set."""
        failed = []
        for key, (_, setter) in self._fields.items():
            if key not in data:
                continue
            try:
                setter(data[key])
            except Exception as e:
                print(f"Session: could not restore {key}: {e}")
                failed.append(key)
        return failed
