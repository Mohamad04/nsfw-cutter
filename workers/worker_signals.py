from PySide6.QtCore import QObject, Signal


class WorkerSignals(QObject):
    progress = Signal(str, int, str)
    finished = Signal(str, object)
    error = Signal(str, str)
