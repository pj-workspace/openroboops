"use client";

import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";

type Locale = "en" | "zh-CN";
type Variables = Record<string, string | number>;

const chinese: Record<string, string> = {
  "Switch language": "切换语言",
  "Open source robot operations": "开源机器人运维平台",
  "Loading control plane…": "正在加载控制平面…",
  "Initialize OpenRoboOps": "初始化 OpenRoboOps",
  "Welcome back": "欢迎回来",
  "Use the one-time token printed by the API container, then create the administrator account.": "使用 API 容器生成的一次性令牌，然后创建管理员账号。",
  "Sign in to access fleet telemetry, datasets, and safety-gated operations.": "登录后管理机器人遥测、数据集和安全运维操作。",
  "Bootstrap token": "初始化令牌",
  Username: "用户名",
  Password: "密码",
  "Working…": "处理中…",
  "Create administrator": "创建管理员",
  "Sign in": "登录",
  "Authentication failed": "认证失败",
  "Fleet control plane": "机器人集群控制平面",
  Robots: "机器人",
  "Add robot": "添加机器人",
  Administrator: "管理员",
  "Sign out": "退出登录",
  Online: "在线",
  Offline: "离线",
  "Observe only": "仅观测",
  adapter: "适配器",
  "last seen": "最后在线",
  "Probe connection": "检测连接",
  "Probing…": "检测中…",
  Overview: "概览",
  Data: "数据",
  Collection: "采集",
  Operations: "运维",
  Audit: "审计",
  "Register your first robot": "注册第一台机器人",
  "Start with the simulator or add an A2D robot in observe-only mode.": "可先使用模拟器，或以仅观测模式添加 A2D 机器人。",
  "Fleet registry": "机器人注册表",
  "Add a robot": "添加机器人",
  Name: "名称",
  Model: "型号",
  Adapter: "适配器",
  Simulator: "模拟器",
  Seed: "随机种子",
  "SSH host": "SSH 地址",
  "SSH port": "SSH 端口",
  "SSH username": "SSH 用户名",
  "Data root": "数据根目录",
  "Pinned known_hosts file": "固定 known_hosts 文件",
  "Private key file": "私钥文件",
  "New robots are observe-only. Credentials remain server-side and are never returned to this browser.": "新机器人默认仅观测。凭证只保存在服务端，绝不会返回浏览器。",
  Cancel: "取消",
  "Adding…": "添加中…",
  Battery: "电量",
  Unavailable: "不可用",
  Charging: "充电中",
  "Not charging": "未充电",
  "Data disk": "数据磁盘",
  free: "可用",
  used: "已用",
  of: "总计",
  "Collection stack": "采集栈",
  Ready: "就绪",
  "Not ready": "未就绪",
  "Recording now": "正在录制",
  Idle: "空闲",
  "Collision protection": "碰撞保护",
  Enabled: "已启用",
  "Not confirmed": "未确认",
  Level: "等级",
  "PICO / VR": "PICO / VR",
  Active: "活跃",
  Unknown: "未知",
  "Live input detected": "已检测到实时输入",
  "No live input detected": "未检测到实时输入",
  "Detection unavailable": "暂时无法探测",
  "Reset poses": "复位姿态",
  "Arm readiness": "机械臂就绪状态",
  "Left arm": "左臂",
  "Right arm": "右臂",
  "Saved reset pose available": "已有保存的复位姿态",
  "No saved reset pose": "尚未保存复位姿态",
  Configured: "已配置",
  Services: "服务",
  "Robot-side health": "机器人端健康状态",
  "No service telemetry reported.": "尚未上报服务遥测。",
  Alerts: "告警",
  "Active conditions": "当前状态",
  Clear: "正常",
  "No active alerts reported by the adapter.": "适配器未报告活动告警。",
  "PICO/VR input is active; motion commands are blocked": "PICO/VR 输入活跃；运动命令已被阻止。",
  "PICO/VR activity is unknown; motion commands fail closed": "无法确认 PICO/VR 活跃状态；运动命令按安全策略拒绝。",
  "VR activity is unknown; motion commands fail closed": "无法确认 PICO/VR 活跃状态；运动命令按安全策略拒绝。",
  "Body parameters": "本体参数",
  "Reported configuration": "上报配置",
  values: "项",
  "No body parameters reported.": "尚未上报本体参数。",
  "Persisted telemetry": "持久化遥测",
  "Status history": "状态历史",
  snapshots: "条快照",
  "Battery history": "电量历史",
  "battery unavailable": "电量不可用",
  "Status snapshots will appear after the worker persists telemetry.": "后台任务持久化遥测后将在此显示状态快照。",
  "Dataset catalog": "数据集目录",
  Episodes: "采集片段",
  "Indexed directly from each episode's meta_info.json.": "直接从每个采集片段的 meta_info.json 建立索引。",
  "All episodes": "全部片段",
  Aligned: "已对齐",
  Valid: "有效",
  Warnings: "警告",
  Synced: "已同步",
  "Not synced": "未同步",
  "Scanning…": "扫描中…",
  Rescan: "重新扫描",
  Episode: "采集片段",
  Task: "任务",
  Channels: "通道",
  "Size / duration": "大小 / 时长",
  Quality: "质量",
  Sync: "同步",
  files: "个文件",
  "and {count} more": "另有 {count} 个",
  sec: "秒",
  aligned: "已对齐",
  "not aligned": "未对齐",
  Missing: "缺失",
  "No episodes match this filter.": "没有符合筛选条件的采集片段。",
  Manage: "管理",
  "Dataset management": "数据管理",
  "Episode details": "片段详情",
  "Cancel the active sync before deleting data.": "请先取消正在进行的同步任务，再删除数据。",
  "Central synchronized copies cannot be deleted in v0.1.": "v0.1 暂不支持删除已同步到中心节点的数据副本。",
  "Episode data was deleted and audited.": "采集片段已永久删除并记录审计。",
  "Deletion failed": "删除失败",
  "Deleting…": "正在删除…",
  "Loading preview…": "正在加载预览…",
  "Syncing…": "正在同步…",
  "Cancelling…": "正在取消…",
  Collected: "采集于",
  "Last scanned": "最后扫描",
  "Local orchestration": "本地采集编排",
  "Start collection": "开始采集",
  "Allocates local task/job IDs and preserves the collector UID. Data is retained until an administrator explicitly reviews it.": "分配本地任务 ID 并保留采集器 UID；数据会持续保留，直到管理员明确审核。",
  "Task name": "任务名称",
  "Planned duration": "计划时长",
  "30 seconds": "30 秒",
  "1 minute": "1 分钟",
  "5 minutes": "5 分钟",
  "15 minutes": "15 分钟",
  "Starting…": "启动中…",
  "Disabled while this robot is observe-only.": "机器人处于仅观测模式时不可用。",
  Sessions: "采集会话",
  "Recent collection jobs": "最近采集任务",
  "local job": "本地任务",
  manual: "手动",
  Stop: "停止",
  "No collection sessions yet.": "暂无采集会话。",
  "Collection review": "采集结果审核",
  Status: "状态",
  Size: "大小",
  Duration: "时长",
  "Indexing…": "正在索引…",
  Pending: "待处理",
  "Preview unavailable": "预览不可用",
  "Keep data": "保留数据",
  Kept: "已保留",
  "Delete data": "删除数据",
  "Confirm UID": "确认 UID",
  "Permanently delete": "永久删除",
  "This permanently deletes the robot-side source data. Type the full UID and administrator password to continue.": "此操作会永久删除机器人端源数据。请输入完整 UID 和管理员密码后继续。",
  "Recorder was force-stopped; source data was preserved.": "已强制停止采集器，源数据保持不变。",
  "Force stop failed": "强制停止失败",
  "Collection was kept.": "采集数据已保留。",
  "Collection data was deleted and audited.": "采集数据已删除并记录审计。",
  "Review action failed": "审核操作失败",
  "Force stop": "强制停止",
  Review: "审核",
  "Collector vision": "采集端视觉",
  "Camera preview": "相机预览",
  "Frames are proxied through OpenRoboOps; robot addresses and credentials stay server-side.": "画面由 OpenRoboOps 安全代理；机器人地址和凭证始终保留在服务端。",
  Refresh: "刷新",
  "Camera preview unavailable": "相机预览不可用",
  "Head camera": "头部相机",
  "Left hand camera": "左手相机",
  "Right hand camera": "右手相机",
  Captured: "采集于",
  "Capture time unavailable": "采集时间未知",
  "Stale frame": "历史画面",
  Stale: "已过期",
  Live: "实时",
  "Real-time": "实时视频",
  "No live frame": "暂无实时画面",
  "No camera previews were reported by the collector.": "采集端没有上报相机预览。",
  "Stale means the collector has not written a recent frame; it is not a live view.": "“已过期”表示采集端近期没有写入新画面，当前显示并非实时图像。",
  "The head camera is real-time. Hand cameras appear when the collector writes current frames; historical frames are hidden.": "头部相机为实时视频；左右手相机在采集端写入当前帧后显示，历史画面已隐藏。",
  "Safety gate": "安全门禁",
  "Authorize one operation": "授权单次操作",
  "A fresh password check creates a 60-second exclusive control lease. Robot status must be online, fresh, idle, collision-protected, and positively free of VR input.": "重新验证密码后创建 60 秒独占控制租约。机器人必须在线、状态新鲜、空闲、碰撞保护开启且确认无 VR 输入。",
  "Administrator password": "管理员密码",
  "I am physically present, the work area is clear, and the physical emergency stop is reachable.": "我已在现场，工作区域安全，并且可立即操作物理急停。",
  "Software controls are not an emergency stop. Keep the physical emergency stop available for every real movement test.": "软件控制不是急停。每次真实运动测试都必须保证物理急停可用。",
  "Preset operations": "预设运维操作",
  "Command catalog": "命令目录",
  "Clear faults": "清除故障",
  "Clear recoverable faults without motion.": "清除无需运动即可恢复的故障。",
  "Restart collection stack": "重启采集栈",
  "Restart the robot-side collection services.": "重启机器人端采集服务。",
  "Save reset pose": "保存复位姿态",
  "Save the current arm pose as its reset target.": "将当前机械臂姿态保存为复位目标。",
  "Reset one arm": "单臂复位",
  "Move one arm to its previously saved pose.": "将单侧机械臂移动到已保存的复位姿态。",
  "Not enabled in this deployment profile.": "当前部署配置未启用。",
  "No saved {side} arm pose is available.": "尚无可用的{side}臂复位姿态。",
  "Authorizing…": "授权中…",
  Execute: "执行",
  "Command history": "命令历史",
  "Latest results": "最近结果",
  "No commands have been requested.": "尚未请求任何命令。",
  "Immutable history": "不可篡改历史",
  "Operations audit": "操作审计",
  records: "条记录",
  "control plane": "控制平面",
  "No audit records for this robot.": "该机器人暂无审计记录。",
  "Connection probe completed.": "连接检测完成。",
  "Probe failed": "连接检测失败",
  "Robot registered in observe-only mode.": "机器人已以仅观测模式注册。",
  "Could not add robot": "无法添加机器人",
};

