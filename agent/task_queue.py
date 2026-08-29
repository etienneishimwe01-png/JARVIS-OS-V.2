import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Any
from memory.task_history import record_task
from agent.confirmation import ConfirmationManager, ConfirmationStatus


class TaskStatus(Enum):
    PENDING    = "pending"
    RUNNING    = "running"
    COMPLETED  = "completed"
    FAILED     = "failed"
    CANCELLED  = "cancelled"
    WAITING_CONFIRMATION = "waiting_confirmation"


class TaskPriority(Enum):
    LOW    = 3
    NORMAL = 2
    HIGH   = 1   


@dataclass(order=True)
class Task:
    priority:    int                       
    created_at:  float = field(compare=False)
    task_id:     str   = field(compare=False)
    goal:        str   = field(compare=False)
    status:      TaskStatus = field(compare=False, default=TaskStatus.PENDING)
    result:      Any        = field(compare=False, default=None)
    error:       str        = field(compare=False, default="")
    speak:       Any        = field(compare=False, default=None)   
    on_complete: Any        = field(compare=False, default=None)  
    on_cancel:   Any        = field(compare=False, default=None)
    runner:      Any        = field(compare=False, default=None)
    kind:        str        = field(compare=False, default="agent")
    progress:    int        = field(compare=False, default=0)
    phase:       str        = field(compare=False, default="Queued")
    artifacts:   list[str]  = field(compare=False, default_factory=list)
    warnings:    list[str]  = field(compare=False, default_factory=list)
    user_id:     str | None = field(compare=False, default=None)
    cancel_flag: threading.Event = field(compare=False, default_factory=threading.Event)
    resume_data: dict | None = field(compare=False, default=None)


