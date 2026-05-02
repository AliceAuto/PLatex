from __future__ import annotations

import threading
import unittest

from platex_client.app_state import AppState, StateMachine, _VALID_TRANSITIONS
from platex_client.events import AppStateChangedEvent, EventBus, reset_event_bus


class TestAppStateEnum(unittest.TestCase):
    def test_all_states_exist(self):
        expected = {"IDLE", "STARTING", "RUNNING", "PAUSED", "STOPPING", "STOPPED"}
        actual = {s.name for s in AppState}
        self.assertEqual(actual, expected)

    def test_states_are_unique(self):
        values = [s.value for s in AppState]
        self.assertEqual(len(values), len(set(values)))


class TestValidTransitions(unittest.TestCase):
    def test_all_states_have_transition_entries(self):
        for state in AppState:
            self.assertIn(state, _VALID_TRANSITIONS)

    def test_idle_transitions(self):
        self.assertEqual(_VALID_TRANSITIONS[AppState.IDLE], {AppState.STARTING})

    def test_starting_transitions(self):
        self.assertEqual(_VALID_TRANSITIONS[AppState.STARTING], {AppState.RUNNING, AppState.STOPPED})

    def test_running_transitions(self):
        self.assertEqual(_VALID_TRANSITIONS[AppState.RUNNING], {AppState.PAUSED, AppState.STOPPING})

    def test_paused_transitions(self):
        self.assertEqual(_VALID_TRANSITIONS[AppState.PAUSED], {AppState.RUNNING, AppState.STOPPING})

    def test_stopping_transitions(self):
        self.assertEqual(_VALID_TRANSITIONS[AppState.STOPPING], {AppState.STOPPED, AppState.IDLE})

    def test_stopped_transitions(self):
        self.assertEqual(_VALID_TRANSITIONS[AppState.STOPPED], {AppState.IDLE, AppState.STARTING})


class TestStateMachineValidTransitions(unittest.TestCase):
    """Test all valid state transitions return True and update state."""

    def setUp(self):
        reset_event_bus()
        self.sm = StateMachine()

    def tearDown(self):
        reset_event_bus()

    def test_idle_to_starting(self):
        self.assertTrue(self.sm.transition_to(AppState.STARTING))
        self.assertEqual(self.sm.state, AppState.STARTING)

    def test_starting_to_running(self):
        self.sm.transition_to(AppState.STARTING)
        self.assertTrue(self.sm.transition_to(AppState.RUNNING))
        self.assertEqual(self.sm.state, AppState.RUNNING)

    def test_starting_to_stopped(self):
        self.sm.transition_to(AppState.STARTING)
        self.assertTrue(self.sm.transition_to(AppState.STOPPED))
        self.assertEqual(self.sm.state, AppState.STOPPED)

    def test_running_to_paused(self):
        self.sm.transition_to(AppState.STARTING)
        self.sm.transition_to(AppState.RUNNING)
        self.assertTrue(self.sm.transition_to(AppState.PAUSED))
        self.assertEqual(self.sm.state, AppState.PAUSED)

    def test_running_to_stopping(self):
        self.sm.transition_to(AppState.STARTING)
        self.sm.transition_to(AppState.RUNNING)
        self.assertTrue(self.sm.transition_to(AppState.STOPPING))
        self.assertEqual(self.sm.state, AppState.STOPPING)

    def test_paused_to_running(self):
        self.sm.transition_to(AppState.STARTING)
        self.sm.transition_to(AppState.RUNNING)
        self.sm.transition_to(AppState.PAUSED)
        self.assertTrue(self.sm.transition_to(AppState.RUNNING))
        self.assertEqual(self.sm.state, AppState.RUNNING)

    def test_paused_to_stopping(self):
        self.sm.transition_to(AppState.STARTING)
        self.sm.transition_to(AppState.RUNNING)
        self.sm.transition_to(AppState.PAUSED)
        self.assertTrue(self.sm.transition_to(AppState.STOPPING))
        self.assertEqual(self.sm.state, AppState.STOPPING)

    def test_stopping_to_stopped(self):
        self.sm.transition_to(AppState.STARTING)
        self.sm.transition_to(AppState.RUNNING)
        self.sm.transition_to(AppState.STOPPING)
        self.assertTrue(self.sm.transition_to(AppState.STOPPED))
        self.assertEqual(self.sm.state, AppState.STOPPED)

    def test_stopping_to_idle(self):
        self.sm.transition_to(AppState.STARTING)
        self.sm.transition_to(AppState.RUNNING)
        self.sm.transition_to(AppState.STOPPING)
        self.assertTrue(self.sm.transition_to(AppState.IDLE))
        self.assertEqual(self.sm.state, AppState.IDLE)

    def test_stopped_to_starting(self):
        self.sm.transition_to(AppState.STARTING)
        self.sm.transition_to(AppState.STOPPED)
        self.assertTrue(self.sm.transition_to(AppState.STARTING))
        self.assertEqual(self.sm.state, AppState.STARTING)

    def test_stopped_to_idle(self):
        self.sm.transition_to(AppState.STARTING)
        self.sm.transition_to(AppState.STOPPED)
        self.assertTrue(self.sm.transition_to(AppState.IDLE))
        self.assertEqual(self.sm.state, AppState.IDLE)


