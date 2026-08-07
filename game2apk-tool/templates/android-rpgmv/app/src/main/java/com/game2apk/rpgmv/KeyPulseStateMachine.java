package com.game2apk.rpgmv;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Frame-safe short key pulses. A pulse keeps a key down for at least one MV
 * render/update opportunity before releasing it, while coalescing overlapping
 * pulses for the same key.
 */
public final class KeyPulseStateMachine {
    public static final long DEFAULT_MIN_PULSE_MS = 40L;

    public interface Scheduler {
        void postDelayed(Runnable runnable, long delayMs);

        void removeCallbacks(Runnable runnable);
    }

    private static final class Pulse {
        private final int keyCode;
        private Runnable callback;
        private boolean active = true;

        private Pulse(int keyCode) {
            this.keyCode = keyCode;
        }
    }

    private final KeySink sink;
    private final Scheduler scheduler;
    private final long minimumPulseMs;
    private final Map<Integer, Integer> activeCounts = new HashMap<>();
    private final List<Pulse> pending = new ArrayList<>();

    public KeyPulseStateMachine(KeySink sink, Scheduler scheduler) {
        this(sink, scheduler, DEFAULT_MIN_PULSE_MS);
    }

    public KeyPulseStateMachine(KeySink sink, Scheduler scheduler, long minimumPulseMs) {
        if (sink == null || scheduler == null) {
            throw new IllegalArgumentException("sink and scheduler are required");
        }
        if (minimumPulseMs <= 0L) {
            throw new IllegalArgumentException("minimumPulseMs must be positive");
        }
        this.sink = sink;
        this.scheduler = scheduler;
        this.minimumPulseMs = minimumPulseMs;
    }

    public void pulse(final int keyCode) {
        Integer count = activeCounts.get(keyCode);
        if (count == null) {
            activeCounts.put(keyCode, 1);
            sink.keyDown(keyCode);
        } else {
            activeCounts.put(keyCode, count + 1);
        }
        final Pulse pulse = new Pulse(keyCode);
        pulse.callback = new Runnable() {
            @Override
            public void run() {
                finish(pulse);
            }
        };
        pending.add(pulse);
        scheduler.postDelayed(pulse.callback, minimumPulseMs);
    }

    private void finish(Pulse pulse) {
        if (!pulse.active) {
            return;
        }
        pulse.active = false;
        pending.remove(pulse);
        Integer count = activeCounts.get(pulse.keyCode);
        if (count == null || count <= 1) {
            activeCounts.remove(pulse.keyCode);
            sink.keyUp(pulse.keyCode);
        } else {
            activeCounts.put(pulse.keyCode, count - 1);
        }
    }

    /** Release every pulse immediately during cancellation/navigation/destroy. */
    public void releaseAll() {
        for (Pulse pulse : pending) {
            pulse.active = false;
            scheduler.removeCallbacks(pulse.callback);
        }
        pending.clear();
        for (Integer keyCode : new ArrayList<>(activeCounts.keySet())) {
            sink.keyUp(keyCode);
        }
        activeCounts.clear();
    }

    public boolean hasActivePulses() {
        return !pending.isEmpty();
    }
}
