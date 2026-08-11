package com.game2apk.rpgmv;

import android.content.Context;
import android.content.DialogInterface;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.os.SystemClock;
import android.text.InputType;
import android.view.MotionEvent;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;
import android.app.AlertDialog;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
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
    private static final NormalizedRect LAYOUT_HANDLE =
            NormalizedRect.fromXYWH(0.79f, 0.02f, 0.065f, 0.065f);
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
        LAYOUT_HANDLE,
        EDIT_BUTTON,
        PASSIVE,
        THREE_FINGER
    }

    private enum HitKind {
        BUTTON,
        HIDE_HANDLE,
        RECOVERY_HANDLE,
        CHEAT_HANDLE,
        LAYOUT_HANDLE,
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
        private final float startX;
        private final float startY;

        private NativeTouchObservation(int takeoverReason, int pointerId, Hit hit,
                                       float startX, float startY) {
            this.takeoverReason = takeoverReason;
            this.pointerId = pointerId;
            this.hit = hit;
            this.startX = startX;
            this.startY = startY;
        }

        private static NativeTouchObservation none() {
            return new NativeTouchObservation(0, -1, null, 0.0f, 0.0f);
        }
    }

    private final Game2ApkConfig config;
    private final KeySink keySink;
    private final OverlayStateStore stateStore;
    private OverlayLayout layout;
    private final List<Game2ApkConfig.ButtonConfig> buttons = new ArrayList<>();
    private float opacity;
    private final OverlayVisibilityStateMachine visibility;
    private final KeyPulseStateMachine pulses;
    private final HeldKeyStateMachine held = new HeldKeyStateMachine();
    private final TwoFingerTapGestureStateMachine twoFinger;
    private final Map<Integer, PointerKind> pointerKinds = new HashMap<>();
    private final Map<Integer, Game2ApkConfig.ButtonConfig> buttonsByPointer = new HashMap<>();
    private final Map<Integer, Float> dragStartX = new HashMap<>();
    private final Map<Integer, Float> dragStartY = new HashMap<>();
    private final Map<Integer, NormalizedRect> dragStartRect = new HashMap<>();
    private final Map<Integer, Boolean> dragMoved = new HashMap<>();
    private boolean nativeGameTracking;
    private boolean editMode;
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
        this.buttons.addAll(state.buttons == null || state.buttons.isEmpty()
                ? config.buttons : state.buttons);
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
        for (Game2ApkConfig.ButtonConfig button : buttons) {
            if (!button.visible) {
                continue;
            }
            NormalizedRect normalized = layout.buttonRect(button.id);
            if (normalized != null) {
                drawButton(canvas, normalized, button.label);
            }
        }
        drawHandle(canvas, VISIBLE_HIDE_HANDLE, "-");
        drawHandle(canvas, LAYOUT_HANDLE, "\u5e03\u5c40");
        if (editMode) {
            textPaint.setTextAlign(Paint.Align.LEFT);
            textPaint.setTextSize(Math.max(11.0f, getHeight() * 0.022f));
            textPaint.setColor(withOpacity(Color.WHITE, 0.92f));
            canvas.drawText("\u5e03\u5c40\u7f16\u8f91\uff1a\u62d6\u52a8\u6309\u952e\uff0c\u70b9\u51fb\u6309\u952e\u7f16\u8f91",
                    Math.max(8.0f, getWidth() * 0.02f), Math.max(20.0f, getHeight() * 0.055f), textPaint);
        }
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
                            TAKEOVER_THREE_OR_MORE, pointerId, null,
                            event.getX(index), event.getY(index));
                }
                Hit hit = hitTest(normalizedX(event.getX(index)), normalizedY(event.getY(index)));
                TwoFingerTapGestureStateMachine.Region region = hit.kind == HitKind.GAME
                        ? TwoFingerTapGestureStateMachine.Region.GAME
                        : TwoFingerTapGestureStateMachine.Region.CONTROL;
                TwoFingerTapGestureStateMachine.Outcome outcome = twoFinger.onPointerDown(
                        pointerId, region, event.getX(index), event.getY(index), now);
                scheduleVisibilityCheck();
                if (hit.kind != HitKind.GAME) {
                    return new NativeTouchObservation(TAKEOVER_CONTROL, pointerId, hit,
                            event.getX(index), event.getY(index));
                }
                if (outcome == TwoFingerTapGestureStateMachine.Outcome.SECOND_FINGER) {
                    return new NativeTouchObservation(TAKEOVER_GAME_TWO_FINGER, pointerId, hit,
                            event.getX(index), event.getY(index));
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
            registerControlPointer(observation.pointerId, observation.hit,
                    observation.startX, observation.startY);
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
                moveEditPointers(event);
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
            registerControlPointer(pointerId, hit, event.getX(index), event.getY(index));
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
        } else if (kind == PointerKind.EDIT_BUTTON) {
            finishEditPointer(pointerId);
        } else if (kind == PointerKind.HIDE_HANDLE) {
            setHidden(true);
        } else if (kind == PointerKind.RECOVERY_HANDLE) {
            if (visibility.restoreByHandle()) {
                stateStore.saveHidden(false);
            }
        } else if (kind == PointerKind.CHEAT_HANDLE) {
            keySink.openCheatPanel();
        } else if (kind == PointerKind.LAYOUT_HANDLE) {
            showLayoutMenu();
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
            dragStartX.clear();
            dragStartY.clear();
            dragStartRect.clear();
            dragMoved.clear();
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
                moveEditPointers(event);
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
        registerControlPointer(pointerId, hit, event.getX(index), event.getY(index));
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
        } else if (kind == PointerKind.EDIT_BUTTON) {
            finishEditPointer(pointerId);
        } else if (kind == PointerKind.HIDE_HANDLE) {
            setHidden(true);
        } else if (kind == PointerKind.RECOVERY_HANDLE) {
            if (visibility.restoreByHandle()) {
                stateStore.saveHidden(false);
            }
        } else if (kind == PointerKind.CHEAT_HANDLE) {
            keySink.openCheatPanel();
        } else if (kind == PointerKind.LAYOUT_HANDLE) {
            showLayoutMenu();
        }
        visibility.onPointerUp(pointerId);
        tickVisibility(now);
        if (event.getActionMasked() == MotionEvent.ACTION_UP) {
            pointerKinds.clear();
            buttonsByPointer.clear();
            dragStartX.clear();
            dragStartY.clear();
            dragStartRect.clear();
            dragMoved.clear();
        }
    }

    private void registerControlPointer(int pointerId, Hit hit, float startX, float startY) {
        if (hit == null) {
            pointerKinds.put(pointerId, PointerKind.PASSIVE);
            return;
        }
        switch (hit.kind) {
            case BUTTON:
                if (editMode) {
                    pointerKinds.put(pointerId, PointerKind.EDIT_BUTTON);
                    buttonsByPointer.put(pointerId, hit.button);
                    dragStartX.put(pointerId, startX);
                    dragStartY.put(pointerId, startY);
                    NormalizedRect startRect = layout.buttonRect(hit.button.id);
                    if (startRect != null) {
                        dragStartRect.put(pointerId, startRect);
                    }
                    dragMoved.put(pointerId, false);
                    break;
                }
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
            case LAYOUT_HANDLE:
                pointerKinds.put(pointerId, PointerKind.LAYOUT_HANDLE);
                break;
            case GAME:
            default:
                pointerKinds.put(pointerId, PointerKind.PASSIVE);
                break;
        }
    }

    private void moveEditPointers(MotionEvent event) {
        if (!editMode || event == null || pointerKinds.isEmpty()) {
            return;
        }
        for (Map.Entry<Integer, PointerKind> entry : pointerKinds.entrySet()) {
            if (entry.getValue() != PointerKind.EDIT_BUTTON) {
                continue;
            }
            int pointerId = entry.getKey();
            int index = event.findPointerIndex(pointerId);
            Game2ApkConfig.ButtonConfig button = buttonsByPointer.get(pointerId);
            NormalizedRect start = dragStartRect.get(pointerId);
            if (index < 0 || button == null || start == null) {
                continue;
            }
            float dx = normalizedX(event.getX(index)) - normalizedX(dragStartX.get(pointerId));
            float dy = normalizedY(event.getY(index)) - normalizedY(dragStartY.get(pointerId));
            if (Math.abs(dx) < 0.0005f && Math.abs(dy) < 0.0005f) {
                continue;
            }
            NormalizedRect candidate = movedRect(start, dx, dy);
            try {
                layout = layout.withButtonRect(button.id, candidate);
                if (Math.abs(dx) > 0.008f || Math.abs(dy) > 0.008f) {
                    dragMoved.put(pointerId, true);
                }
                invalidate();
            } catch (IllegalArgumentException ignored) {
                // Do not allow a drag to overlap another control. The last
                // valid position remains active and can still be saved.
            }
        }
    }

    private NormalizedRect movedRect(NormalizedRect start, float dx, float dy) {
        float left = clamp(start.left + dx, 0.0f, 1.0f - start.width());
        float top = clamp(start.top + dy, 0.0f, 1.0f - start.height());
        return NormalizedRect.fromXYWH(left, top, start.width(), start.height());
    }

    private static float clamp(float value, float min, float max) {
        return Math.max(min, Math.min(max, value));
    }

    private void finishEditPointer(int pointerId) {
        Game2ApkConfig.ButtonConfig button = buttonsByPointer.remove(pointerId);
        boolean moved = Boolean.TRUE.equals(dragMoved.remove(pointerId));
        dragStartX.remove(pointerId);
        dragStartY.remove(pointerId);
        dragStartRect.remove(pointerId);
        if (button == null) {
            return;
        }
        if (moved) {
            persistLayoutState();
        } else {
            showButtonEditor(button);
        }
    }

    private void persistLayoutState() {
        stateStore.saveLayout(layout);
        stateStore.saveButtons(buttons);
        invalidate();
    }

    private void showLayoutMenu() {
        final String[] items = {
                "\u5f00\u542f\u62d6\u52a8\u4e0e\u7f16\u8f91",
                "\u6dfb\u52a0\u81ea\u5b9a\u4e49\u6309\u952e",
                "\u6062\u590d\u9ed8\u8ba4\u5e03\u5c40",
                "\u5173\u95ed\u5e03\u5c40\u7f16\u8f91"
        };
        new AlertDialog.Builder(getContext())
                .setTitle("\u60ac\u6d6e\u6309\u952e\u5e03\u5c40")
                .setItems(items, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        if (which == 0) {
                            editMode = true;
                            invalidate();
                        } else if (which == 1) {
                            addCustomButtonDialog();
                        } else if (which == 2) {
                            resetLayoutEditor();
                        } else {
                            editMode = false;
                            invalidate();
                        }
                    }
                })
                .setNegativeButton("\u53d6\u6d88", null)
                .show();
    }

    private void showButtonEditor(final Game2ApkConfig.ButtonConfig button) {
        if (button == null) return;
        LinearLayout form = new LinearLayout(getContext());
        form.setOrientation(LinearLayout.VERTICAL);
        int padding = Math.max(12, getResources().getDisplayMetrics().densityDpi / 2);
        form.setPadding(padding, padding, padding, 0);

        TextView hint = new TextView(getContext());
        hint.setText(button.id.startsWith("custom_")
                ? "\u81ea\u5b9a\u4e49\u6309\u952e\uff1a\u53ef\u4fee\u6539\u6807\u7b7e\u3001\u952e\u503c\u548c\u6309\u4e0b\u6a21\u5f0f"
                : "\u65b9\u5411\u952e\u4fdd\u6301\u539f\u59cb\u952e\u503c\uff0c\u53f3\u4fa7\u6309\u952e\u53ef\u91cd\u65b0\u7ed1\u5b9a");
        form.addView(hint);

        EditText label = new EditText(getContext());
        label.setHint("\u663e\u793a\u540d\u79f0");
        label.setText(button.label);
        label.setSingleLine(true);
        form.addView(label);

        EditText keyCode = new EditText(getContext());
        keyCode.setHint("\u952e\u503c\uff08KeyboardEvent keyCode\uff09");
        keyCode.setInputType(InputType.TYPE_CLASS_NUMBER);
        keyCode.setText(String.valueOf(button.keyCode));
        form.addView(keyCode);

        Spinner mode = new Spinner(getContext());
        ArrayAdapter<String> modes = new ArrayAdapter<>(getContext(),
                android.R.layout.simple_spinner_dropdown_item,
                new String[]{"tap", "hold"});
        mode.setAdapter(modes);
        mode.setSelection("hold".equals(button.mode) ? 1 : 0);
        form.addView(mode);

        CheckBox visible = new CheckBox(getContext());
        visible.setText("\u663e\u793a\u8fd9\u4e2a\u6309\u952e");
        visible.setChecked(button.visible);
        form.addView(visible);

        boolean directional = "up".equals(button.id) || "down".equals(button.id)
                || "left".equals(button.id) || "right".equals(button.id);
        keyCode.setEnabled(!directional);
        mode.setEnabled(!directional);
        final AlertDialog dialog = new AlertDialog.Builder(getContext())
                .setTitle("\u7f16\u8f91\uff1a" + button.label)
                .setView(form)
                .setNegativeButton("\u53d6\u6d88", null)
                .setPositiveButton("\u4fdd\u5b58", null)
                .create();
        if (button.id.startsWith("custom_")) {
            dialog.setButton(DialogInterface.BUTTON_NEUTRAL, "\u5220\u9664", (d, which) -> {
                removeButton(button.id);
            });
        }
        dialog.setOnShowListener(new DialogInterface.OnShowListener() {
            @Override
            public void onShow(DialogInterface ignored) {
                dialog.getButton(DialogInterface.BUTTON_POSITIVE).setOnClickListener(v -> {
                    String nextLabel = label.getText().toString().trim();
                    if (nextLabel.isEmpty()) nextLabel = button.label;
                    if (nextLabel.length() > 40) nextLabel = nextLabel.substring(0, 40);
                    int nextKey = button.keyCode;
                    try {
                        nextKey = Integer.parseInt(keyCode.getText().toString().trim());
                    } catch (NumberFormatException ignoredNumber) {
                        // Keep the previous valid binding when input is blank.
                    }
                    if (nextKey < 0 || nextKey > 512) nextKey = button.keyCode;
                    String nextMode = directional ? button.mode : (String) mode.getSelectedItem();
                    replaceButton(button.id, button.withValues(nextLabel, nextKey,
                            nextMode, visible.isChecked(), button.rect));
                    dialog.dismiss();
                });
            }
        });
        dialog.show();
    }

    private void replaceButton(String id, Game2ApkConfig.ButtonConfig replacement) {
        for (int index = 0; index < buttons.size(); index++) {
            if (id.equals(buttons.get(index).id)) {
                buttons.set(index, replacement);
                persistLayoutState();
                return;
            }
        }
    }

    private void removeButton(String id) {
        if (!id.startsWith("custom_")) return;
        List<Game2ApkConfig.ButtonConfig> remaining = new ArrayList<>();
        for (Game2ApkConfig.ButtonConfig button : buttons) {
            if (!id.equals(button.id)) remaining.add(button);
        }
        buttons.clear();
        buttons.addAll(remaining);
        Map<String, NormalizedRect> rects = new LinkedHashMap<>();
        for (Game2ApkConfig.ButtonConfig button : buttons) {
            NormalizedRect rect = layout.buttonRect(button.id);
            rects.put(button.id, rect == null ? button.rect : rect);
        }
        try {
            layout = new OverlayLayout(rects);
        } catch (IllegalArgumentException ignored) {
            layout = OverlayLayout.fromConfig(buttons);
        }
        persistLayoutState();
    }

    private void addCustomButtonDialog() {
        if (buttons.size() >= 40) {
            Toast.makeText(getContext(), "\u81ea\u5b9a\u4e49\u6309\u952e\u5df2\u8fbe\u4e0a\u9650", Toast.LENGTH_SHORT).show();
            return;
        }
        final EditText label = new EditText(getContext());
        label.setHint("\u6309\u952e\u540d\u79f0\uff08\u4f8b\u5982\uff1a\u5feb\u6377\u952e\uff09");
        label.setSingleLine(true);
        final EditText keyCode = new EditText(getContext());
        keyCode.setHint("\u952e\u503c\uff08\u9ed8\u8ba4 65=A\uff09");
        keyCode.setInputType(InputType.TYPE_CLASS_NUMBER);
        keyCode.setText("65");
        LinearLayout form = new LinearLayout(getContext());
        form.setOrientation(LinearLayout.VERTICAL);
        int padding = Math.max(12, getResources().getDisplayMetrics().densityDpi / 2);
        form.setPadding(padding, padding, padding, 0);
        form.addView(label);
        form.addView(keyCode);
        new AlertDialog.Builder(getContext())
                .setTitle("\u6dfb\u52a0\u81ea\u5b9a\u4e49\u6309\u952e")
                .setView(form)
                .setNegativeButton("\u53d6\u6d88", null)
                .setPositiveButton("\u6dfb\u52a0", (dialog, which) -> {
                    String nextLabel = label.getText().toString().trim();
                    if (nextLabel.isEmpty()) nextLabel = "\u81ea\u5b9a\u4e49";
                    if (nextLabel.length() > 40) nextLabel = nextLabel.substring(0, 40);
                    int nextKey = 65;
                    try {
                        nextKey = Integer.parseInt(keyCode.getText().toString().trim());
                    } catch (NumberFormatException ignored) {}
                    nextKey = Math.max(0, Math.min(512, nextKey));
                    NormalizedRect rect = findAvailableRect();
                    if (rect == null) {
                        Toast.makeText(getContext(), "\u53f3\u4fa7\u6ca1\u6709\u53ef\u7528\u7a7a\u95f4", Toast.LENGTH_SHORT).show();
                        return;
                    }
                    String id = nextCustomId();
                    try {
                        Game2ApkConfig.ButtonConfig button = Game2ApkConfig.ButtonConfig.custom(
                                id, nextLabel, nextKey, "tap", true, rect);
                        buttons.add(button);
                        layout = layout.withButtonRect(id, rect);
                        persistLayoutState();
                    } catch (IllegalArgumentException ignored) {
                        Toast.makeText(getContext(), "\u81ea\u5b9a\u4e49\u6309\u952e\u521b\u5efa\u5931\u8d25", Toast.LENGTH_SHORT).show();
                    }
                })
                .show();
    }

    private String nextCustomId() {
        for (int index = 1; index <= 999; index++) {
            String candidate = "custom_" + index;
            boolean used = false;
            for (Game2ApkConfig.ButtonConfig button : buttons) {
                if (candidate.equals(button.id)) {
                    used = true;
                    break;
                }
            }
            if (!used) return candidate;
        }
        return "custom_" + SystemClock.uptimeMillis();
    }

    private NormalizedRect findAvailableRect() {
        for (int row = 0; row < 8; row++) {
            NormalizedRect candidate = NormalizedRect.fromXYWH(
                    0.68f, 0.12f + row * 0.105f, 0.12f, 0.075f);
            boolean overlap = false;
            for (Game2ApkConfig.ButtonConfig button : buttons) {
                NormalizedRect rect = layout.buttonRect(button.id);
                if (rect != null && overlaps(candidate, rect)) {
                    overlap = true;
                    break;
                }
            }
            if (!overlap) return candidate;
        }
        return null;
    }

    private static boolean overlaps(NormalizedRect left, NormalizedRect right) {
        return left.left < right.right && right.left < left.right
                && left.top < right.bottom && right.top < left.bottom;
    }

    private void resetLayoutEditor() {
        editMode = false;
        buttons.clear();
        buttons.addAll(config.buttons);
        layout = OverlayLayout.fromConfig(buttons);
        persistLayoutState();
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
        dragStartX.clear();
        dragStartY.clear();
        dragStartRect.clear();
        dragMoved.clear();
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
        if (LAYOUT_HANDLE.contains(x, y)) {
            return new Hit(HitKind.LAYOUT_HANDLE, null);
        }
        for (Game2ApkConfig.ButtonConfig button : buttons) {
            if (!button.visible) {
                continue;
            }
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