class TestStateMachineInvalidTransitions(unittest.TestCase):
    """Test all invalid state transitions return False and do not change state."""

    def setUp(self):
        reset_event_bus()
        self.sm = StateMachine()

    def tearDown(self):
        reset_event_bus()

    def _force_state(self, state: AppState) -> None:
        """Helper to put the machine into a specific state for testing."""
        self.sm.force_state(state)

    def test_idle_to_running_invalid(self):
        self.assertFalse(self.sm.transition_to(AppState.RUNNING))
        self.assertEqual(self.sm.state, AppState.IDLE)

    def test_idle_to_paused_invalid(self):
        self.assertFalse(self.sm.transition_to(AppState.PAUSED))
        self.assertEqual(self.sm.state, AppState.IDLE)

    def test_idle_to_stopping_invalid(self):
        self.assertFalse(self.sm.transition_to(AppState.STOPPING))
        self.assertEqual(self.sm.state, AppState.IDLE)

    def test_idle_to_stopped_invalid(self):
        self.assertFalse(self.sm.transition_to(AppState.STOPPED))
        self.assertEqual(self.sm.state, AppState.IDLE)

    def test_idle_to_self_invalid(self):
        self.assertFalse(self.sm.transition_to(AppState.IDLE))
        self.assertEqual(self.sm.state, AppState.IDLE)

    def test_starting_to_idle_invalid(self):
        self._force_state(AppState.STARTING)
        self.assertFalse(self.sm.transition_to(AppState.IDLE))
        self.assertEqual(self.sm.state, AppState.STARTING)

    def test_starting_to_paused_invalid(self):
        self._force_state(AppState.STARTING)
        self.assertFalse(self.sm.transition_to(AppState.PAUSED))
        self.assertEqual(self.sm.state, AppState.STARTING)

    def test_starting_to_stopping_invalid(self):
        self._force_state(AppState.STARTING)
        self.assertFalse(self.sm.transition_to(AppState.STOPPING))
        self.assertEqual(self.sm.state, AppState.STARTING)

    def test_starting_to_self_invalid(self):
        self._force_state(AppState.STARTING)
        self.assertFalse(self.sm.transition_to(AppState.STARTING))
        self.assertEqual(self.sm.state, AppState.STARTING)

    def test_running_to_idle_invalid(self):
        self._force_state(AppState.RUNNING)
        self.assertFalse(self.sm.transition_to(AppState.IDLE))
        self.assertEqual(self.sm.state, AppState.RUNNING)

    def test_running_to_starting_invalid(self):
        self._force_state(AppState.RUNNING)
        self.assertFalse(self.sm.transition_to(AppState.STARTING))
        self.assertEqual(self.sm.state, AppState.RUNNING)

    def test_running_to_stopped_invalid(self):
        self._force_state(AppState.RUNNING)
        self.assertFalse(self.sm.transition_to(AppState.STOPPED))
        self.assertEqual(self.sm.state, AppState.RUNNING)

    def test_running_to_self_invalid(self):
        self._force_state(AppState.RUNNING)
        self.assertFalse(self.sm.transition_to(AppState.RUNNING))
        self.assertEqual(self.sm.state, AppState.RUNNING)

    def test_paused_to_idle_invalid(self):
        self._force_state(AppState.PAUSED)
        self.assertFalse(self.sm.transition_to(AppState.IDLE))
        self.assertEqual(self.sm.state, AppState.PAUSED)

    def test_paused_to_starting_invalid(self):
        self._force_state(AppState.PAUSED)
        self.assertFalse(self.sm.transition_to(AppState.STARTING))
        self.assertEqual(self.sm.state, AppState.PAUSED)

    def test_paused_to_stopped_invalid(self):
        self._force_state(AppState.PAUSED)
        self.assertFalse(self.sm.transition_to(AppState.STOPPED))
        self.assertEqual(self.sm.state, AppState.PAUSED)

    def test_paused_to_self_invalid(self):
        self._force_state(AppState.PAUSED)
        self.assertFalse(self.sm.transition_to(AppState.PAUSED))
        self.assertEqual(self.sm.state, AppState.PAUSED)

    def test_stopping_to_starting_invalid(self):
        self._force_state(AppState.STOPPING)
        self.assertFalse(self.sm.transition_to(AppState.STARTING))
        self.assertEqual(self.sm.state, AppState.STOPPING)

    def test_stopping_to_running_invalid(self):
        self._force_state(AppState.STOPPING)
        self.assertFalse(self.sm.transition_to(AppState.RUNNING))
        self.assertEqual(self.sm.state, AppState.STOPPING)

    def test_stopping_to_paused_invalid(self):
        self._force_state(AppState.STOPPING)
        self.assertFalse(self.sm.transition_to(AppState.PAUSED))
        self.assertEqual(self.sm.state, AppState.STOPPING)

    def test_stopping_to_self_invalid(self):
        self._force_state(AppState.STOPPING)
        self.assertFalse(self.sm.transition_to(AppState.STOPPING))
        self.assertEqual(self.sm.state, AppState.STOPPING)

    def test_stopped_to_running_invalid(self):
        self._force_state(AppState.STOPPED)
        self.assertFalse(self.sm.transition_to(AppState.RUNNING))
        self.assertEqual(self.sm.state, AppState.STOPPED)

    def test_stopped_to_paused_invalid(self):
        self._force_state(AppState.STOPPED)
        self.assertFalse(self.sm.transition_to(AppState.PAUSED))
        self.assertEqual(self.sm.state, AppState.STOPPED)

    def test_stopped_to_stopping_invalid(self):
        self._force_state(AppState.STOPPED)
        self.assertFalse(self.sm.transition_to(AppState.STOPPING))
        self.assertEqual(self.sm.state, AppState.STOPPED)

    def test_stopped_to_self_invalid(self):
        self._force_state(AppState.STOPPED)
        self.assertFalse(self.sm.transition_to(AppState.STOPPED))
        self.assertEqual(self.sm.state, AppState.STOPPED)


