"""Keep the application alive when something unexpected goes wrong in a Qt slot."""
import sys
import traceback


def install_exception_hook(window=None):
    """Report uncaught exceptions instead of letting them abort the process.

    PyQt6 calls ``qFatal`` (the process aborts) when a Qt slot raises and ``sys.excepthook`` is the
    default one. This hook prints the traceback to the console and shows a short message in the
    status bar of ``window``; the application keeps running.
    """
    default_hook = sys.excepthook

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            default_hook(exc_type, exc, tb)
            return
        traceback.print_exception(exc_type, exc, tb)
        if window is not None:
            try:
                window.statusBar().showMessage(
                    f"Unexpected error: {exc_type.__name__}: {exc} (details in the console)", 15000
                )
            except Exception:
                pass

    sys.excepthook = hook
