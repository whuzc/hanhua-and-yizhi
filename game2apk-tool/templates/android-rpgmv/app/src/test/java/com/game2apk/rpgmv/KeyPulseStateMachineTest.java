package com.game2apk.rpgmv;

import org.junit.Test;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public final class KeyPulseStateMachineTest {
    @Test
    public void pulseStaysDownAcrossAnMvUpdateBeforeRelease() {
        FakeScheduler scheduler = new FakeScheduler();
        FakeMvInput input = new FakeMvInput();
        KeyPulseStateMachine pulses = new KeyPulseStateMachine(input, scheduler, 40L);

        pulses.pulse(13);
        assertEquals("down:13", input.events.get(0));
        scheduler.advanceTo(16L);
        input.update();
        assertTrue(input.isPressed("ok"));
        assertTrue(input.isTriggered("ok"));

        scheduler.advanceTo(40L);
        input.update();
        assertFalse(input.isPressed("ok"));
        assertEquals("up:13", input.events.get(1));
    }

    @Test
    public void overlappingPulsesAndCancellationReleaseOnce() {
        FakeScheduler scheduler = new FakeScheduler();
        FakeMvInput input = new FakeMvInput();
        KeyPulseStateMachine pulses = new KeyPulseStateMachine(input, scheduler, 40L);

        pulses.pulse(27);
        pulses.pulse(27);
        assertEquals(1, input.events.size());
        scheduler.advanceTo(16L);
        input.update();
        pulses.releaseAll();
        pulses.releaseAll();
        assertEquals("up:27", input.events.get(1));
        scheduler.advanceTo(100L);
        assertEquals(2, input.events.size());
    }

    private static final class FakeScheduler implements KeyPulseStateMachine.Scheduler {
        private final List<Task> tasks = new ArrayList<>();
        private long now;

        @Override
        public void postDelayed(Runnable runnable, long delayMs) {
            tasks.add(new Task(runnable, now + delayMs));
        }

        @Override
        public void removeCallbacks(Runnable runnable) {
            tasks.removeIf(task -> task.runnable == runnable);
        }

        void advanceTo(long target) {
            now = target;
            boolean ran;
            do {
                ran = false;
                for (int index = 0; index < tasks.size(); index++) {
                    if (tasks.get(index).due <= now) {
                        Runnable runnable = tasks.remove(index).runnable;
                        runnable.run();
                        ran = true;
                        break;
                    }
                }
            } while (ran);
        }
    }

    private static final class Task {
        private final Runnable runnable;
        private final long due;

        private Task(Runnable runnable, long due) {
            this.runnable = runnable;
            this.due = due;
        }
    }

    private static final class FakeMvInput implements KeySink {
        private final Map<Integer, String> mapper = new HashMap<>();
        private final Map<String, Boolean> current = new HashMap<>();
        private final Map<String, Boolean> previous = new HashMap<>();
        private final Map<String, Boolean> triggered = new HashMap<>();
        private final List<String> events = new ArrayList<>();

        private FakeMvInput() {
            mapper.put(13, "ok");
            mapper.put(27, "cancel");
        }

        @Override
        public void keyDown(int keyCode) {
            String name = mapper.get(keyCode);
            if (name != null) {
                current.put(name, true);
            }
            events.add("down:" + keyCode);
        }

        @Override
        public void keyUp(int keyCode) {
            String name = mapper.get(keyCode);
            if (name != null) {
                current.put(name, false);
            }
            events.add("up:" + keyCode);
        }

        private void update() {
            triggered.clear();
            for (Map.Entry<String, Boolean> entry : current.entrySet()) {
                triggered.put(
                        entry.getKey(),
                        Boolean.TRUE.equals(entry.getValue())
                                && !Boolean.TRUE.equals(previous.get(entry.getKey()))
                );
            }
            previous.clear();
            previous.putAll(current);
        }

        private boolean isPressed(String name) {
            return Boolean.TRUE.equals(current.get(name));
        }

        private boolean isTriggered(String name) {
            return Boolean.TRUE.equals(triggered.get(name));
        }
    }
}