type I18nValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (source: string, variables?: Variables) => string;
};

const I18nContext = createContext<I18nValue>({
  locale: "en",
  setLocale: () => undefined,
  t: (source) => source,
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>("en");

  useEffect(() => {
    const saved = window.localStorage.getItem("openroboops.locale");
    const initial = saved === "en" || saved === "zh-CN"
      ? saved
      : navigator.language.toLowerCase().startsWith("zh") ? "zh-CN" : "en";
    window.localStorage.setItem("openroboops.locale", initial);
    // The browser preference is unavailable during server rendering; hydrate it once on mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLocale(initial);
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const updateLocale = useCallback((next: Locale) => {
    window.localStorage.setItem("openroboops.locale", next);
    setLocale(next);
  }, []);

  const t = useCallback((source: string, variables: Variables = {}) => {
    let translated = locale === "zh-CN" ? chinese[source] ?? source : source;
    Object.entries(variables).forEach(([name, value]) => {
      translated = translated.replaceAll(`{${name}}`, String(value));
    });
    return translated;
  }, [locale]);

  return <I18nContext.Provider value={{ locale, setLocale: updateLocale, t }}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}

export function LanguageToggle({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale, t } = useI18n();
  const next = locale === "en" ? "zh-CN" : "en";
  return <button
    type="button"
    className={`language-toggle${compact ? " compact" : ""}`}
    onClick={() => setLocale(next)}
    title={t("Switch language")}
    aria-label={t("Switch language")}
  >{locale === "en" ? "中文" : "EN"}</button>;
}
