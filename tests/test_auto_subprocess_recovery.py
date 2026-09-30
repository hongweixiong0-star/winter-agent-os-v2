from types import SimpleNamespace
from unittest.mock import Mock

from tools import control_panel as panel
from winter_agent_v2.runtime_snapshot import RuntimeSnapshotStore


def test_child_traceback_preserves_the_actual_exception():
    output = ('[role] B\nTraceback (most recent call last):\n'
              '  File "runtime.py", line 7302, in run\n'
              "AttributeError: 'LiveRuntime' object has no attribute '_training_continuation_goal'\n"
              'product: MuMuPlayer-12.0-0\n')
    failure = panel.worker_result_failure(output, 1)
    assert failure['message'].startswith('AttributeError:')
    assert failure['classification'] == 'WORKER_CRASH'
    assert 'line 7302' in failure['child_traceback']
    assert 'product:' not in failure['child_traceback']


def test_environment_loss_and_missing_result_are_distinct():
    failure = panel.worker_result_failure(
        'Traceback (most recent call last):\nRuntimeError: DEVICE_NOT_CONNECTED\n', 1)
    assert failure['classification'] == 'ENVIRONMENT'
    assert panel.worker_result_failure('', 0)['message'] == 'WORKER_RESULT_MISSING: exit=0'
    assert panel.worker_result_failure('', panel.WORKER_ABANDONED_CODE)['message'].startswith('WORKER_TIMEOUT:')


def harness(tmp_path):
    store = RuntimeSnapshotStore(tmp_path / 'snapshot.json')
    fake = SimpleNamespace(
        runtime_store=store, stop_requested=False, paused=False,
        continuous=SimpleNamespace(get=lambda: True), values={
            k: Mock() for k in panel.status_defaults()}, root=Mock(), start=Mock(),
        _append=Mock(), _idle_buttons=Mock(), _clear_running_task_labels=Mock(),
        _waiting_buttons=Mock(),
    )
    fake._handle_worker_failure = lambda data: panel.ControlPanel._handle_worker_failure(fake, data)
    return fake


def test_real_complete_path_reports_and_restarts_a_crashed_child(tmp_path, monkeypatch):
    fake = harness(tmp_path)
    monkeypatch.setattr(panel, 'CRASH_ROOT', tmp_path / 'crashes')
    panel.ControlPanel._apply_complete(fake, 1, {},
        'Traceback (most recent call last):\nAttributeError: retired field\n')
    assert fake.runtime_store.read().stop_reason == 'AttributeError: retired field'
    assert fake.runtime_store.read().unexpected_worker_exits == 1
    fake.root.after.assert_called_once_with(5000, fake.start)
    reports = list((tmp_path / 'crashes').glob('*.json'))
    assert len(reports) == 1
    assert 'AttributeError: retired field' in reports[0].read_text(encoding='utf-8')


def test_repeated_crash_opens_a_persistent_circuit_instead_of_restarting_forever(tmp_path, monkeypatch):
    fake = harness(tmp_path)
    state = tmp_path / 'panel.json'
    monkeypatch.setattr(panel, 'PANEL_STATE_PATH', state)
    for _ in range(4):
        fake._handle_worker_failure({'message': 'AttributeError: repeated', 'classification': 'WORKER_CRASH'})
    assert [call.args[0] for call in fake.root.after.call_args_list] == [5000, 10000, 20000]
    assert fake.paused is True
    assert panel.load_operator_intent(state) == 'PAUSED'
    assert fake.runtime_store.read().watchdog_restart_count == 3


def test_operator_pause_never_schedules_a_restart(tmp_path):
    fake = harness(tmp_path)
    fake.paused = True
    fake._handle_worker_failure({'message': 'AttributeError: retired', 'classification': 'WORKER_CRASH'})
    fake.root.after.assert_not_called()
