from PySide6.QtCore import QObject, Signal


class WorkerSignals(QObject):
    progress = Signal(str, int, str)
    analysisEvent = Signal(str, object)
    modelProvisioningEvent = Signal(str, object)
    cancelled = Signal(str, str)
    finished = Signal(str, object)
    error = Signal(str, str)
