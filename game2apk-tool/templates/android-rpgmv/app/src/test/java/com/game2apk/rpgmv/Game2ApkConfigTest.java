package com.game2apk.rpgmv;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

public final class Game2ApkConfigTest {
    private static final String VALID = "{"
            + "\"schemaVersion\":1,"
            + "\"touch\":{\"cancelKeyCode\":27,\"twoFingerWindowMs\":250,\"touchSlopPx\":24},"
            + "\"overlay\":{\"opacity\":0.38,\"hiddenByDefault\":false},"
            + "\"buttons\":["
            + button("left", "L", 37, "hold", 0.04, 0.80)
            + "," + button("up", "U", 38, "hold", 0.15, 0.67)
            + "," + button("down", "D", 40, "hold", 0.15, 0.82)
            + "," + button("right", "R", 39, "hold", 0.26, 0.80)
            + "," + button("confirm", "OK", 13, "tap", 0.67, 0.58)
            + "," + button("cancel", "X", 88, "tap", 0.83, 0.58)
            + "," + button("esc", "ESC", 27, "tap", 0.67, 0.71)
            + "," + button("portrait", "A", 65, "tap", 0.83, 0.71)
            + "]}"
            ;

    private static String button(String id, String label, int keyCode, String mode, double x, double y) {
        return "{\"id\":\"" + id + "\",\"label\":\"" + label
                + "\",\"keyCode\":" + keyCode + ",\"mode\":\"" + mode
                + "\",\"x\":" + x + ",\"y\":" + y
                + ",\"width\":0.10,\"height\":0.10}";
    }

    @Test
    public void parsesFourDirectionsAndFourActions() throws Exception {
        Game2ApkConfig config = Game2ApkConfig.parse(VALID);
        assertEquals(1, config.schemaVersion);
        assertEquals(27, config.touch.cancelKeyCode);
        assertEquals(250, config.touch.twoFingerWindowMs);
        assertEquals(8, config.buttons.size());
        assertEquals(65, find(config, "portrait").keyCode);
        assertEquals("tap", find(config, "portrait").mode);
        assertTrue(find(config, "up").rect.contains(0.16f, 0.68f));
    }

    @Test
    public void legacyTapAndJoystickAreRejected() {
        try {
            Game2ApkConfig.parse(VALID.replace("\"touch\":", "\"joystick\":{},\"touch\":"));
            fail("legacy joystick must fail");
        } catch (Game2ApkConfig.ConfigException e) {
            assertTrue(e.getMessage().contains("legacy tap/joystick"));
        }
    }

    @Test
    public void overlappingButtonsFailExplicitly() {
        String overlap = VALID.replace("\"x\":0.83,\"y\":0.71", "\"x\":0.70,\"y\":0.71");
        try {
            Game2ApkConfig.parse(overlap);
            fail("overlap must fail");
        } catch (Game2ApkConfig.ConfigException e) {
            assertTrue(e.getMessage().contains("overlap"));
        }
    }

    @Test
    public void unknownSchemaFailsExplicitly() {
        try {
            Game2ApkConfig.parse(VALID.replace("\"schemaVersion\":1", "\"schemaVersion\":99"));
            fail("unknown schema must fail");
        } catch (Game2ApkConfig.ConfigException e) {
            assertTrue(e.getMessage().contains("Unsupported game2apk config schemaVersion 99"));
        }
    }

    private static Game2ApkConfig.ButtonConfig find(Game2ApkConfig config, String id) {
        for (Game2ApkConfig.ButtonConfig button : config.buttons) {
            if (id.equals(button.id)) {
                return button;
            }
        }
        throw new AssertionError("missing button " + id);
    }
}
