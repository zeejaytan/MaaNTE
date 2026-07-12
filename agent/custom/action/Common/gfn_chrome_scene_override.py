import sys

from maa.agent.agent_server import AgentServer
from maa.event_sink import NotificationType
from maa.resource import Resource, ResourceEventSink
from maa.tasker import Tasker, TaskerEventSink

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

# 模块级状态（配合独立 reset 约定）：覆盖只需应用一次；
# 资源重新加载会清空 override，此时由 resource sink 复位标志以便重新应用
_override_applied = False


def _build_gfn_chrome_override(header_height):
    return {
        node_name: {"roi": [x, y + header_height, w, h]}
        for node_name, (x, y, w, h) in _GFN_CHROME_TOP_ANCHORED_ROIS.items()
    }


def _apply_override_if_needed(resource: Resource, trigger: str) -> None:
    """gfn_chrome 会话下向 resource 应用一次性 ROI 下移覆盖。

    通过 Resource.override_pipeline（MaaResourceOverridePipeline）持久覆盖，
    对该 resource 后续所有任务生效，无需在任何任务的 Pipeline 中显式调用。
    幂等：应用成功后置位模块级标志，重复触发直接返回。
    """
    global _override_applied
    if _override_applied:
        return
    if get_game_window_mode is None:
        return

    try:
        mode = get_game_window_mode()
    except Exception:
        logger.exception("gfn_chrome_scene_override 探测窗口模式失败 (trigger=%s)", trigger)
        return

    if mode != GAME_WINDOW_MODE_GFN_CHROME:
        logger.debug(
            "gfn_chrome_scene_override 跳过 (trigger=%s, 当前模式=%s, 非 gfn_chrome)",
            trigger,
            mode,
        )
        return

    override = _build_gfn_chrome_override(GFN_CHROME_HEADER_HEIGHT)
    try:
        ok = resource.override_pipeline(override)
    except Exception:
        logger.exception(
            "gfn_chrome_scene_override 调用 override_pipeline 失败 (trigger=%s)", trigger
        )
        return

    _override_applied = True
    if ok:
        logger.info("gfn_chrome_scene_override 已应用 (trigger=%s): %s", trigger, override)
    else:
        logger.warning(
            "gfn_chrome_scene_override override_pipeline 返回失败 (trigger=%s): %s",
            trigger,
            override,
        )


@AgentServer.tasker_sink()
class GfnChromeSceneOverrideTaskerSink(TaskerEventSink):
    """任务启动时应用覆盖（主触发路径）。

    资源加载发生在 MXU 宿主进程、且早于 agent 依赖安装完成/连接建立
    （实测早约 80 秒），agent 侧的 resource sink 收不到那次事件；
    Tasker.Task.Starting 则在每次任务运行时都会送达 agent，
    经 tasker.resource 同样能拿到 Resource 应用持久覆盖。
    """

    def on_tasker_task(
        self, tasker: Tasker, noti_type: NotificationType, detail
    ):
        if noti_type != NotificationType.Starting:
            return
        try:
            resource = tasker.resource
        except RuntimeError:
            logger.warning("gfn_chrome_scene_override 无法从 tasker 获取 resource")
            return
        _apply_override_if_needed(resource, trigger="tasker_task_starting")


@AgentServer.resource_sink()
class GfnChromeSceneOverrideResourceSink(ResourceEventSink):
    """资源（重新）加载完成时复位并重新应用覆盖（兜底触发路径）。

    资源重新加载会清空既有 override_pipeline 覆盖；若此时 agent 已连接
    并能收到该事件，则复位标志并立即重新应用。
    """

    def on_resource_loading(
        self, resource: Resource, noti_type: NotificationType, detail
    ):
        global _override_applied
        if noti_type != NotificationType.Succeeded:
            return
        _override_applied = False
        _apply_override_if_needed(resource, trigger="resource_loading_succeeded")
