import sys

from maa.agent.agent_server import AgentServer
from maa.event_sink import NotificationType
from maa.resource import Resource, ResourceEventSink

from utils.logger import logger

if sys.platform == "win32":
    try:
        from utils.win32_process import (
            GAME_WINDOW_MODE_GFN_CHROME,
            GFN_CHROME_HEADER_HEIGHT,
            get_game_window_mode,
        )
    except Exception:
        get_game_window_mode = None
        GAME_WINDOW_MODE_GFN_CHROME = "gfn_chrome"
        GFN_CHROME_HEADER_HEIGHT = 37
else:
    get_game_window_mode = None
    GAME_WINDOW_MODE_GFN_CHROME = "gfn_chrome"
    GFN_CHROME_HEADER_HEIGHT = 37

# 贴近顶部的基础设施级识别节点：GFN Chrome 头部平移（见
# gfn-chrome-window-resize-prd.md §5.2）会使其结构性失效（EscMenuButton/
# TasksMenuButton 组成 InWorld 判定，是几乎所有任务共用的场景门禁）。
# 原始 ROI 取自各自的节点定义文件，仅在 gfn_chrome 会话下于 y 方向整体
# 下移 GFN_CHROME_HEADER_HEIGHT px，不修改任何 Pipeline JSON 文件本身。
_GFN_CHROME_TOP_ANCHORED_ROIS = {
    # Common/Button/InWorld/EscMenuButton.json
    "EscMenuButton": (1208, 5, 60, 60),
    # Common/Button/InWorld/TasksMenuButton.json
    "TasksMenuButton": (0, 105, 60, 60),
    # Common/Button/InWorld/ExitButton.json
    "ExitButton": (20, 5, 60, 60),
}

_override_applied = False


def _build_gfn_chrome_override(header_height):
    return {
        node_name: {"roi": [x, y + header_height, w, h]}
        for node_name, (x, y, w, h) in _GFN_CHROME_TOP_ANCHORED_ROIS.items()
    }


@AgentServer.resource_sink()
class GfnChromeSceneOverrideSink(ResourceEventSink):
    """gfn_chrome 会话下，资源加载完成后一次性下移基础场景检测节点的 ROI。

    通过 Resource.override_pipeline（MaaResourceOverridePipeline）持久覆盖，
    对该 resource 后续所有任务生效，无需在任何任务的 Pipeline 中显式调用。
    """

    def on_resource_loading(
        self, resource: Resource, noti_type: NotificationType, detail
    ):
        global _override_applied
        if noti_type != NotificationType.Succeeded or _override_applied:
            return
        if get_game_window_mode is None:
            return

        try:
            mode = get_game_window_mode()
        except Exception:
            logger.exception("gfn_chrome_scene_override 探测窗口模式失败")
            return

        if mode != GAME_WINDOW_MODE_GFN_CHROME:
            logger.debug(
                "gfn_chrome_scene_override 跳过（当前模式=%s，非 gfn_chrome）", mode
            )
            return

        override = _build_gfn_chrome_override(GFN_CHROME_HEADER_HEIGHT)
        try:
            ok = resource.override_pipeline(override)
        except Exception:
            logger.exception("gfn_chrome_scene_override 调用 override_pipeline 失败")
            return

        _override_applied = True
        if ok:
            logger.info("gfn_chrome_scene_override 已应用: %s", override)
        else:
            logger.warning("gfn_chrome_scene_override override_pipeline 返回失败: %s", override)
