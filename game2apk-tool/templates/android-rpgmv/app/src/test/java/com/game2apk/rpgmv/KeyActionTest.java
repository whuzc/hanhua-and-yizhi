package com.game2apk.rpgmv;

import org.junit.Test;

import java.util.ArrayList;
import java.util.List;

import static org.junit.Assert.assertEquals;

public final class KeyActionTest {
    @Test
    public void keyDownAndKeyUpCanBeAppliedToSink() {
        List<String> events = new ArrayList<>();
        KeySink sink = new KeySink() {
            @Override
            public void keyDown(int keyCode) {
                events.add("down:" + keyCode);
            }

            @Override
            public void keyUp(int keyCode) {
                events.add("up:" + keyCode);
            }
        };

        KeyActions.apply(KeyActions.press(65), sink);
        assertEquals("down:65", events.get(0));
        assertEquals("up:65", events.get(1));
    }
}
