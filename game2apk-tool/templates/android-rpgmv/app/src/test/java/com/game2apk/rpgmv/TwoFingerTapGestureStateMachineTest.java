package com.game2apk.rpgmv;

import org.junit.Test;

import static org.junit.Assert.assertEquals;

public final class TwoFingerTapGestureStateMachineTest {
    @Test
    public void gameAreaTwoFingerTapCancelsOnceAfterBothLift() {
        TwoFingerTapGestureStateMachine taps = new TwoFingerTapGestureStateMachine(250L, 24.0f);
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.NONE,
                taps.onPointerDown(1, TwoFingerTapGestureStateMachine.Region.GAME, 100, 100, 0));
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.SECOND_FINGER,
                taps.onPointerDown(2, TwoFingerTapGestureStateMachine.Region.GAME, 700, 500, 80));
        taps.onPointerMove(1, 101, 101, 100);
        taps.onPointerMove(2, 701, 501, 100);
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.NONE, taps.onPointerUp(1, 150));
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.CANCEL, taps.onPointerUp(2, 180));
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.NONE,
                taps.onPointerUp(2, 200));
    }

    @Test
    public void controlAreaTwoFingerInputNeverCancels() {
        TwoFingerTapGestureStateMachine taps = new TwoFingerTapGestureStateMachine(250L, 24.0f);
        taps.onPointerDown(1, TwoFingerTapGestureStateMachine.Region.CONTROL, 10, 10, 0);
        taps.onPointerDown(2, TwoFingerTapGestureStateMachine.Region.CONTROL, 700, 500, 80);
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.NONE, taps.onPointerUp(1, 120));
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.NONE, taps.onPointerUp(2, 140));

        taps.onPointerDown(3, TwoFingerTapGestureStateMachine.Region.GAME, 10, 10, 200);
        taps.onPointerDown(4, TwoFingerTapGestureStateMachine.Region.CONTROL, 20, 20, 220);
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.NONE, taps.onPointerUp(3, 260));
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.NONE, taps.onPointerUp(4, 280));
    }

    @Test
    public void movementTimeoutAndThirdPointerInvalidateCandidate() {
        TwoFingerTapGestureStateMachine moved = new TwoFingerTapGestureStateMachine(250L, 24.0f);
        moved.onPointerDown(1, TwoFingerTapGestureStateMachine.Region.GAME, 10, 10, 0);
        moved.onPointerMove(1, 40, 10, 20);
        moved.onPointerDown(2, TwoFingerTapGestureStateMachine.Region.GAME, 100, 100, 40);
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.NONE, moved.onPointerUp(1, 80));
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.NONE, moved.onPointerUp(2, 90));

        TwoFingerTapGestureStateMachine late = new TwoFingerTapGestureStateMachine(250L, 24.0f);
        late.onPointerDown(1, TwoFingerTapGestureStateMachine.Region.GAME, 10, 10, 0);
        late.onPointerDown(2, TwoFingerTapGestureStateMachine.Region.GAME, 100, 100, 300);
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.NONE, late.onPointerUp(1, 350));
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.NONE, late.onPointerUp(2, 360));

        TwoFingerTapGestureStateMachine controlMove = new TwoFingerTapGestureStateMachine(250L, 24.0f);
        controlMove.onPointerDown(1, TwoFingerTapGestureStateMachine.Region.GAME, 10, 10, 0);
        controlMove.onPointerDown(2, TwoFingerTapGestureStateMachine.Region.GAME, 100, 100, 30);
        controlMove.invalidateCandidate();
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.NONE, controlMove.onPointerUp(1, 40));
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.NONE, controlMove.onPointerUp(2, 50));

        TwoFingerTapGestureStateMachine third = new TwoFingerTapGestureStateMachine(250L, 24.0f);
        third.onPointerDown(1, TwoFingerTapGestureStateMachine.Region.GAME, 10, 10, 0);
        third.onPointerDown(2, TwoFingerTapGestureStateMachine.Region.GAME, 100, 100, 30);
        third.onThreeFingerDetected();
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.NONE, third.onPointerUp(1, 40));
        assertEquals(TwoFingerTapGestureStateMachine.Outcome.NONE, third.onPointerUp(2, 50));
    }
}
