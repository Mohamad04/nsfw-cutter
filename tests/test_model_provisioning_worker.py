import unittest

from services.analysis.cancellation import CancellationToken
from services.analysis.model_provisioning import (
    PRODUCTION_MODELS,
    ModelProvisioningCancelled,
    ModelReadiness,
    ProvisioningProgress,
    ProvisioningResult,
    ProvisioningState,
    ReadinessState,
)
from workers.model_provisioning_worker import ModelProvisioningWorker


def ready_models():
    return tuple(
        ModelReadiness(
            spec=spec,
            state=ReadinessState.READY,
            reason=f"{spec.repo_id} is ready",
        )
        for spec in PRODUCTION_MODELS
    )


class FakeProvisioner:
    def __init__(self):
        self.readiness = ready_models()
        self.check_calls = 0
        self.provision_calls = 0
        self.failure = None

    def check_all_models(self):
        self.check_calls += 1
        if self.failure is not None:
            raise self.failure
        return self.readiness

    def provision_all(self, *, progress_callback, cancellation_check):
        self.provision_calls += 1
        if cancellation_check():
            raise ModelProvisioningCancelled("cancelled between components")
        progress_callback(
            ProvisioningProgress(
                component=PRODUCTION_MODELS[0].component,
                state=ProvisioningState.READY,
                message="Safety prefilter is ready",
                completed_components=1,
                total_components=3,
                overall_fraction=1 / 3,
            )
        )
        return ProvisioningResult(models=self.readiness)


class CancellingReadiness:
    def __init__(self, cancellation):
        self.cancellation = cancellation

    @property
    def ready(self):
        self.cancellation.cancel()
        return True


class ModelProvisioningWorkerTests(unittest.TestCase):
    def test_readiness_check_emits_local_result(self):
        provisioner = FakeProvisioner()
        worker = ModelProvisioningWorker(
            job_token="check-job",
            operation=ModelProvisioningWorker.CHECK,
            provisioner=provisioner,
        )
        finished = []
        worker.signals.finished.connect(lambda token, result: finished.append((token, result)))

        worker.run()

        self.assertEqual(finished, [("check-job", ready_models())])
        self.assertEqual(provisioner.check_calls, 1)
        self.assertEqual(provisioner.provision_calls, 0)

    def test_provisioning_forwards_backend_event_and_revalidates(self):
        provisioner = FakeProvisioner()
        worker = ModelProvisioningWorker(
            job_token="provision-job",
            operation=ModelProvisioningWorker.PROVISION,
            provisioner=provisioner,
        )
        events = []
        finished = []
        worker.signals.modelProvisioningEvent.connect(
            lambda token, event: events.append((token, event))
        )
        worker.signals.finished.connect(lambda token, result: finished.append((token, result)))

        worker.run()

        self.assertEqual(provisioner.provision_calls, 1)
        self.assertEqual(provisioner.check_calls, 1)
        self.assertEqual(events[0][0], "provision-job")
        self.assertEqual(events[0][1].state, ProvisioningState.READY)
        self.assertEqual(finished, [("provision-job", ready_models())])

    def test_confirmed_cancellation_uses_cancelled_signal_not_success(self):
        provisioner = FakeProvisioner()
        cancellation = CancellationToken()
        cancellation.cancel()
        worker = ModelProvisioningWorker(
            job_token="cancel-job",
            operation=ModelProvisioningWorker.PROVISION,
            cancellation=cancellation,
            provisioner=provisioner,
        )
        cancelled = []
        finished = []
        worker.signals.cancelled.connect(
            lambda token, message: cancelled.append((token, message))
        )
        worker.signals.finished.connect(lambda token, result: finished.append((token, result)))

        worker.run()

        self.assertEqual(cancelled[0][0], "cancel-job")
        self.assertIn("cancelled", cancelled[0][1])
        self.assertEqual(finished, [])

    def test_token_cancelled_immediately_before_finished_prevents_success(self):
        provisioner = FakeProvisioner()
        cancellation = CancellationToken()
        provisioner.readiness = tuple(
            CancellingReadiness(cancellation) for _spec in PRODUCTION_MODELS
        )
        worker = ModelProvisioningWorker(
            job_token="final-cancel-job",
            operation=ModelProvisioningWorker.PROVISION,
            cancellation=cancellation,
            provisioner=provisioner,
        )
        cancelled = []
        finished = []
        worker.signals.cancelled.connect(
            lambda token, message: cancelled.append((token, message))
        )
        worker.signals.finished.connect(lambda token, result: finished.append((token, result)))

        worker.run()

        self.assertEqual(cancelled[0][0], "final-cancel-job")
        self.assertEqual(finished, [])

    def test_worker_reports_errors_without_success(self):
        provisioner = FakeProvisioner()
        provisioner.failure = RuntimeError("cache unreadable")
        worker = ModelProvisioningWorker(
            job_token="error-job",
            operation=ModelProvisioningWorker.CHECK,
            provisioner=provisioner,
        )
        errors = []
        finished = []
        worker.signals.error.connect(lambda token, message: errors.append((token, message)))
        worker.signals.finished.connect(lambda token, result: finished.append((token, result)))

        worker.run()

        self.assertEqual(errors, [("error-job", "cache unreadable")])
        self.assertEqual(finished, [])


if __name__ == "__main__":
    unittest.main()
