from __future__ import annotations

import logging

from PySide6.QtCore import QRunnable, Slot

from services.analysis.cancellation import CancellationToken
from services.analysis.model_provisioning import (
    ModelProvisioningCancelled,
    ModelProvisioningError,
    ProductionModelProvisioner,
)
from workers.worker_signals import WorkerSignals

logger = logging.getLogger(__name__)


class ModelProvisioningWorker(QRunnable):
    CHECK = "check"
    PROVISION = "provision"
    OPERATIONS = frozenset({CHECK, PROVISION})

    def __init__(
        self,
        job_token: str,
        operation: str,
        cancellation: CancellationToken | None = None,
        provisioner: ProductionModelProvisioner | None = None,
    ) -> None:
        super().__init__()
        if operation not in self.OPERATIONS:
            raise ValueError(f"Unsupported model provisioning operation: {operation}")
        self.setAutoDelete(True)
        self.job_token = job_token
        self.operation = operation
        self.cancellation = cancellation or CancellationToken()
        self.provisioner = provisioner or ProductionModelProvisioner()
        self.signals = WorkerSignals()

    def cancel(self) -> None:
        self.cancellation.cancel()

    @Slot()
    def run(self) -> None:
        try:
            if self.operation == self.CHECK:
                result = self.provisioner.check_all_models()
            else:
                provisioned = self.provisioner.provision_all(
                    progress_callback=self._emit_event,
                    cancellation_check=lambda: self.cancellation.is_cancelled,
                )
                if self.cancellation.is_cancelled:
                    raise ModelProvisioningCancelled(
                        "Model provisioning was cancelled. Partial cache data was preserved."
                    )
                # Revalidate the immutable snapshots locally before the controller
                # is allowed to expose Analyze again.
                result = self.provisioner.check_all_models()
                if self.cancellation.is_cancelled:
                    raise ModelProvisioningCancelled(
                        "Model provisioning was cancelled. Partial cache data was preserved."
                    )
                if not provisioned.success or not all(item.ready for item in result):
                    raise ModelProvisioningError(
                        "Production model provisioning completed, but local validation failed. "
                        "Retry model setup to reuse downloaded data."
                    )
            if self.operation == self.PROVISION and self.cancellation.is_cancelled:
                raise ModelProvisioningCancelled(
                    "Model provisioning was cancelled. Partial cache data was preserved."
                )
            self._emit_finished(result)
        except ModelProvisioningCancelled as exc:
            self._emit_cancelled(str(exc))
        except Exception as exc:
            logger.exception("Production model setup worker failed")
            self._emit_error(str(exc))

    def _emit_event(self, event) -> None:
        try:
            self.signals.modelProvisioningEvent.emit(self.job_token, event)
        except RuntimeError:
            logger.info("Dropping model setup progress after Qt shutdown")

    def _emit_finished(self, result) -> None:
        try:
            self.signals.finished.emit(self.job_token, result)
        except RuntimeError:
            logger.info("Dropping model setup result after Qt shutdown")

    def _emit_cancelled(self, message: str) -> None:
        try:
            self.signals.cancelled.emit(self.job_token, message)
        except RuntimeError:
            logger.info("Dropping model setup cancellation after Qt shutdown")

    def _emit_error(self, message: str) -> None:
        try:
            self.signals.error.emit(self.job_token, message)
        except RuntimeError:
            logger.info("Dropping model setup failure after Qt shutdown")
