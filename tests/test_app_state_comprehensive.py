from __future__ import annotations

import threading
import unittest

from platex_client.app_state import AppState, StateMachine
from platex_client.events import reset_event_bus


class TestAppStateEnum(unittest.TestCase):
    def test_all_states_exist(self):
        self.assertIsNotNone(AppState.IDLE)
        self.assertIsNotNone(AppState.STARTING)
        self.assertIsNotNone(AppState.RUNNING)
        self.assertIsNotNone(AppState.PAUSED)
        self.assertIsNotNone(AppState.STOPPING)
        self.assertIsNotNone(AppState.STOPPED)

    def test_states_are_unique(self):
        values = [s.value for s in AppState]
        self.assertEqual(len(values), len(set(values)))


class TestStateMachineTransitions(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_initial_state_is_idle(self):
        sm = StateMachine()
        self.assertEqual(sm.state, AppState.IDLE)

    def test_valid_transition_idle_to_starting(self):
        sm = StateMachine()
        self.assertTrue(sm.transition_to(AppState.STARTING))
        self.assertEqual(sm.state, AppState.STARTING)

    def test_valid_transition_starting_to_running(self):
        sm = StateMachine()
        sm.transition_to(AppState.STARTING)
        self.assertTrue(sm.transition_to(AppState.RUNNING))
        self.assertEqual(sm.state, AppState.RUNNING)

    def test_valid_transition_running_to_paused(self):
        sm = StateMachine()
        sm.force_state(AppState.RUNNING)
        self.assertTrue(sm.transition_to(AppState.PAUSED))
        self.assertEqual(sm.state, AppState.PAUSED)

    def test_valid_transition_paused_to_running(self):
        sm = StateMachine()
        sm.force_state(AppState.PAUSED)
        self.assertTrue(sm.transition_to(AppState.RUNNING))
        self.assertEqual(sm.state, AppState.RUNNING)

    def test_valid_transition_running_to_stopping(self):
        sm = StateMachine()
        sm.force_state(AppState.RUNNING)
        self.assertTrue(sm.transition_to(AppState.STOPPING))
        self.assertEqual(sm.state, AppState.STOPPING)

    def test_valid_transition_stopping_to_stopped(self):
        sm = StateMachine()
        sm.force_state(AppState.STOPPING)
        self.assertTrue(sm.transition_to(AppState.STOPPED))
        self.assertEqual(sm.state, AppState.STOPPED)

    def test_valid_transition_stopped_to_idle(self):
        sm = StateMachine()
        sm.force_state(AppState.STOPPED)
        self.assertTrue(sm.transition_to(AppState.IDLE))
        self.assertEqual(sm.state, AppState.IDLE)

    def test_valid_transition_stopped_to_starting(self):
        sm = StateMachine()
        sm.force_state(AppState.STOPPED)
        self.assertTrue(sm.transition_to(AppState.STARTING))
        self.assertEqual(sm.state, AppState.STARTING)

    def test_valid_transition_starting_to_stopped(self):
        sm = StateMachine()
        sm.transition_to(AppState.STARTING)
        self.assertTrue(sm.transition_to(AppState.STOPPED))
        self.assertEqual(sm.state, AppState.STOPPED)

    def test_valid_transition_stopping_to_idle(self):
        sm = StateMachine()
        sm.force_state(AppState.STOPPING)
        self.assertTrue(sm.transition_to(AppState.IDLE))
        self.assertEqual(sm.state, AppState.IDLE)

    def test_invalid_transition_idle_to_running(self):
        sm = StateMachine()
        self.assertFalse(sm.transition_to(AppState.RUNNING))
        self.assertEqual(sm.state, AppState.IDLE)

    def test_invalid_transition_idle_to_stopping(self):
        sm = StateMachine()
        self.assertFalse(sm.transition_to(AppState.STOPPING))
        self.assertEqual(sm.state, AppState.IDLE)

    def test_invalid_transition_running_to_starting(self):
        sm = StateMachine()
        sm.force_state(AppState.RUNNING)
        self.assertFalse(sm.transition_to(AppState.STARTING))
        self.assertEqual(sm.state, AppState.RUNNING)

    def test_invalid_transition_paused_to_starting(self):
        sm = StateMachine()
        sm.force_state(AppState.PAUSED)
        self.assertFalse(sm.transition_to(AppState.STARTING))
        self.assertEqual(sm.state, AppState.PAUSED)


class TestStateMachineForceState(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_force_state_from_any(self):
        sm = StateMachine()
        sm.force_state(AppState.RUNNING)
        self.assertEqual(sm.state, AppState.RUNNING)

    def test_force_state_to_stopped(self):
        sm = StateMachine()
        sm.force_state(AppState.RUNNING)
        sm.force_state(AppState.STOPPED)
        self.assertEqual(sm.state, AppState.STOPPED)

    def test_force_state_same_state(self):
        sm = StateMachine()
        sm.force_state(AppState.IDLE)
        self.assertEqual(sm.state, AppState.IDLE)

    def test_force_state_emits_event(self):
        sm = StateMachine()
        received = []
        sm._bus.subscribe(
            type(sm._bus._subscribers.__class__()),
            lambda e: None,
        )
        from platex_client.events import AppStateChangedEvent
        sm._bus.subscribe(AppStateChangedEvent, lambda e: received.append(e))
        sm.force_state(AppState.RUNNING)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].old_state, "IDLE")
        self.assertEqual(received[0].new_state, "RUNNING")


