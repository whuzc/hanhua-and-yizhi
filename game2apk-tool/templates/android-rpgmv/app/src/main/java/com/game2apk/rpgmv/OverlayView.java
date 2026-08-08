package com.game2apk.rpgmv;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.View;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Semi-transparent controls drawn above the WebView.
 *
 * The view is deliberately non-clickable for the game area: blank touches
 * return false and Android keeps the WebView as the native touch target. The
 * parent observes those events only to recognize the two-finger cancel and
 * takes over that stream after sending one ACTION_CANCEL to the WebView.
 */
public final class OverlayView extends View {
    private static final NormalizedRect VISIBLE_HIDE_HANDLE =
            NormalizedRect.fromXYWH(0.94f, 0.02f, 0.055f, 0.065f);
    private static final NormalizedRect CHEAT_HANDLE =
            NormalizedRect.fromXYWH(0.87f, 0.02f, 0.065f, 0.065f);
    private static final NormalizedRect HIDDEN_RECOVERY_HANDLE =
            NormalizedRect.fromXYWH(0.94f, 0.90f, 0.055f, 0.065f);

    public static final int TAKEOVER_GAME_TWO_FINGER = 1;
    public static final int TAKEOVER_CONTROL = 2;
    public static final int TAKEOVER_THREE_OR_MORE = 3;

    private enum PointerKind {
        BUTTON,
        HIDE_HANDLE,
        RECOVERY_HANDLE,
        CHEAT_HANDLE,
        PASSIVE,
        THREE_FINGER
    }

    private enum HitKind {
        BUTTON,
        HIDE_HANDLE,
        RECOVERY_HANDLE,
        CHEAT_HANDLE,
        GAME
    }

    private static final class Hit {
        private final HitKind kind;
        private final Game2ApkConfig.ButtonConfig button;

        private Hit(HitKind kind, Game2ApkConfig.ButtonConfig button) {
            this.kind = kind;
            this.button = button;
        }
    }

    /** Immutable result used by the parent touch router before child dispatch. */
    public static final class NativeTouchObservation {
        public final int takeoverReason;
        public final int pointerId;
        private final Hit hit;

        private NativeTouchObservation(int takeoverReason, int pointerId, Hit hit) {
            this.takeoverReason = takeoverReason;
            this.pointerId = pointerId;
            this.hit = hit;
        }

        private static NativeTouchObservation none() {
            return new NativeTouchObservation(0, -1, null);
        }
    }

    private final Game2ApkConfig config;
    private final KeySink keySink;
    private final OverlayStateStore stateStore;
    private OverlayLayout layout;
    private float opacity;
    private final OverlayVisibilityStateMachine visibility;
    private final KeyPulseStateMachine pulses;
    private final HeldKeyStateMachine held = new HeldKeyStateMachine();
    private final TwoFingerTapGestureStateMachine twoFinger;
    private final Map<Integer, PointerKind> pointerKinds = new HashMap<>();
    private final Map<Integer, Game2ApkConfig.ButtonConfig> buttonsByPointer = new HashMap<>();
    private boolean nativeGameTracking;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint textPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Runnable visibilityRunnable = new Runnable() {
        @Override
        public void run() {
            if (visibility.tick(SystemClock.uptimeMillis())) {
                stateStore.saveHidden(false);
                invalidate();
            }
        }
    };

    public OverlayView(Context context, Game2ApkConfig config, KeySink keySink,
                       OverlayStateStore stateStore, OverlayStateStore.State state) {
        super(context);
        this.config = config;
        this.keySink = keySink;
        this.stateStore = stateStore;
        this.layout = state.layout;
        this.opacity = state.opacity;
        this.visibility = new OverlayVisibilityStateMachine(state.hidden);
        this.twoFinger = new TwoFingerTapGestureStateMachine(
                config.touch.twoFingerWindowMs, config.touch.touchSlopPx);
        this.pulses = new KeyPulseStateMachine(keySink, new KeyPulseStateMachine.Scheduler() {
            @Override
            public void postDelayed(Runnable runnable, long delayMs) {
                OverlayView.this.postDelayed(runnable, delayMs);
            }

            @Override
            public void removeCallbacks(Runnable runnable) {
                OverlayView.this.removeCallbacks(runnable);
            }
        });
        setWillNotDraw(false);
        setClickable(false);
        setFocusable(false);
        textPaint.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
    }

    public void setHidden(boolean hidden) {
        boolean changed = hidden ? visibility.hide() : visibility.restoreByHandle();
        if (changed) {
            releaseAllInput();
            stateStore.saveHidden(hidden);
            invalidate();
        }
    }