class TestStateMachineProperties(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        self.sm = StateMachine()

    def tearDown(self):
        reset_event_bus()

    def test_initial_state_is_idle(self):
        self.assertEqual(self.sm.state, AppState.IDLE)

    def test_is_running_false_initially(self):
        self.assertFalse(self.sm.is_running)

    def test_is_stopped_true_when_idle(self):
        self.assertTrue(self.sm.is_stopped)

    def test_is_running_true_when_running(self):
        self.sm.force_state(AppState.RUNNING)
        self.assertTrue(self.sm.is_running)

    def test_is_running_false_when_paused(self):
        self.sm.force_state(AppState.PAUSED)
        self.assertFalse(self.sm.is_running)

    def test_is_stopped_true_when_stopped(self):
        self.sm.force_state(AppState.STOPPED)
        self.assertTrue(self.sm.is_stopped)

    def test_is_stopped_false_when_starting(self):
        self.sm.force_state(AppState.STARTING)
        self.assertFalse(self.sm.is_stopped)

    def test_is_stopped_false_when_running(self):
        self.sm.force_state(AppState.RUNNING)
        self.assertFalse(self.sm.is_stopped)

    def test_is_stopped_false_when_paused(self):
        self.sm.force_state(AppState.PAUSED)
        self.assertFalse(self.sm.is_stopped)

    def test_is_stopped_false_when_stopping(self):
        self.sm.force_state(AppState.STOPPING)
        self.assertFalse(self.sm.is_stopped)


class TestCanTransitionTo(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        self.sm = StateMachine()

    def tearDown(self):
        reset_event_bus()

    def test_can_transition_from_idle_to_starting(self):
        self.assertTrue(self.sm.can_transition_to(AppState.STARTING))

    def test_cannot_transition_from_idle_to_running(self):
        self.assertFalse(self.sm.can_transition_to(AppState.RUNNING))

    def test_can_transition_from_starting_to_running(self):
        self.sm.force_state(AppState.STARTING)
        self.assertTrue(self.sm.can_transition_to(AppState.RUNNING))

    def test_can_transition_from_starting_to_stopped(self):
        self.sm.force_state(AppState.STARTING)
        self.assertTrue(self.sm.can_transition_to(AppState.STOPPED))

    def test_cannot_transition_from_starting_to_idle(self):
        self.sm.force_state(AppState.STARTING)
        self.assertFalse(self.sm.can_transition_to(AppState.IDLE))

    def test_can_transition_from_running_to_paused(self):
        self.sm.force_state(AppState.RUNNING)
        self.assertTrue(self.sm.can_transition_to(AppState.PAUSED))

    def test_can_transition_from_running_to_stopping(self):
        self.sm.force_state(AppState.RUNNING)
        self.assertTrue(self.sm.can_transition_to(AppState.STOPPING))

    def test_cannot_transition_from_running_to_idle(self):
        self.sm.force_state(AppState.RUNNING)
        self.assertFalse(self.sm.can_transition_to(AppState.IDLE))

    def test_can_transition_from_paused_to_running(self):
        self.sm.force_state(AppState.PAUSED)
        self.assertTrue(self.sm.can_transition_to(AppState.RUNNING))

    def test_can_transition_from_paused_to_stopping(self):
        self.sm.force_state(AppState.PAUSED)
        self.assertTrue(self.sm.can_transition_to(AppState.STOPPING))

    def test_can_transition_from_stopping_to_stopped(self):
        self.sm.force_state(AppState.STOPPING)
        self.assertTrue(self.sm.can_transition_to(AppState.STOPPED))

    def test_can_transition_from_stopping_to_idle(self):
        self.sm.force_state(AppState.STOPPING)
        self.assertTrue(self.sm.can_transition_to(AppState.IDLE))

    def test_can_transition_from_stopped_to_starting(self):
        self.sm.force_state(AppState.STOPPED)
        self.assertTrue(self.sm.can_transition_to(AppState.STARTING))

    def test_can_transition_from_stopped_to_idle(self):
        self.sm.force_state(AppState.STOPPED)
        self.assertTrue(self.sm.can_transition_to(AppState.IDLE))

    def test_cannot_transition_from_stopped_to_running(self):
        self.sm.force_state(AppState.STOPPED)
        self.assertFalse(self.sm.can_transition_to(AppState.RUNNING))

    def test_cannot_transition_to_self(self):
        for state in AppState:
            self.sm.force_state(state)
            self.assertFalse(self.sm.can_transition_to(state), f"Should not be able to transition from {state.name} to itself")


class TestOnTransitionCallbacks(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        self.sm = StateMachine()

    def tearDown(self):
        reset_event_bus()

    def test_callback_called_on_valid_transition(self):
        transitions = []
        self.sm.on_transition(lambda old, new: transitions.append((old, new)))
        self.sm.transition_to(AppState.STARTING)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0], (AppState.IDLE, AppState.STARTING))

    def test_callback_not_called_on_invalid_transition(self):
        transitions = []
        self.sm.on_transition(lambda old, new: transitions.append((old, new)))
        self.sm.transition_to(AppState.RUNNING)  # invalid from IDLE
        self.assertEqual(len(transitions), 0)

    def test_multiple_callbacks_all_called(self):
        results_a = []
        results_b = []
        self.sm.on_transition(lambda old, new: results_a.append((old, new)))
        self.sm.on_transition(lambda old, new: results_b.append((old, new)))
        self.sm.transition_to(AppState.STARTING)
        self.assertEqual(len(results_a), 1)
        self.assertEqual(len(results_b), 1)
        self.assertEqual(results_a[0], (AppState.IDLE, AppState.STARTING))
        self.assertEqual(results_b[0], (AppState.IDLE, AppState.STARTING))

    def test_callback_receives_correct_old_and_new_state(self):
        self.sm.transition_to(AppState.STARTING)
        transitions = []
        self.sm.on_transition(lambda old, new: transitions.append((old, new)))
        self.sm.transition_to(AppState.RUNNING)
        self.assertEqual(transitions[0], (AppState.STARTING, AppState.RUNNING))

    def test_callback_exception_does_not_prevent_state_change(self):
        def bad_callback(old, new):
            raise RuntimeError("callback error")

        self.sm.on_transition(bad_callback)
        result = self.sm.transition_to(AppState.STARTING)
        self.assertTrue(result)
        self.assertEqual(self.sm.state, AppState.STARTING)

    def test_callback_exception_does_not_prevent_other_callbacks(self):
        def bad_callback(old, new):
            raise RuntimeError("callback error")

        good_called = []
        self.sm.on_transition(bad_callback)
        self.sm.on_transition(lambda old, new: good_called.append((old, new)))
        self.sm.transition_to(AppState.STARTING)
        self.assertEqual(len(good_called), 1)

    def test_callback_called_on_force_state(self):
        transitions = []
        self.sm.on_transition(lambda old, new: transitions.append((old, new)))
        self.sm.force_state(AppState.RUNNING)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0], (AppState.IDLE, AppState.RUNNING))

    def test_callback_exception_in_force_state_does_not_break(self):
        def bad_callback(old, new):
            raise RuntimeError("callback error")

        self.sm.on_transition(bad_callback)
        self.sm.force_state(AppState.RUNNING)
        self.assertEqual(self.sm.state, AppState.RUNNING)

    def test_callback_sees_latest_snapshot_of_callbacks(self):
        """Callbacks registered after transition_to are not called for that transition."""
        transitions = []
        self.sm.transition_to(AppState.STARTING)
        self.sm.on_transition(lambda old, new: transitions.append((old, new)))
        self.sm.transition_to(AppState.RUNNING)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0], (AppState.STARTING, AppState.RUNNING))