class TestStateMachineCanTransition(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_can_transition_from_idle(self):
        sm = StateMachine()
        self.assertTrue(sm.can_transition_to(AppState.STARTING))
        self.assertFalse(sm.can_transition_to(AppState.RUNNING))
        self.assertFalse(sm.can_transition_to(AppState.PAUSED))
        self.assertFalse(sm.can_transition_to(AppState.STOPPING))
        self.assertFalse(sm.can_transition_to(AppState.STOPPED))

    def test_can_transition_from_running(self):
        sm = StateMachine()
        sm.force_state(AppState.RUNNING)
        self.assertTrue(sm.can_transition_to(AppState.PAUSED))
        self.assertTrue(sm.can_transition_to(AppState.STOPPING))
        self.assertFalse(sm.can_transition_to(AppState.STARTING))
        self.assertFalse(sm.can_transition_to(AppState.IDLE))


class TestStateMachineProperties(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_is_running_true(self):
        sm = StateMachine()
        sm.force_state(AppState.RUNNING)
        self.assertTrue(sm.is_running)

    def test_is_running_false(self):
        sm = StateMachine()
        self.assertFalse(sm.is_running)

    def test_is_stopped_true_when_stopped(self):
        sm = StateMachine()
        sm.force_state(AppState.STOPPED)
        self.assertTrue(sm.is_stopped)

    def test_is_stopped_true_when_idle(self):
        sm = StateMachine()
        self.assertTrue(sm.is_stopped)

    def test_is_stopped_false_when_running(self):
        sm = StateMachine()
        sm.force_state(AppState.RUNNING)
        self.assertFalse(sm.is_stopped)


class TestStateMachineCallbacks(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_on_transition_callback(self):
        sm = StateMachine()
        transitions = []
        sm.on_transition(lambda old, new: transitions.append((old, new)))
        sm.transition_to(AppState.STARTING)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0][0], AppState.IDLE)
        self.assertEqual(transitions[0][1], AppState.STARTING)

    def test_multiple_callbacks(self):
        sm = StateMachine()
        count = {"value": 0}

        def cb1(old, new):
            count["value"] += 1

        def cb2(old, new):
            count["value"] += 10

        sm.on_transition(cb1)
        sm.on_transition(cb2)
        sm.transition_to(AppState.STARTING)
        self.assertEqual(count["value"], 11)

    def test_callback_exception_does_not_break(self):
        sm = StateMachine()
        bad_called = threading.Event()
        good_called = threading.Event()

        def bad_cb(old, new):
            bad_called.set()
            raise RuntimeError("callback error")

        def good_cb(old, new):
            good_called.set()

        sm.on_transition(bad_cb)
        sm.on_transition(good_cb)
        result = sm.transition_to(AppState.STARTING)
        self.assertTrue(result)
        self.assertTrue(bad_called.wait(timeout=2))
        self.assertTrue(good_called.wait(timeout=2))


class TestStateMachineConcurrency(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_concurrent_transitions_no_deadlock(self):
        sm = StateMachine()
        errors = []

        def transition_loop():
            try:
                for _ in range(50):
                    sm.transition_to(AppState.STARTING)
                    sm.transition_to(AppState.RUNNING)
                    sm.transition_to(AppState.STOPPING)
                    sm.transition_to(AppState.STOPPED)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=transition_loop) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(len(errors), 0)

    def test_concurrent_force_state(self):
        sm = StateMachine()
        errors = []

        def force_loop():
            try:
                for _ in range(50):
                    sm.force_state(AppState.RUNNING)
                    sm.force_state(AppState.STOPPED)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=force_loop) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(len(errors), 0)


class TestStateMachineFullCycle(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_full_lifecycle(self):
        sm = StateMachine()
        self.assertEqual(sm.state, AppState.IDLE)

        sm.transition_to(AppState.STARTING)
        self.assertEqual(sm.state, AppState.STARTING)

        sm.transition_to(AppState.RUNNING)
        self.assertEqual(sm.state, AppState.RUNNING)

        sm.transition_to(AppState.PAUSED)
        self.assertEqual(sm.state, AppState.PAUSED)

        sm.transition_to(AppState.RUNNING)
        self.assertEqual(sm.state, AppState.RUNNING)

        sm.transition_to(AppState.STOPPING)
        self.assertEqual(sm.state, AppState.STOPPING)

        sm.transition_to(AppState.STOPPED)
        self.assertEqual(sm.state, AppState.STOPPED)

        sm.transition_to(AppState.IDLE)
        self.assertEqual(sm.state, AppState.IDLE)

    def test_restart_cycle(self):
        sm = StateMachine()
        sm.transition_to(AppState.STARTING)
        sm.transition_to(AppState.RUNNING)
        sm.transition_to(AppState.STOPPING)
        sm.transition_to(AppState.STOPPED)
        sm.transition_to(AppState.STARTING)
        self.assertEqual(sm.state, AppState.STARTING)


if __name__ == "__main__":
    unittest.main()
