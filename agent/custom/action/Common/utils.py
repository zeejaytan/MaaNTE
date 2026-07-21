import cv2
import time
import numpy as np

# GFN 云游戏放宽：串流画面模板分数整体偏低约 0.1~0.15，云端模式下统一下调模板匹配阈值。
# 导入做保护：is_cloud_mode 依赖 Windows-only 的 win32_process；非 Windows 环境回退为桌面行为。
try:
    from utils.win32_process import is_cloud_mode
except Exception:  # pragma: no cover - 非 Windows / 导入失败时回退

    def is_cloud_mode():
        return False


CLOUD_THRESHOLD_RELAX = 0.15
CLOUD_THRESHOLD_FLOOR = 0.40


def effective_match_threshold(min_similarity):
    """云游戏模式下放宽模板匹配阈值，并设下限以避免误匹配。"""
    if is_cloud_mode():
        return max(CLOUD_THRESHOLD_FLOOR, min_similarity - CLOUD_THRESHOLD_RELAX)
    return min_similarity


def get_image(controller):
    job = controller.post_screencap()
    job.wait()
    img = controller.cached_image
    return img


def click_rect(controller, rect, delay=0.001):
    x, y, w, h = rect
    cx = x + w // 2
    cy = y + h // 2
    controller.post_touch_down(cx, cy).wait()
    time.sleep(delay)
    controller.post_touch_up().wait()


def click_rect_multiple(controller, rect, repeat=3):
    """点击多次以确保可靠性"""
    x, y, w, h = rect
    cx = x + w // 2
    cy = y + h // 2
    for _ in range(repeat):
        controller.post_touch_down(cx, cy).wait()
        time.sleep(0.05)
        controller.post_touch_up().wait()


def match_template_in_region(
    img, region, template, min_similarity=0.8, green_mask=False
):
    if img is None or not isinstance(img, np.ndarray):
        return False, 0.0, 0, 0

    x1, y1, w, h = region
    x2, y2 = x1 + w, y1 + h

    h, w = img.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)

    if x2 <= x1 or y2 <= y1:
        return False, 0.0, 0, 0

    roi = img[y1:y2, x1:x2]

    if len(roi.shape) == 3 and roi.shape[2] == 4:
        roi = cv2.cvtColor(roi, cv2.COLOR_BGRA2BGR)

    if green_mask:
        lower_green = np.array([0, 255, 0], dtype=np.uint8)
        upper_green = np.array([0, 255, 0], dtype=np.uint8)
        mask = cv2.bitwise_not(cv2.inRange(template, lower_green, upper_green))
        res = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED, mask=mask)

    else:
        res = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)

    res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
    res[(res < -1e-6) | (res > 1.0 + 1e-6)] = -1.0
    np.clip(res, 0.0, 1.0, out=res)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

    threshold = effective_match_threshold(min_similarity)
    if max_val >= threshold:
        return True, max_val, x1 + max_loc[0], y1 + max_loc[1]
    return False, max_val, 0, 0