class TestForceState(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        self.sm = StateMachine()

    def tearDown(self):
        reset_event_bus()

    def test_force_state_changes_state(self):
        self.sm.force_state(AppState.RUNNING)
        self.assertEqual(self.sm.state, AppState.RUNNING)

    def test_force_state_bypasses_validation(self):
        self.sm.force_state(AppState.RUNNING)  # IDLE -> RUNNING is normally invalid
        self.assertEqual(self.sm.state, AppState.RUNNING)

    def test_force_state_to_same_state(self):
        self.sm.force_state(AppState.IDLE)
        self.assertEqual(self.sm.state, AppState.IDLE)

    def test_force_state_emits_event(self):
        events = []
        bus = self.sm._bus
        bus.subscribe(AppStateChangedEvent, lambda e: events.append(e))
        self.sm.force_state(AppState.RUNNING)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].old_state, "IDLE")
        self.assertEqual(events[0].new_state, "RUNNING")

    def test_force_state_calls_callbacks(self):
        transitions = []
        self.sm.on_transition(lambda old, new: transitions.append((old, new)))
        self.sm.force_state(AppState.PAUSED)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0], (AppState.IDLE, AppState.PAUSED))

    def test_force_state_multiple_times(self):
        self.sm.force_state(AppState.RUNNING)
        self.sm.force_state(AppState.PAUSED)
        self.sm.force_state(AppState.IDLE)
        self.assertEqual(self.sm.state, AppState.IDLE)


