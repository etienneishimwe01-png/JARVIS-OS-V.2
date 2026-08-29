import unittest
import threading

from agent.confirmation import ConfirmationManager, ConfirmationStatus
from agent.registry import ConfirmationRequired
from agent.task_queue import TaskQueue, TaskStatus


class ConfirmationManagerTests(unittest.TestCase):
    def test_duplicate_requests_return_one_pending_request(self):
        manager = ConfirmationManager(timeout_seconds=5)
        first = manager.request("TASK-1", "file_controller", "Modify a file", "medium")
        second = manager.request("TASK-1", "file_controller", "Modify a file", "medium")
        self.assertIs(first, second)
        self.assertEqual(len(manager.pending()), 1)

    def test_approval_and_denial_are_terminal(self):
        manager = ConfirmationManager(timeout_seconds=5)
        manager.request("TASK-1", "send_message", "Send a message", "medium")
        self.assertEqual(manager.resolve("TASK-1", True).status, ConfirmationStatus.APPROVED)
        self.assertEqual(manager.resolve("TASK-1", False).status, ConfirmationStatus.APPROVED)

    def test_expiration_fails_closed(self):
        manager = ConfirmationManager(timeout_seconds=1)
        manager.request("TASK-1", "file_controller", "Modify a file", "medium")
        manager.expire("TASK-1")
        self.assertEqual(manager.get("TASK-1").status, ConfirmationStatus.EXPIRED)

    def test_sensitive_values_are_redacted(self):
        manager = ConfirmationManager(timeout_seconds=5)
        request = manager.request("TASK-1", "email_control", "Send email", "medium", {
            "api_key": "secret", "body": "x" * 300,
        })
        self.assertEqual(request.parameters["api_key"], "[redacted]")
        self.assertTrue(request.parameters["body"].endswith("..."))


class ConfirmationQueueTests(unittest.TestCase):
    def _queue_with_executor(self, calls):
        queue = TaskQueue(max_concurrent=1)

        class FakeExecutor:
            def execute(self, **kwargs):
                calls.append(kwargs)
                if kwargs.get("approved_confirmation") is None:
                    error = ConfirmationRequired("approval needed")
                    error.plan = {"steps": [{"step": 1, "tool": "file_controller", "description": "Write file", "parameters": {"action": "write"}}]}
                    error.completed_steps = []
                    error.step_results = {}
                    error.step_index = 0
                    error.step = error.plan["steps"][0]
                    raise error
                return "verified result"

        queue._get_executor = lambda: FakeExecutor()
        return queue

    def test_approval_resumes_same_task_and_original_step(self):
        calls = []
        queue = self._queue_with_executor(calls)
        task_id = queue.submit("Write file")
        task = queue._tasks[task_id]
        task.status = TaskStatus.RUNNING
        queue._active_count = 1
        queue._run_task(task)
        self.assertEqual(queue.get_status(task_id)["status"], "waiting_confirmation")
        self.assertTrue(queue.approve(task_id))
        for _ in range(20):
            if queue.get_status(task_id)["status"] == "completed":
                break
            threading.Event().wait(0.01)
        self.assertEqual(queue.get_status(task_id)["status"], "completed")
        self.assertEqual(calls[-1]["approved_confirmation"], (0, "file_controller"))

    def test_denial_cancels_without_resuming(self):
        calls = []
        queue = self._queue_with_executor(calls)
        task_id = queue.submit("Write file")
        task = queue._tasks[task_id]
        task.status = TaskStatus.RUNNING
        queue._active_count = 1
        queue._run_task(task)
        self.assertTrue(queue.deny(task_id))
        self.assertEqual(queue.get_status(task_id)["status"], "cancelled")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()