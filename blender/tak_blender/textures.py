"""Image utilities working on bpy images through numpy (no external packages)."""
import bpy
import numpy as np


def pixels(img):
    """Return the image as a float32 array of shape (height, width, 4)."""
    width, height = img.size
    data = np.empty(width * height * 4, dtype=np.float32)
    img.pixels.foreach_get(data)
    return data.reshape(height, width, 4)


def store(img, array):
    img.pixels.foreach_set(np.ascontiguousarray(array, dtype=np.float32).ravel())
    img.update()


def limit_size(img, max_size):
    """Downscale so the longest side is at most ``max_size`` (power-of-two sources stay square)."""
    width, height = img.size
    longest = max(width, height)
    if longest > max_size:
        img.scale(max(1, round(width * max_size / longest)), max(1, round(height * max_size / longest)))
    return img


def own_copy(img, name):
    """A packed, editable copy so source assets on disk are never modified."""
    copy = img.copy()
    copy.name = name
    if copy.packed_file is None:
        copy.pack()
    return copy


def bleed_alpha(img, threshold=0.02, passes=24):
    """Spread opaque colours into transparent texels so filtering does not pull in white halos."""
    arr = pixels(img)
    rgb, alpha = arr[..., :3].copy(), arr[..., 3]
    known = alpha > threshold
    if known.all() or not known.any():
        return img
    acc = np.where(known[..., None], rgb, 0.0)
    filled = known.copy()
    for _ in range(passes):
        if filled.all():
            break
        total = np.zeros_like(acc)
        count = np.zeros(filled.shape, dtype=np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            total += np.roll(np.roll(acc, dy, 0), dx, 1)
            count += np.roll(np.roll(filled, dy, 0), dx, 1)
        grow = (~filled) & (count > 0)
        acc[grow] = total[grow] / count[grow, None]
        filled |= grow
    mean = rgb[known].mean(axis=0)
    acc[~filled] = mean
    arr[..., :3] = np.where(known[..., None], rgb, acc)
    store(img, arr)
    return img


def scale_rgb(img, factor, saturation=1.0):
    arr = pixels(img)
    rgb = arr[..., :3]
    if saturation != 1.0:
        luma = (rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32))[..., None]
        rgb = luma + (rgb - luma) * saturation
    arr[..., :3] = np.clip(rgb * np.asarray(factor, dtype=np.float32), 0.0, 1.0)
    store(img, arr)
    return img


def set_alpha(img, value=1.0):
    arr = pixels(img)
    arr[..., 3] = value
    store(img, arr)
    return img


def tune_eye(img, sclera_level=0.86, iris_tint=(1.0, 0.64, 0.38), iris_gain=1.25, keep=0.25):
    """Calm the MakeHuman eye texture: a less glowing sclera and a natural brown iris.

    The sclera (bright, desaturated texels) is lowered and warmed slightly. The
    iris of the brown MakeHuman texture is a saturated maroon that reads as red
    in a viewer; its chroma is replaced by a brown hue at the same luminance
    (lifted a little for readability), keeping some of the original fibres.
    """
    arr = pixels(img)
    rgb = arr[..., :3]
    weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    luma = rgb @ weights
    sat = rgb.max(axis=2) - rgb.min(axis=2)
    sclera = np.clip((luma - 0.45) / 0.25, 0, 1) * np.clip(1 - sat / 0.25, 0, 1)
    iris = np.clip((sat - 0.12) / 0.15, 0, 1)
    tint = np.array(iris_tint, dtype=np.float32)
    tint = tint / float(tint @ weights)
    iris_rgb = np.clip(luma[..., None] * iris_gain, 0, 1) * tint
    iris_rgb = iris_rgb * (1 - keep) + rgb * keep
    rgb = rgb * (1 - iris[..., None]) + iris_rgb * iris[..., None]
    sclera_rgb = rgb * sclera_level * np.array([1.0, 0.985, 0.96], dtype=np.float32)
    rgb = rgb * (1 - sclera[..., None]) + sclera_rgb * sclera[..., None]
    arr[..., :3] = np.clip(rgb, 0, 1)
    arr[..., 3] = 1.0
    store(img, arr)
    return img