class TestEventEmission(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        self.sm = StateMachine()
        self.events: list[AppStateChangedEvent] = []
        self.sm._bus.subscribe(AppStateChangedEvent, lambda e: self.events.append(e))

    def tearDown(self):
        reset_event_bus()

    def test_event_emitted_on_valid_transition(self):
        self.sm.transition_to(AppState.STARTING)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].old_state, "IDLE")
        self.assertEqual(self.events[0].new_state, "STARTING")

    def test_no_event_emitted_on_invalid_transition(self):
        self.sm.transition_to(AppState.RUNNING)  # invalid from IDLE
        self.assertEqual(len(self.events), 0)

    def test_event_emitted_on_force_state(self):
        self.sm.force_state(AppState.RUNNING)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].old_state, "IDLE")
        self.assertEqual(self.events[0].new_state, "RUNNING")

    def test_event_contains_state_names_not_values(self):
        self.sm.transition_to(AppState.STARTING)
        self.assertIsInstance(self.events[0].old_state, str)
        self.assertIsInstance(self.events[0].new_state, str)

    def test_multiple_transitions_emit_multiple_events(self):
        self.sm.transition_to(AppState.STARTING)
        self.sm.transition_to(AppState.RUNNING)
        self.sm.transition_to(AppState.PAUSED)
        self.assertEqual(len(self.events), 3)
        self.assertEqual(self.events[0].new_state, "STARTING")
        self.assertEqual(self.events[1].new_state, "RUNNING")
        self.assertEqual(self.events[2].new_state, "PAUSED")

    def test_event_old_state_matches_previous_state(self):
        self.sm.transition_to(AppState.STARTING)
        self.sm.transition_to(AppState.RUNNING)
        self.assertEqual(self.events[1].old_state, "STARTING")
        self.assertEqual(self.events[1].new_state, "RUNNING")


