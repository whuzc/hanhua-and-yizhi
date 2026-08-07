package com.game2apk.rpgmv;

/**
 * Recognizes a short two-finger tap that began entirely in the game/WebView
 * region. Control pointers, movement, timeout, and any third pointer make the
 * candidate permanently invalid until the current sequence ends.
 */
public final class TwoFingerTapGestureStateMachine {
    public enum Region {
        GAME,
        CONTROL
    }

    public enum Outcome {
        NONE,
        SECOND_FINGER,
        CANCEL
    }

    private final long secondFingerWindowMs;
    private final float touchSlopPx;
    private final long maxTapDurationMs;
    private int firstPointerId = -1;
    private int secondPointerId = -1;
    private float firstX;
    private float firstY;
    private float secondX;
    private float secondY;
    private long startTimeMs = -1L;
    private boolean invalid;
    private boolean secondRecognized;

    public TwoFingerTapGestureStateMachine(long secondFingerWindowMs, float touchSlopPx) {
        if (secondFingerWindowMs < 1L || touchSlopPx <= 0.0f) {
            throw new IllegalArgumentException("invalid two-finger gesture parameters");
        }
        this.secondFingerWindowMs = secondFingerWindowMs;
        this.touchSlopPx = touchSlopPx;
        this.maxTapDurationMs = secondFingerWindowMs * 2L;
    }

    public Outcome onPointerDown(int pointerId, Region region, float x, float y, long timeMs) {
        if (firstPointerId < 0) {
            firstPointerId = pointerId;
            firstX = x;
            firstY = y;
            startTimeMs = timeMs;
            invalid = region != Region.GAME;
            return Outcome.NONE;
        }
        if (pointerId == firstPointerId || secondPointerId >= 0) {
            invalid = true;
            return Outcome.NONE;
        }
        if (region != Region.GAME
                || invalid
                || timeMs - startTimeMs > secondFingerWindowMs) {
            invalid = true;
            secondPointerId = pointerId;
            secondX = x;
            secondY = y;
            return Outcome.NONE;
        }
        secondPointerId = pointerId;
        secondX = x;
        secondY = y;
        secondRecognized = true;
        return Outcome.SECOND_FINGER;
    }

    public void onPointerMove(int pointerId, float x, float y, long timeMs) {
        if (pointerId == firstPointerId) {
            if (distanceSquared(firstX, firstY, x, y) > touchSlopPx * touchSlopPx) {
                invalid = true;
            }
        } else if (pointerId == secondPointerId
                && distanceSquared(secondX, secondY, x, y) > touchSlopPx * touchSlopPx) {
            invalid = true;
        }
        if (startTimeMs >= 0L && timeMs - startTimeMs > maxTapDurationMs) {
            invalid = true;
        }
    }

    public Outcome onPointerUp(int pointerId, long timeMs) {
        if (pointerId != firstPointerId && pointerId != secondPointerId) {
            return Outcome.NONE;
        }
        boolean lastPointer = pointerId == firstPointerId
                ? secondPointerId < 0 : firstPointerId < 0;
        if (pointerId == firstPointerId) {
            firstPointerId = -1;
        } else {
            secondPointerId = -1;
        }
        if (!lastPointer) {
            return Outcome.NONE;
        }
        Outcome outcome = secondRecognized && !invalid
                && startTimeMs >= 0L
                && timeMs - startTimeMs <= maxTapDurationMs
                ? Outcome.CANCEL : Outcome.NONE;
        reset();
        return outcome;
    }

    public void onThreeFingerDetected() {
        invalid = true;
    }

    /** Invalidate the candidate when a tracked finger enters a control area. */
    public void invalidateCandidate() {
        invalid = true;
    }

    public void cancel() {
        reset();
    }

    public boolean isTracking() {
        return firstPointerId >= 0 || secondPointerId >= 0;
    }

    private void reset() {
        firstPointerId = -1;
        secondPointerId = -1;
        startTimeMs = -1L;
        invalid = false;
        secondRecognized = false;
    }

    private static float distanceSquared(float x1, float y1, float x2, float y2) {
        float dx = x1 - x2;
        float dy = y1 - y2;
        return dx * dx + dy * dy;
    }
}
