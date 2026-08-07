package com.game2apk.rpgmv;

import org.junit.Test;

import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

public final class HeldKeyStateMachineTest {
    @Test
    public void directionsHoldAndReleaseIndependentlyAcrossPointers() {
        HeldKeyStateMachine held = new HeldKeyStateMachine();
        List<KeyAction> first = held.onPointerDown(1, 38);
        assertEquals(1, first.size());
        assertTrue(first.get(0).down);
        assertTrue(held.onPointerDown(2, 39).get(0).down);
        assertEquals(38, held.onPointerUp(1).get(0).keyCode);
        assertTrue(held.onPointerUp(99).isEmpty());
        assertEquals(39, held.onPointerUp(2).get(0).keyCode);
    }

    @Test
    public void duplicatePointerAndReleaseAllDoNotLeakKeys() {
        HeldKeyStateMachine held = new HeldKeyStateMachine();
        held.onPointerDown(1, 38);
        assertTrue(held.onPointerDown(1, 40).isEmpty());
        assertEquals(1, held.releaseAll().size());
        assertEquals(0, held.activePointerCount());
        assertTrue(held.onPointerCancel(99).isEmpty());
    }
}