class TestStateMachineWithCustomBus(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()

    def tearDown(self):
        reset_event_bus()

    def test_state_machine_uses_custom_bus(self):
        events = []
        self.bus.subscribe(AppStateChangedEvent, lambda e: events.append(e))
        sm = StateMachine(bus=self.bus)
        sm.transition_to(AppState.STARTING)
        self.assertEqual(len(events), 1)

    def test_state_machine_default_bus(self):
        reset_event_bus()
        sm = StateMachine()
        self.assertIs(sm._bus, sm._bus)  # just verify it has a bus


class TestConcurrentTransitions(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        self.sm = StateMachine()

    def tearDown(self):
        reset_event_bus()

    def test_concurrent_transitions_no_corruption(self):
        """Multiple threads attempting transitions should not corrupt state."""
        errors: list[Exception] = []
        barrier = threading.Barrier(4)

        def worker(target_state: AppState) -> None:
            try:
                barrier.wait(timeout=5)
                self.sm.transition_to(target_state)
            except Exception as e:
                errors.append(e)

        # All threads try to transition from IDLE; only STARTING is valid.
        # After STARTING succeeds, RUNNING (valid from STARTING) may also succeed
        # due to the race, so we only verify no crashes and a valid final state.
        threads = [
            threading.Thread(target=worker, args=(AppState.STARTING,)),
            threading.Thread(target=worker, args=(AppState.RUNNING,)),
            threading.Thread(target=worker, args=(AppState.PAUSED,)),
            threading.Thread(target=worker, args=(AppState.STOPPING,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0)
        # State must be a valid AppState (no corruption)
        self.assertIn(self.sm.state, list(AppState))

    def test_concurrent_force_state_no_crash(self):
        """Concurrent force_state calls should not crash."""
        errors: list[Exception] = []
        barrier = threading.Barrier(6)

        def worker(state: AppState) -> None:
            try:
                barrier.wait(timeout=5)
                self.sm.force_state(state)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(s,)) for s in AppState]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0)
        # State should be one of the valid AppState values
        self.assertIn(self.sm.state, list(AppState))

    def test_concurrent_transition_and_read(self):
        """Reading state while transitioning should not crash."""
        errors: list[Exception] = []
        stop_event = threading.Event()

        def writer() -> None:
            try:
                sm = self.sm
                sm.transition_to(AppState.STARTING)
                sm.transition_to(AppState.RUNNING)
                sm.transition_to(AppState.PAUSED)
                sm.transition_to(AppState.STOPPING)
                sm.transition_to(AppState.STOPPED)
                stop_event.set()
            except Exception as e:
                errors.append(e)
                stop_event.set()

        def reader() -> None:
            try:
                while not stop_event.is_set():
                    _ = self.sm.state
                    _ = self.sm.is_running
                    _ = self.sm.is_stopped
                    _ = self.sm.can_transition_to(AppState.RUNNING)
            except Exception as e:
                errors.append(e)

        w = threading.Thread(target=writer)
        readers = [threading.Thread(target=reader) for _ in range(3)]
        w.start()
        for r in readers:
            r.start()
        w.join(timeout=10)
        for r in readers:
            r.join(timeout=10)

        self.assertEqual(len(errors), 0)


class TestMultipleTransitions(unittest.TestCase):
    def setUp(self):
        reset_event_bus()
        self.sm = StateMachine()

    def tearDown(self):
        reset_event_bus()

    def test_full_lifecycle_idle_to_stopped(self):
        self.assertEqual(self.sm.state, AppState.IDLE)
        self.assertTrue(self.sm.transition_to(AppState.STARTING))
        self.assertEqual(self.sm.state, AppState.STARTING)
        self.assertTrue(self.sm.transition_to(AppState.RUNNING))
        self.assertEqual(self.sm.state, AppState.RUNNING)
        self.assertTrue(self.sm.transition_to(AppState.STOPPING))
        self.assertEqual(self.sm.state, AppState.STOPPING)
        self.assertTrue(self.sm.transition_to(AppState.STOPPED))
        self.assertEqual(self.sm.state, AppState.STOPPED)

    def test_full_lifecycle_with_pause(self):
        self.assertTrue(self.sm.transition_to(AppState.STARTING))
        self.assertTrue(self.sm.transition_to(AppState.RUNNING))
        self.assertTrue(self.sm.transition_to(AppState.PAUSED))
        self.assertTrue(self.sm.transition_to(AppState.RUNNING))
        self.assertTrue(self.sm.transition_to(AppState.STOPPING))
        self.assertTrue(self.sm.transition_to(AppState.STOPPED))

    def test_restart_after_stop(self):
        self.assertTrue(self.sm.transition_to(AppState.STARTING))
        self.assertTrue(self.sm.transition_to(AppState.RUNNING))
        self.assertTrue(self.sm.transition_to(AppState.STOPPING))
        self.assertTrue(self.sm.transition_to(AppState.STOPPED))
        # Restart
        self.assertTrue(self.sm.transition_to(AppState.STARTING))
        self.assertEqual(self.sm.state, AppState.STARTING)
        self.assertTrue(self.sm.transition_to(AppState.RUNNING))
        self.assertEqual(self.sm.state, AppState.RUNNING)

    def test_stopping_to_idle_then_restart(self):
        self.assertTrue(self.sm.transition_to(AppState.STARTING))
        self.assertTrue(self.sm.transition_to(AppState.RUNNING))
        self.assertTrue(self.sm.transition_to(AppState.STOPPING))
        self.assertTrue(self.sm.transition_to(AppState.IDLE))
        self.assertEqual(self.sm.state, AppState.IDLE)
        # Can start again
        self.assertTrue(self.sm.transition_to(AppState.STARTING))

    def test_starting_fails_then_stopped(self):
        self.assertTrue(self.sm.transition_to(AppState.STARTING))
        self.assertTrue(self.sm.transition_to(AppState.STOPPED))
        self.assertEqual(self.sm.state, AppState.STOPPED)

    def test_stopped_to_idle_cycle(self):
        self.assertTrue(self.sm.transition_to(AppState.STARTING))
        self.assertTrue(self.sm.transition_to(AppState.STOPPED))
        self.assertTrue(self.sm.transition_to(AppState.IDLE))
        self.assertEqual(self.sm.state, AppState.IDLE)

    def test_is_running_across_lifecycle(self):
        self.assertFalse(self.sm.is_running)
        self.sm.transition_to(AppState.STARTING)
        self.assertFalse(self.sm.is_running)
        self.sm.transition_to(AppState.RUNNING)
        self.assertTrue(self.sm.is_running)
        self.sm.transition_to(AppState.PAUSED)
        self.assertFalse(self.sm.is_running)
        self.sm.transition_to(AppState.RUNNING)
        self.assertTrue(self.sm.is_running)
        self.sm.transition_to(AppState.STOPPING)
        self.assertFalse(self.sm.is_running)

    def test_is_stopped_across_lifecycle(self):
        self.assertTrue(self.sm.is_stopped)  # IDLE
        self.sm.transition_to(AppState.STARTING)
        self.assertFalse(self.sm.is_stopped)
        self.sm.transition_to(AppState.RUNNING)
        self.assertFalse(self.sm.is_stopped)
        self.sm.transition_to(AppState.STOPPING)
        self.assertFalse(self.sm.is_stopped)
        self.sm.transition_to(AppState.STOPPED)
        self.assertTrue(self.sm.is_stopped)


class TestStateMachineInitialState(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_new_state_machine_starts_idle(self):
        sm = StateMachine()
        self.assertEqual(sm.state, AppState.IDLE)

    def test_new_state_machine_is_stopped(self):
        sm = StateMachine()
        self.assertTrue(sm.is_stopped)

    def test_new_state_machine_not_running(self):
        sm = StateMachine()
        self.assertFalse(sm.is_running)


if __name__ == "__main__":
    unittest.main()