    public void setOpacity(float opacity) {
        this.opacity = Math.max(0.0f, Math.min(1.0f, opacity));
        stateStore.saveOpacity(this.opacity);
        invalidate();
    }

    public OverlayLayout getLayoutState() {
        return layout;
    }

    public void setLayoutState(OverlayLayout layout) {
        this.layout = layout;
        stateStore.saveLayout(layout);
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (visibility.isHidden()) {
            drawHandle(canvas, HIDDEN_RECOVERY_HANDLE, "+");
            return;
        }
        for (Game2ApkConfig.ButtonConfig button : config.buttons) {
            NormalizedRect normalized = layout.buttonRect(button.id);
            if (normalized != null) {
                drawButton(canvas, normalized, button.label);
            }
        }
        drawHandle(canvas, VISIBLE_HIDE_HANDLE, "-");
        drawHandle(canvas, CHEAT_HANDLE, "作弊");
    }

    private void drawButton(Canvas canvas, NormalizedRect normalized, String label) {
        RectF rect = toPixels(normalized);
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(withOpacity(Color.rgb(20, 28, 42), 0.76f));
        canvas.drawRoundRect(rect, rect.height() * 0.22f, rect.height() * 0.22f, paint);
        paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(Math.max(1.0f, rect.height() * 0.025f));
        paint.setColor(withOpacity(Color.WHITE, 0.58f));
        canvas.drawRoundRect(rect, rect.height() * 0.22f, rect.height() * 0.22f, paint);
        textPaint.setTextAlign(Paint.Align.CENTER);
        textPaint.setTextSize(Math.max(12.0f, rect.height() * 0.34f));
        textPaint.setColor(withOpacity(Color.WHITE, 0.90f));
        Paint.FontMetrics metrics = textPaint.getFontMetrics();
        float baseline = rect.centerY() - (metrics.ascent + metrics.descent) / 2.0f;
        canvas.drawText(label, rect.centerX(), baseline, textPaint);
    }

    private void drawHandle(Canvas canvas, NormalizedRect normalized, String label) {
        RectF rect = toPixels(normalized);
        paint.setStyle(Paint.Style.FILL);
        paint.setColor(withOpacity(Color.BLACK, 0.30f));
        canvas.drawRoundRect(rect, rect.height() * 0.28f, rect.height() * 0.28f, paint);
        textPaint.setTextAlign(Paint.Align.CENTER);
        textPaint.setTextSize(Math.max(10.0f, rect.height() * 0.52f));
        textPaint.setColor(withOpacity(Color.WHITE, 0.62f));
        Paint.FontMetrics metrics = textPaint.getFontMetrics();
        float baseline = rect.centerY() - (metrics.ascent + metrics.descent) / 2.0f;
        canvas.drawText(label, rect.centerX(), baseline, textPaint);
    }

    /**
     * Observe a native WebView stream without consuming it. A takeover is
     * requested only when a second pointer starts in a control or when the
     * all-game two-finger candidate is recognized.
     */
    public NativeTouchObservation observeNativeTouch(MotionEvent event) {
        if (event == null) {
            return NativeTouchObservation.none();
        }
        long now = eventTime(event);
        int action = event.getActionMasked();
        if (!nativeGameTracking) {
            if (action == MotionEvent.ACTION_DOWN) {
                int index = event.getActionIndex();
                Hit hit = hitTest(normalizedX(event.getX(index)), normalizedY(event.getY(index)));
                if (hit.kind == HitKind.GAME) {
                    nativeGameTracking = true;
                    int pointerId = event.getPointerId(index);
                    visibility.onPointerDown(pointerId, now);
                    twoFinger.onPointerDown(pointerId,
                            TwoFingerTapGestureStateMachine.Region.GAME,
                            event.getX(index), event.getY(index), now);
                    scheduleVisibilityCheck();
                }
            }
            return NativeTouchObservation.none();
        }

        switch (action) {
            case MotionEvent.ACTION_POINTER_DOWN: {
                int index = event.getActionIndex();
                int pointerId = event.getPointerId(index);
                visibility.onPointerDown(pointerId, now);
                if (event.getPointerCount() >= 3) {
                    twoFinger.onThreeFingerDetected();
                    scheduleVisibilityCheck();
                    return new NativeTouchObservation(
                            TAKEOVER_THREE_OR_MORE, pointerId, null);
                }
                Hit hit = hitTest(normalizedX(event.getX(index)), normalizedY(event.getY(index)));
                TwoFingerTapGestureStateMachine.Region region = hit.kind == HitKind.GAME
                        ? TwoFingerTapGestureStateMachine.Region.GAME
                        : TwoFingerTapGestureStateMachine.Region.CONTROL;
                TwoFingerTapGestureStateMachine.Outcome outcome = twoFinger.onPointerDown(
                        pointerId, region, event.getX(index), event.getY(index), now);
                scheduleVisibilityCheck();
                if (hit.kind != HitKind.GAME) {
                    return new NativeTouchObservation(TAKEOVER_CONTROL, pointerId, hit);
                }
                if (outcome == TwoFingerTapGestureStateMachine.Outcome.SECOND_FINGER) {
                    return new NativeTouchObservation(TAKEOVER_GAME_TWO_FINGER, pointerId, hit);
                }
                return NativeTouchObservation.none();
            }
            case MotionEvent.ACTION_MOVE:
                observeNativeMove(event, now);
                return NativeTouchObservation.none();
            case MotionEvent.ACTION_POINTER_UP:
            case MotionEvent.ACTION_UP:
                observeNativeUp(event, now);
                return NativeTouchObservation.none();
            case MotionEvent.ACTION_CANCEL:
                resetNativeTracking();
                return NativeTouchObservation.none();
            default:
                return NativeTouchObservation.none();
        }
    }

