package com.game2apk.rpgmv;

import android.content.Context;
import android.view.MotionEvent;
import android.webkit.WebView;
import android.widget.FrameLayout;

/**
 * Keeps ordinary game touches on the WebView's native target. It takes over
 * only after the overlay recognizes a control pointer or an all-game
 * two-finger gesture. The only manual event sent to WebView is one independent
 * ACTION_CANCEL copy; raw game events are never replayed or duplicated.
 */
public final class InputRootLayout extends FrameLayout {
    private WebView webView;
    private OverlayView overlay;
    private boolean manualSequence;

    public InputRootLayout(Context context) {
        super(context);
        setClickable(false);
    }

    public void setWebView(WebView webView) {
        this.webView = webView;
    }

    public void setOverlay(OverlayView overlay) {
        this.overlay = overlay;
    }

    @Override
    public boolean dispatchTouchEvent(MotionEvent event) {
        if (event == null) {
            return false;
        }
        if (manualSequence) {
            if (overlay != null) {
                overlay.handleRootTouch(event);
            }
            if (event.getActionMasked() == MotionEvent.ACTION_UP
                    || event.getActionMasked() == MotionEvent.ACTION_CANCEL) {
                manualSequence = false;
            }
            return true;
        }
        if (overlay != null) {
            OverlayView.NativeTouchObservation observation = overlay.observeNativeTouch(event);
            if (observation.takeoverReason != 0) {
                sendOneCancelToWebView(event);
                manualSequence = true;
                overlay.beginRootTakeover(observation);
                return true;
            }
        }
        return super.dispatchTouchEvent(event);
    }

    private void sendOneCancelToWebView(MotionEvent source) {
        if (webView == null) {
            return;
        }
        MotionEvent cancel = MotionEvent.obtain(source);
        int[] rootLocation = new int[2];
        int[] webLocation = new int[2];
        getLocationOnScreen(rootLocation);
        webView.getLocationOnScreen(webLocation);
        // The source coordinates are local to this root. Convert the copied
        // event to WebView-local coordinates before dispatching ACTION_CANCEL.
        cancel.offsetLocation(rootLocation[0] - webLocation[0], rootLocation[1] - webLocation[1]);
        cancel.setAction(MotionEvent.ACTION_CANCEL);
        try {
            webView.dispatchTouchEvent(cancel);
        } finally {
            cancel.recycle();
        }
    }
}
