package com.game2apk.rpgmv;

/** A rectangle in normalized screen coordinates, independent of 816x624. */
public final class NormalizedRect {
    public final float left;
    public final float top;
    public final float right;
    public final float bottom;

    public NormalizedRect(float left, float top, float right, float bottom) {
        if (left < 0.0f || top < 0.0f || right > 1.0f || bottom > 1.0f
                || right <= left || bottom <= top) {
            throw new IllegalArgumentException("rectangle must be within normalized screen coordinates");
        }
        this.left = left;
        this.top = top;
        this.right = right;
        this.bottom = bottom;
    }

    public static NormalizedRect fromXYWH(float x, float y, float width, float height) {
        return new NormalizedRect(x, y, x + width, y + height);
    }

    public boolean contains(float x, float y) {
        return x >= left && x <= right && y >= top && y <= bottom;
    }

    public float width() {
        return right - left;
    }

    public float height() {
        return bottom - top;
    }
}
