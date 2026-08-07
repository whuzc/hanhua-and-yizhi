package com.game2apk.rpgmv;

import org.junit.Test;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public final class OverlayVisibilityStateMachineTest {
    @Test
    public void handleRestoresHiddenOverlay() {
        OverlayVisibilityStateMachine visibility = new OverlayVisibilityStateMachine(false);
        assertTrue(visibility.hide());
        assertTrue(visibility.isHidden());
        assertTrue(visibility.restoreByHandle());
        assertFalse(visibility.isHidden());
    }

    @Test
    public void threeFingerLongPressRestoresHiddenOverlay() {
        OverlayVisibilityStateMachine visibility = new OverlayVisibilityStateMachine(false);
        visibility.hide();
        visibility.onPointerDown(1, 100L);
        visibility.onPointerDown(2, 120L);
        visibility.onPointerDown(3, 140L);
        assertFalse(visibility.tick(939L));
        assertTrue(visibility.tick(940L));
        assertFalse(visibility.isHidden());
    }

    @Test
    public void releasingOneFingerCancelsLongPress() {
        OverlayVisibilityStateMachine visibility = new OverlayVisibilityStateMachine(true);
        visibility.onPointerDown(1, 100L);
        visibility.onPointerDown(2, 100L);
        visibility.onPointerDown(3, 100L);
        visibility.onPointerUp(2);
        assertFalse(visibility.tick(2000L));
        assertTrue(visibility.isHidden());
    }
}