class TaskQueue:
    def __init__(self, max_concurrent: int = 2, awareness=None):
        self._queue:        list[Task]       = []
        self._lock:         threading.Lock   = threading.Lock()
        self._condition:    threading.Condition = threading.Condition(self._lock)
        self._tasks:        dict[str, Task]  = {} 
        self._running:      bool             = False
        self._worker_thread: threading.Thread | None = None
        self._max_concurrent = max_concurrent
        self._active_count   = 0
        self._executor       = None
        self._awareness      = awareness
        self.confirmations  = ConfirmationManager()
        self.confirmations.add_listener(self._on_confirmation_resolved)

    def _get_executor(self):
        if self._executor is None:
            from agent.executor import AgentExecutor
            self._executor = AgentExecutor(awareness=self._awareness)
        return self._executor

    def start(self) -> None:
        if self._running:
            return
        self._running      = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="AgentTaskQueue"
        )
        self._worker_thread.start()
        print("[TaskQueue] ✅ Started")

    def stop(self) -> None:
        self._running = False
        with self._condition:
            self._condition.notify_all()
        print("[TaskQueue] 🔴 Stopped")

    def submit(
        self,
        goal:        str,
        priority:    TaskPriority = TaskPriority.NORMAL,
        speak:       Callable | None = None,
        on_complete: Callable | None = None,
        immediate:   bool = False,
    ) -> str:

        from core.tenant import get_current_user_id

        task_id = str(uuid.uuid4())[:8]
        task    = Task(
            priority    = priority.value,
            created_at  = time.time(),
            task_id     = task_id,
            goal        = goal,
            speak       = speak,
            on_complete = on_complete,
            user_id     = get_current_user_id(),
        )

        start_now = False
        with self._condition:
            self._queue.append(task)
            self._queue.sort(key=lambda t: (t.priority, t.created_at))
            self._tasks[task_id] = task
            if immediate and self._running and self._active_count < self._max_concurrent:
                task.status = TaskStatus.RUNNING
                task.phase = "Starting"
                self._active_count += 1
                self._queue.remove(task)
                start_now = True
            self._condition.notify()

        if start_now:
            threading.Thread(
                target=self._run_task,
                args=(task,),
                daemon=True,
                name=f"AgentTask-{task.task_id}",
            ).start()
            print(f"[TaskQueue] ⚡ Task started immediately: [{task_id}] {goal[:60]}")
        else:
            print(f"[TaskQueue] 📥 Task queued: [{task_id}] {goal[:60]}")
        return task_id

    def submit_job(
        self,
        goal: str,
        runner: Callable,
        priority: TaskPriority = TaskPriority.NORMAL,
        speak: Callable | None = None,
        on_complete: Callable | None = None,
        on_cancel: Callable | None = None,
        kind: str = "presentation",
    ) -> str:
        """Submit a specialized callable without routing it through AgentExecutor."""
        from core.tenant import get_current_user_id

        task_id = str(uuid.uuid4())[:8]
        task = Task(
            priority=priority.value,
            created_at=time.time(),
            task_id=task_id,
            goal=goal,
            speak=speak,
            on_complete=on_complete,
            on_cancel=on_cancel,
            runner=runner,
            kind=kind,
            user_id=get_current_user_id(),
        )
        with self._condition:
            self._queue.append(task)
            self._queue.sort(key=lambda item: (item.priority, item.created_at))
            self._tasks[task_id] = task
            self._condition.notify()
        print(f"[TaskQueue] 📥 {kind} job queued: [{task_id}] {goal[:60]}")
        return task_id

    def cancel(self, task_id: str) -> bool:
        on_cancel = None
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                return False

            task.cancel_flag.set()
            task.status = TaskStatus.CANCELLED
            task.phase = "Cancelled"
            on_cancel = task.on_cancel
            if task in self._queue:
                self._queue.remove(task)
            print(f"[TaskQueue] 🚫 Task cancelled: [{task_id}]")
        self.confirmations.cancel(task_id)
        if on_cancel:
            try:
                on_cancel()
            except Exception as exc:
                print(f"[TaskQueue] ⚠️ on_cancel callback error: {exc}")
        with self._condition:
            self._condition.notify_all()
        return True

    def approve(self, task_id: str) -> bool:
        request = self.confirmations.resolve(task_id, True)
        return bool(request and request.status == ConfirmationStatus.APPROVED)

    def deny(self, task_id: str) -> bool:
        request = self.confirmations.resolve(task_id, False)
        return bool(request and request.status == ConfirmationStatus.DENIED)

    def pending_confirmations(self):
        return self.confirmations.pending()

    def add_confirmation_listener(self, listener):
        self.confirmations.add_listener(listener)

    def _on_confirmation_resolved(self, request) -> None:
        if request.status == ConfirmationStatus.APPROVED:
            with self._condition:
                task = self._tasks.get(request.task_id)
                if not task or task.status != TaskStatus.WAITING_CONFIRMATION:
                    return
                resume_data = task.resume_data or {}
                resume_data["approved_confirmation"] = (
                    resume_data.get("step_index", 0), request.tool
                )
                task.resume_data = resume_data
                task.status = TaskStatus.RUNNING
                task.phase = "Resuming"
                self._active_count += 1
            threading.Thread(
                target=self._run_task,
                args=(task,),
                daemon=True,
                name=f"AgentTask-{task.task_id}-resume",
            ).start()
        elif request.status in {ConfirmationStatus.DENIED, ConfirmationStatus.EXPIRED, ConfirmationStatus.CANCELLED}:
            with self._lock:
                task = self._tasks.get(request.task_id)
                if not task or task.status != TaskStatus.WAITING_CONFIRMATION:
                    return
                task.status = TaskStatus.CANCELLED
                task.phase = "Cancelled"
                task.error = f"Confirmation {request.status.value}."
                task.resume_data = None
            if task.speak:
                task.speak("Understood. I cancelled that action.")


    def cancel_running(self, *args, **kwargs):
        return False


    def get_status(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return {
                "task_id": task.task_id,
                "goal":    task.goal,
                "status":  task.status.value,
                "result":  task.result,
                "error":   task.error,
                "kind": task.kind,
                "progress": task.progress,
                "phase": task.phase,
                "artifacts": list(task.artifacts),
                "warnings": list(task.warnings),
            }

    def get_all_statuses(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "task_id": t.task_id,
                    "goal":    t.goal[:50],
                    "status":  t.status.value,
                    "kind": t.kind,
                    "progress": t.progress,
                    "phase": t.phase,
                }
                for t in self._tasks.values()
            ]

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._queue if t.status == TaskStatus.PENDING)

    def _worker_loop(self) -> None:
        while self._running:
            task = None

            with self._condition:
                while self._running and not self._next_task():
                    self._condition.wait(timeout=1.0)
                task = self._next_task()
                if task:
                    task.status = TaskStatus.RUNNING
                    self._active_count += 1
                    try:
                        self._queue.remove(task)
                    except ValueError:
                        pass

            if task:
                threading.Thread(
                    target=self._run_task,
                    args=(task,),
                    daemon=True,
                    name=f"AgentTask-{task.task_id}"
                ).start()

    def _next_task(self) -> Task | None:
        if self._active_count >= self._max_concurrent:
            return None
        for task in self._queue:
            if task.status == TaskStatus.PENDING and not task.cancel_flag.is_set():
                return task
        return None

    def _run_task(self, task: Task) -> None:
        if task.user_id:
            from core.tenant import tenant_scope

            with tenant_scope(task.user_id):
                self._run_task_inner(task)
            return
        self._run_task_inner(task)

    def _run_task_inner(self, task: Task) -> None:
        print(f"[TaskQueue] ▶️ Running: [{task.task_id}] {task.goal[:60]}")
        try:
            def update_progress(
                percent: int | None = None,
                phase: str | None = None,
                artifacts: list[str] | None = None,
                warnings: list[str] | None = None,
            ) -> None:
                with self._lock:
                    if percent is not None:
                        task.progress = max(0, min(100, int(percent)))
                    if phase:
                        task.phase = str(phase)
                    if artifacts is not None:
                        task.artifacts = [str(item) for item in artifacts]
                    if warnings is not None:
                        task.warnings = [str(item) for item in warnings]

            if task.runner:
                update_progress(1, "Starting")
                raw_result = task.runner(task.cancel_flag, update_progress)
                task.result = str(raw_result)
                task.artifacts = list(getattr(raw_result, "artifacts", task.artifacts) or task.artifacts)
                task.warnings = list(getattr(raw_result, "warnings", task.warnings) or task.warnings)
                result = task.result
            else:
                executor = self._get_executor()
                resume = task.resume_data or {}
                task.resume_data = None
                result = executor.execute(
                    goal=task.goal,
                    speak=task.speak,
                    cancel_flag=task.cancel_flag,
                    plan=resume.get("plan"),
                    completed_steps=resume.get("completed_steps"),
                    step_results=resume.get("step_results"),
                    start_index=resume.get("step_index", 0),
                    approved_confirmation=resume.get("approved_confirmation"),
                )
                step_results = getattr(executor, "last_step_results", {}) or {}
                if step_results:
                    step_result_text = "\n".join(
                        f"Step {key}: {value}" for key, value in step_results.items()
                    )
                    task.result = f"{result}\n\nSTEP RESULTS:\n{step_result_text}"
                else:
                    task.result = result

            with self._lock:
                if task.cancel_flag.is_set():
                    task.status = TaskStatus.CANCELLED
                else:
                    task.status = TaskStatus.COMPLETED
                    task.result = task.result or result
                    task.progress = 100
                    task.phase = "Completed"
                self._active_count -= 1

            if task.on_complete and not task.cancel_flag.is_set():
                try:
                    task.on_complete(task.task_id, result)
                except Exception as e:
                    print(f"[TaskQueue] ⚠️ on_complete callback error: {e}")

            if not task.cancel_flag.is_set():
                completion_msg = (
                    str(task.result)[:500]
                    if task.kind in {"presentation", "research"} and task.result
                    else f"Task completed: {task.goal[:90]}"
                )

                # Push completion into awareness so UI/state knows it finished.
                if self._awareness and task.kind != "research":
                    try:
                        self._awareness.record_event(completion_msg)
                        self._awareness.clear_active_tool()
                    except Exception as e:
                        print(f"[TaskQueue] ⚠️ awareness completion update failed: {e}")

                # Tell the live assistant/user that the background task finished.
                if task.speak:
                    try:
                        task.speak(completion_msg)
                    except Exception as e:
                        print(f"[TaskQueue] ⚠️ speak completion notification failed: {e}")

            if task.kind != "research":
                try:
                    record_task(
                        task_id=task.task_id,
                        goal=task.goal,
                        status=task.status.value,
                        result=task.result,
                        error=task.error,
                    )
                except Exception as e:
                    print(f"[TaskQueue] ⚠️ task history save failed: {e}")

            print(f"[TaskQueue] ✅ Completed: [{task.task_id}]")

        except Exception as e:
            with self._lock:
                cancelled = task.cancel_flag.is_set()
                waiting_confirmation = e.__class__.__name__ == "ConfirmationRequired"
                if waiting_confirmation:
                    task.resume_data = {
                        "plan": getattr(e, "plan", None),
                        "completed_steps": getattr(e, "completed_steps", []),
                        "step_results": getattr(e, "step_results", {}),
                        "step_index": getattr(e, "step_index", 0),
                        "approved_confirmation": None,
                    }
                task.status = (
                    TaskStatus.CANCELLED if cancelled
                    else TaskStatus.WAITING_CONFIRMATION if waiting_confirmation
                    else TaskStatus.FAILED
                )
                task.error = "" if cancelled else str(e)
                task.phase = (
                    "Cancelled" if cancelled
                    else "Waiting for confirmation" if waiting_confirmation
                    else "Failed"
                )
                self._active_count -= 1

            if waiting_confirmation:
                request = self.confirmations.request(
                    task_id=task.task_id,
                    tool=getattr(e, "step", {}).get("tool", "unknown"),
                    explanation=getattr(e, "step", {}).get("description", str(e)),
                    risk="medium",
                    parameters=getattr(e, "step", {}).get("parameters", {}),
                )
                if task.speak:
                    task.speak(
                        f"Confirmation required for {request.tool}. "
                        f"{request.explanation} Say yes to approve or no to cancel."
                    )

            failure_msg = (
                f"Task cancelled: {task.goal[:90]}"
                if cancelled else f"Task failed: {task.goal[:90]} — {e}"
            )

            if self._awareness and task.kind != "research" and not waiting_confirmation:
                try:
                    self._awareness.record_event(failure_msg)
                    self._awareness.clear_active_tool()
                except Exception as ae:
                    print(f"[TaskQueue] ⚠️ awareness failure update failed: {ae}")

            if task.speak and not cancelled and not waiting_confirmation:
                try:
                    task.speak(failure_msg)
                except Exception as se:
                    print(f"[TaskQueue] ⚠️ speak failure notification failed: {se}")

            if task.kind != "research" and not waiting_confirmation:
                try:
                    record_task(
                        task_id=task.task_id,
                        goal=task.goal,
                        status=task.status.value,
                        result=task.result,
                        error=task.error,
                    )
                except Exception as he:
                    print(f"[TaskQueue] ⚠️ task history save failed: {he}")

            if cancelled:
                print(f"[TaskQueue] 🚫 Cancelled: [{task.task_id}]")
            elif waiting_confirmation:
                print(f"[TaskQueue] ⏸️ Waiting for confirmation: [{task.task_id}]")
            else:
                print(f"[TaskQueue] ❌ Failed: [{task.task_id}] {e}")

        with self._condition:
            self._condition.notify()

_queue        = TaskQueue(max_concurrent=2)
_queue_started = False
_queue_lock    = threading.Lock()


def get_queue(awareness=None) -> TaskQueue:
    global _queue, _queue_started

    with _queue_lock:
        if awareness is not None and getattr(_queue, "_awareness", None) is None:
            _queue = TaskQueue(max_concurrent=2, awareness=awareness)
            _queue_started = False

        if not _queue_started:
            _queue.start()
            _queue_started = True

    return _queue