    /** Handle the pointer-down event that caused the parent to take over. */
    public void beginRootTakeover(NativeTouchObservation observation) {
        if (observation == null) {
            return;
        }
        if (observation.takeoverReason == TAKEOVER_CONTROL && observation.hit != null) {
            registerControlPointer(observation.pointerId, observation.hit);
        } else if (observation.takeoverReason == TAKEOVER_THREE_OR_MORE) {
            pointerKinds.put(observation.pointerId, PointerKind.THREE_FINGER);
        }
        invalidate();
    }

    /** Handle events after the parent has taken over a native WebView stream. */
    public void handleRootTouch(MotionEvent event) {
        if (event == null) {
            return;
        }
        long now = eventTime(event);
        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_POINTER_DOWN:
                handleRootPointerDown(event, now);
                break;
            case MotionEvent.ACTION_MOVE:
                for (int index = 0; index < event.getPointerCount(); index++) {
                    if (hitTest(normalizedX(event.getX(index)), normalizedY(event.getY(index))).kind
                            != HitKind.GAME) {
                        twoFinger.invalidateCandidate();
                    }
                    twoFinger.onPointerMove(event.getPointerId(index), event.getX(index), event.getY(index), now);
                }
                tickVisibility(now);
                break;
            case MotionEvent.ACTION_POINTER_UP:
            case MotionEvent.ACTION_UP:
                handleRootPointerUp(event, now);
                break;
            case MotionEvent.ACTION_CANCEL:
                releaseAllInput();
                break;
            default:
                break;
        }
        invalidate();
    }

    private void handleRootPointerDown(MotionEvent event, long now) {
        int index = event.getActionIndex();
        int pointerId = event.getPointerId(index);
        visibility.onPointerDown(pointerId, now);
        if (event.getPointerCount() >= 3) {
            twoFinger.onThreeFingerDetected();
            pointerKinds.put(pointerId, PointerKind.THREE_FINGER);
            scheduleVisibilityCheck();
            return;
        }
        Hit hit = hitTest(normalizedX(event.getX(index)), normalizedY(event.getY(index)));
        TwoFingerTapGestureStateMachine.Region region = hit.kind == HitKind.GAME
                ? TwoFingerTapGestureStateMachine.Region.GAME
                : TwoFingerTapGestureStateMachine.Region.CONTROL;
        twoFinger.onPointerDown(pointerId, region, event.getX(index), event.getY(index), now);
        if (hit.kind == HitKind.GAME) {
            pointerKinds.put(pointerId, PointerKind.PASSIVE);
        } else {
            registerControlPointer(pointerId, hit);
        }
        scheduleVisibilityCheck();
    }

    private void handleRootPointerUp(MotionEvent event, long now) {
        int index = event.getActionIndex();
        int pointerId = event.getPointerId(index);
        PointerKind kind = pointerKinds.remove(pointerId);
        if (kind == PointerKind.BUTTON) {
            Game2ApkConfig.ButtonConfig button = buttonsByPointer.remove(pointerId);
            if (button != null && "hold".equals(button.mode)) {
                apply(held.onPointerUp(pointerId));
            }
        } else if (kind == PointerKind.HIDE_HANDLE) {
            setHidden(true);
        } else if (kind == PointerKind.RECOVERY_HANDLE) {
            if (visibility.restoreByHandle()) {
                stateStore.saveHidden(false);
            }
        } else if (kind == PointerKind.CHEAT_HANDLE) {
            keySink.openCheatPanel();
        }
        TwoFingerTapGestureStateMachine.Outcome outcome = twoFinger.onPointerUp(pointerId, now);
        if (outcome == TwoFingerTapGestureStateMachine.Outcome.CANCEL) {
            pulses.pulse(config.touch.cancelKeyCode);
        }
        visibility.onPointerUp(pointerId);
        tickVisibility(now);
        if (event.getActionMasked() == MotionEvent.ACTION_UP) {
            nativeGameTracking = false;
            removeCallbacks(visibilityRunnable);
            pointerKinds.clear();
            buttonsByPointer.clear();
        }
    }

    private void observeNativeMove(MotionEvent event, long now) {
        for (int index = 0; index < event.getPointerCount(); index++) {
            if (hitTest(normalizedX(event.getX(index)), normalizedY(event.getY(index))).kind
                    != HitKind.GAME) {
                twoFinger.invalidateCandidate();
            }
            twoFinger.onPointerMove(event.getPointerId(index), event.getX(index), event.getY(index), now);
        }
        tickVisibility(now);
    }

    private void observeNativeUp(MotionEvent event, long now) {
        int index = event.getActionIndex();
        twoFinger.onPointerUp(event.getPointerId(index), now);
        visibility.onPointerUp(event.getPointerId(index));
        tickVisibility(now);
        if (event.getActionMasked() == MotionEvent.ACTION_UP) {
            resetNativeTracking();
        }
    }

    private void resetNativeTracking() {
        nativeGameTracking = false;
        twoFinger.cancel();
        visibility.clearPointers();
        removeCallbacks(visibilityRunnable);
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        if (event == null) {
            return false;
        }
        long now = eventTime(event);
        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                // The parent has already observed a game-area ACTION_DOWN.
                // Returning false here is essential: it lets the WebView
                // become the native touch target for ordinary single-finger
                // MV TouchInput. Controls and handles still return true.
                int downIndex = event.getActionIndex();
                if (hitTest(normalizedX(event.getX(downIndex)), normalizedY(event.getY(downIndex))).kind
                        == HitKind.GAME) {
                    return false;
                }
                return handleOverlayPointerDown(event, now);
            case MotionEvent.ACTION_POINTER_DOWN:
                return handleOverlayPointerDown(event, now);
            case MotionEvent.ACTION_MOVE:
                if (pointerKinds.isEmpty()) {
                    return false;
                }
                tickVisibility(now);
                return true;
            case MotionEvent.ACTION_POINTER_UP:
            case MotionEvent.ACTION_UP:
                if (pointerKinds.isEmpty()) {
                    return false;
                }
                handleOverlayPointerUp(event, now);
                return true;
            case MotionEvent.ACTION_CANCEL:
                if (pointerKinds.isEmpty()) {
                    return false;
                }
                releaseAllInput();
                return true;
            default:
                return !pointerKinds.isEmpty();
        }
    }

    private boolean handleOverlayPointerDown(MotionEvent event, long now) {
        int index = event.getActionIndex();
        int pointerId = event.getPointerId(index);
        visibility.onPointerDown(pointerId, now);
        if (event.getPointerCount() >= 3) {
            pointerKinds.put(pointerId, PointerKind.THREE_FINGER);
            scheduleVisibilityCheck();
            return true;
        }
        Hit hit = hitTest(normalizedX(event.getX(index)), normalizedY(event.getY(index)));
        if (hit.kind == HitKind.GAME) {
            // A control stream owns this view. Do not turn a newly added game
            // pointer into a map touch or a cancel gesture.
            pointerKinds.put(pointerId, PointerKind.PASSIVE);
            return true;
        }
        registerControlPointer(pointerId, hit);
        scheduleVisibilityCheck();
        invalidate();
        return true;
    }

    private void handleOverlayPointerUp(MotionEvent event, long now) {
        int index = event.getActionIndex();
        int pointerId = event.getPointerId(index);
        PointerKind kind = pointerKinds.remove(pointerId);
        if (kind == PointerKind.BUTTON) {
            Game2ApkConfig.ButtonConfig button = buttonsByPointer.remove(pointerId);
            if (button != null && "hold".equals(button.mode)) {
                apply(held.onPointerUp(pointerId));
            }
        } else if (kind == PointerKind.HIDE_HANDLE) {
            setHidden(true);
        } else if (kind == PointerKind.RECOVERY_HANDLE) {
            if (visibility.restoreByHandle()) {
                stateStore.saveHidden(false);
            }
        } else if (kind == PointerKind.CHEAT_HANDLE) {
            keySink.openCheatPanel();
        }
        visibility.onPointerUp(pointerId);
        tickVisibility(now);
        if (event.getActionMasked() == MotionEvent.ACTION_UP) {
            pointerKinds.clear();
            buttonsByPointer.clear();
        }
    }

    private void registerControlPointer(int pointerId, Hit hit) {
        if (hit == null) {
            pointerKinds.put(pointerId, PointerKind.PASSIVE);
            return;
        }
        switch (hit.kind) {
            case BUTTON:
                pointerKinds.put(pointerId, PointerKind.BUTTON);
                buttonsByPointer.put(pointerId, hit.button);
                if ("hold".equals(hit.button.mode)) {
                    apply(held.onPointerDown(pointerId, hit.button.keyCode));
                } else {
                    pulses.pulse(hit.button.keyCode);
                }
                break;
            case HIDE_HANDLE:
                pointerKinds.put(pointerId, PointerKind.HIDE_HANDLE);
                break;
            case RECOVERY_HANDLE:
                pointerKinds.put(pointerId, PointerKind.RECOVERY_HANDLE);
                break;
            case CHEAT_HANDLE:
                pointerKinds.put(pointerId, PointerKind.CHEAT_HANDLE);
                break;
            case GAME:
            default:
                pointerKinds.put(pointerId, PointerKind.PASSIVE);
                break;
        }
    }

    private void tickVisibility(long now) {
        if (visibility.tick(now)) {
            stateStore.saveHidden(false);
        }
    }

    private void scheduleVisibilityCheck() {
        removeCallbacks(visibilityRunnable);
        if (visibility.activePointerCount() >= 3) {
            postDelayed(visibilityRunnable,
                    OverlayVisibilityStateMachine.THREE_FINGER_LONG_PRESS_MS + 8L);
        }
    }

    private void apply(List<KeyAction> actions) {
        KeyActions.apply(actions, keySink);
    }

    /** Release held keys and gesture state during hide, navigation, or destroy. */
    public void releaseAllInput() {
        apply(held.releaseAll());
        pulses.releaseAll();
        pointerKinds.clear();
        buttonsByPointer.clear();
        twoFinger.cancel();
        nativeGameTracking = false;
        visibility.clearPointers();
        removeCallbacks(visibilityRunnable);
        invalidate();
    }

    private Hit hitTest(float x, float y) {
        if (visibility.isHidden()) {
            return new Hit(HIDDEN_RECOVERY_HANDLE.contains(x, y)
                    ? HitKind.RECOVERY_HANDLE : HitKind.GAME, null);
        }
        if (VISIBLE_HIDE_HANDLE.contains(x, y)) {
            return new Hit(HitKind.HIDE_HANDLE, null);
        }
        if (CHEAT_HANDLE.contains(x, y)) {
            return new Hit(HitKind.CHEAT_HANDLE, null);
        }
        for (Game2ApkConfig.ButtonConfig button : config.buttons) {
            NormalizedRect rect = layout.buttonRect(button.id);
            if (rect != null && rect.contains(x, y)) {
                return new Hit(HitKind.BUTTON, button);
            }
        }
        return new Hit(HitKind.GAME, null);
    }

    private RectF toPixels(NormalizedRect normalized) {
        return new RectF(normalized.left * getWidth(), normalized.top * getHeight(),
                normalized.right * getWidth(), normalized.bottom * getHeight());
    }

    private float normalizedX(float x) {
        return getWidth() == 0 ? 0.0f : x / getWidth();
    }

    private float normalizedY(float y) {
        return getHeight() == 0 ? 0.0f : y / getHeight();
    }

    private long eventTime(MotionEvent event) {
        long time = event.getEventTime();
        return time > 0L ? time : SystemClock.uptimeMillis();
    }

    private int withOpacity(int color, float factor) {
        int alpha = Math.round(Color.alpha(color) * opacity * factor);
        return Color.argb(alpha, Color.red(color), Color.green(color), Color.blue(color));
    }

    @Override
    protected void onDetachedFromWindow() {
        releaseAllInput();
        super.onDetachedFromWindow();
    }
}
