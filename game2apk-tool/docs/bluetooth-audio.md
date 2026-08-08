# Bluetooth audio notes

The Android template treats RPG Maker MV background music and sound effects as game media:

- `AudioAttributes.USAGE_GAME` and `CONTENT_TYPE_MUSIC` are used for audio focus.
- A long-lived `AUDIOFOCUS_GAIN` is requested while the Activity is in the foreground.
- WebAudio is resumed after a real page gesture, page load, window focus, and audio-focus gain.
- The MV unlock callback is also primed with its zero-length source, which helps WebView route WebAudio to an already-connected Bluetooth headset.
- The template does not request Bluetooth permissions and does not force a Bluetooth route; Android's current system output remains authoritative.

On a phone, connect the headset before launching the APK and verify the system media volume is non-zero. If a headset is connected or disconnected while the game is open, return to the game window once so the focus/visibility resume path runs.
