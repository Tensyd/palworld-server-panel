const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const state = {
    currentTab: "dashboard",
    logAutoRefresh: true,
    loadingAction: false,
    currentConfig: {},
    configDirty: false,
    configConfirmResolve: null,
    dialogResolve: null,
    lastMetricValues: {},
    tabTransitionTimer: null,
    saveStatus: null,
    saveSlots: [],
    saveLoading: false,
    saveBusy: false,
    systemHistory: [],
    auditRecords: [],
    auditFilter: "all",
    auditLoading: false,
    updateStatus: null,
    updateLoading: false,
    updateLoadPromise: null,
    installStatus: null,
    installLoading: false,
    installLoadPromise: null,
    modStatus: null,
    mods: [],
    modLoading: false,
    modBusy: false,
    theme: localStorage.getItem("palworld-panel-theme") || "system",
    motion: localStorage.getItem("palworld-panel-motion") || "luxe",
    rawLogLines: [],
    logLevel: "all",
    logSearch: "",
    logAutoScroll: true,
    progressStartedAt: 0,
    progressLastError: "",
    activeAbortController: null,
    saveUploadMaxBytes: 1024 * 1024 * 1024,
    modUploadMaxBytes: 1024 * 1024 * 1024,
    requestGenerations: { status: 0, system: 0, log: 0 },
};

const particles = {
    canvas: null,
    ctx: null,
    items: [],
    meteors: [],
    raf: null,
    width: 0,
    height: 0,
    dpr: 1,
    visible: true,
    lastMeteorAt: 0,
    pointer: { x: -9999, y: -9999, active: false },
    colors: [
        [47, 111, 237],
        [124, 92, 255],
        [21, 127, 92],
        [83, 143, 255],
        [176, 146, 255],
    ],
};

const glowSelector = [
    ".topbar",
    ".tabs",
    ".panel",
    ".hero-panel",
    ".system-card",
    ".trend-card",
    ".config-group",
    ".save-current-card",
    ".save-slot-card",
    ".mod-card",
    ".mod-status-card",
    ".audit-item",
    ".update-card",
    ".update-step",
    ".install-card",
    ".install-check",
    ".modal-card",
    ".toast",
    ".log-box",
    ".console-output",
    ".primary",
    ".secondary",
    ".icon-button",
    ".tab-button",
].join(",");

const configGroups = [
    {
        icon: "☰",
        title: "服务器基础",
        fields: [
            ["ServerName", "服务器名称", "text"],
            ["ServerDescription", "服务器描述", "text"],
            ["ServerPassword", "服务器密码", "password"],
            ["ServerPlayerMaxNum", "最大玩家数", "number", { step: "1", min: 1, max: 128 }],
            ["GuildPlayerMaxNum", "公会最大人数", "number", { step: "1", min: 1, max: 100 }],
            ["CoopPlayerMaxNum", "合作模式最大玩家数", "number", { step: "1", min: 1, max: 32 }],
            ["AutoSaveSpan", "自动存档间隔(秒)", "number", { step: "1", min: 1, max: 3600 }],
            ["ChatPostLimitPerMinute", "聊天限速(条/分钟)", "number", { step: "1", min: 0, max: 1000 }],
            ["bShowPlayerList", "显示在线玩家列表", "bool", { hint: "开启后面板可通过 RCON 显示在线玩家。" }],
            ["bIsMultiplay", "启用多人模式", "bool"],
            ["bEnableAimAssistPad", "手柄瞄准辅助", "bool"],
            ["bEnableAimAssistKeyboard", "键鼠瞄准辅助", "bool"],
            ["bActiveUNKO", "启用 UNKO 特殊规则", "bool"],
            ["bIsShowJoinLeftMessage", "显示加入/离开消息", "bool"],
            ["bIsUseBackupSaveData", "启用游戏内备份存档", "bool"],
        ],
    },
    {
        icon: "↗",
        title: "倍率设置",
        fields: [
            ["ExpRate", "经验获取倍率", "number", { step: "0.1", min: 0.1, max: 20 }],
            ["DayTimeSpeedRate", "白天流逝速度倍率", "number", { step: "0.1", min: 0.1, max: 5 }],
            ["NightTimeSpeedRate", "夜晚流逝速度倍率", "number", { step: "0.1", min: 0.1, max: 5 }],
            ["WorkSpeedRate", "工作速度倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["ItemWeightRate", "物品重量倍率", "number", { step: "0.1", min: 0.1, max: 10, hint: "越低物品越轻。" }],
            ["ItemCorruptionMultiplier", "物品腐败速度倍率", "number", { step: "0.1", min: 0, max: 10, hint: "数值越高，食物等有保质期的物品腐败越快。" }],
            ["MonsterFarmActionSpeedRate", "牧场放牧产出速度倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["PalCaptureRate", "帕鲁捕获倍率", "number", { step: "0.1", min: 0.1, max: 5 }],
            ["PalSpawnNumRate", "帕鲁生成数量倍率", "number", { step: "0.1", min: 0.1, max: 5, hint: "控制野生帕鲁的生成数量；调高会增加服务器性能压力。" }],
            ["CollectionDropRate", "可采集资源掉落数量倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["EnemyDropItemRate", "敌人掉落物数量倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["EquipmentDurabilityDamageRate", "装备耐久损耗倍率", "number", { step: "0.1", min: 0, max: 10, hint: "0 表示不损耗耐久。" }],
        ],
    },
    {
        icon: "⚔",
        title: "战斗与生存",
        fields: [
            ["PalDamageRateAttack", "帕鲁攻击力倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["PalDamageRateDefense", "帕鲁受伤倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["PlayerDamageRateAttack", "玩家攻击力倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["PlayerDamageRateDefense", "玩家受伤倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["PlayerStomachDecreaceRate", "玩家饱食度下降速度倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["PlayerStaminaDecreaceRate", "玩家耐力消耗倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["PlayerAutoHPRegeneRate", "玩家自然生命恢复倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["PlayerAutoHpRegeneRateInSleep", "玩家睡眠生命恢复倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["PalStomachDecreaceRate", "帕鲁饱食度下降速度倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["PalStaminaDecreaceRate", "帕鲁耐力消耗倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["PalAutoHPRegeneRate", "帕鲁自然生命恢复倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["PalAutoHpRegeneRateInSleep", "帕鲁在 Palbox 内生命恢复倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["bEnablePlayerToPlayerDamage", "玩家对战伤害", "bool"],
            ["bEnableFriendlyFire", "友军伤害", "bool"],
            ["bIsPvP", "PvP 模式", "bool"],
            ["bEnableInvaderEnemy", "入侵敌人", "bool"],
        ],
    },
    {
        icon: "⌂",
        title: "世界、建造与据点",
        fields: [
            ["Difficulty", "世界难度", "select", [["None", "自定义"], ["Casual", "休闲"], ["Normal", "普通"], ["Hard", "困难"], ["Hardcore", "极限"]]],
            ["RandomizerType", "帕鲁生成随机化模式", "select", [["None", "关闭"], ["Region", "按区域随机"], ["All", "完全随机"]]],
            ["RandomizerSeed", "随机化种子", "text"],
            ["bIsRandomizerPalLevelRandom", "随机化帕鲁等级", "bool"],
            ["DeathPenalty", "死亡掉落惩罚", "select", [["None", "无掉落"], ["Item", "掉落物品（保留装备）"], ["ItemAndEquipment", "掉落物品和装备"], ["All", "掉落物品、装备和队伍帕鲁"]]],
            ["PalEggDefaultHatchingTime", "巨大帕鲁蛋孵化时间(时)", "number", { step: "0.5", min: 0, max: 240, hint: "其他尺寸的帕鲁蛋会按比例计算孵化时间。" }],
            ["BuildObjectHpRate", "建筑生命倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["BuildObjectDamageRate", "建筑受伤倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["BuildObjectDeteriorationDamageRate", "建筑腐蚀倍率", "number", { step: "0.1", min: 0, max: 10, hint: "0 表示关闭腐蚀。" }],
            ["CollectionObjectHpRate", "采集物生命倍率", "number", { step: "0.1", min: 0.1, max: 10 }],
            ["CollectionObjectRespawnSpeedRate", "采集物重生间隔倍率", "number", { step: "0.1", min: 0.1, max: 10, hint: "控制重生间隔；数值越高，采集物重生越慢。" }],
            ["BaseCampMaxNum", "据点最大数量", "number", { step: "1", min: 1, max: 512 }],
            ["BaseCampWorkerMaxNum", "每个据点的帕鲁上限", "number", { step: "1", min: 1, max: 50, hint: "官方上限为 50；调高会增加服务器性能压力。" }],
            ["BaseCampMaxNumInGuild", "每个公会的据点上限", "number", { step: "1", min: 1, max: 512, hint: "官方文档建议不超过 10；为兼容已有服务器配置，面板允许更高值。调高会增加服务器性能压力。" }],
            ["bBuildAreaLimit", "限制建筑区域", "bool"],
            ["bAllowGlobalPalboxExport", "允许全局 Palbox 导出", "bool"],
            ["bAllowGlobalPalboxImport", "允许全局 Palbox 导入", "bool"],
        ],
    },
    {
        icon: "◎",
        title: "玩法规则与社交",
        fields: [
            ["bHardcore", "硬核模式（死亡后无法复活）", "bool"],
            ["bPalLost", "帕鲁永久丢失", "bool"],
            ["bCharacterRecreateInHardcore", "硬核死亡后允许重建角色", "bool"],
            ["bCanPickupOtherGuildDeathPenaltyDrop", "可拾取其他公会死亡掉落", "bool"],
            ["bEnableNonLoginPenalty", "启用离线惩罚", "bool"],
            ["bExistPlayerAfterLogout", "玩家离线后保留角色", "bool"],
            ["bEnableDefenseOtherGuildPlayer", "允许防御其他公会玩家", "bool"],
            ["bInvisibleOtherGuildBaseCampAreaFX", "隐藏其他公会据点特效", "bool"],
            ["bEnableFastTravel", "快速旅行", "bool"],
            ["bEnableFastTravelOnlyBaseCamp", "仅基地快速旅行", "bool"],
            ["bIsStartLocationSelectByMap", "地图选择出生点", "bool"],
            ["bAllowClientMod", "允许客户端 MOD", "bool"],
            ["bEnableVoiceChat", "启用语音聊天", "bool"],
            ["VoiceChatMaxVolumeDistance", "语音保持最大音量的距离", "number", { step: "100", min: 0, max: 100000 }],
            ["VoiceChatZeroVolumeDistance", "语音音量降为零的距离", "number", { step: "100", min: 0, max: 100000 }],
            ["DenyTechnologyList", "禁用科技列表", "text", { hint: "以英文逗号分隔科技 ID；留空表示不限制。" }],
            ["bAllowEnhanceStat_Health", "允许强化生命", "bool"],
            ["bAllowEnhanceStat_Attack", "允许强化攻击", "bool"],
            ["bAllowEnhanceStat_Stamina", "允许强化体力", "bool"],
            ["bAllowEnhanceStat_Weight", "允许强化负重", "bool"],
            ["bAllowEnhanceStat_WorkSpeed", "允许强化工作速度", "bool"],
        ],
    },
    {
        icon: "✦",
        title: "掉落、复活与公会",
        fields: [
            ["DropItemMaxNum", "掉落物上限", "number", { step: "100", min: 0, max: 10000, hint: "过高会增加服务器性能压力。" }],
            ["DropItemMaxNum_UNKO", "特殊掉落物上限", "number", { step: "10", min: 0, max: 10000 }],
            ["DropItemAliveMaxHours", "掉落物保留时间(时)", "number", { step: "0.5", min: 0.1, max: 240 }],
            ["SupplyDropSpan", "陨石与补给空投间隔(分)", "number", { step: "1", min: 1, max: 1440 }],
            ["bAutoResetGuildNoOnlinePlayers", "自动清理长期无人公会据点", "bool", { hint: "达到离线时限后，删除该公会的建筑和据点帕鲁。" }],
            ["AutoResetGuildTimeNoOnlinePlayers", "无人公会据点清理时限(时)", "number", { step: "1", min: 0, max: 720 }],
            ["GuildRejoinCooldownMinutes", "重新加入公会冷却(分)", "number", { step: "1", min: 0, max: 10080 }],
            ["BlockRespawnTime", "死亡后复活冷却(秒)", "number", { step: "1", min: 0, max: 3600 }],
            ["RespawnPenaltyDurationThreshold", "触发复活惩罚的存活时长阈值(秒)", "number", { step: "1", min: 0, max: 3600 }],
            ["RespawnPenaltyTimeScale", "复活冷却倍率", "number", { step: "0.1", min: 0, max: 10 }],
            ["bDisplayPvPItemNumOnWorldMap_BaseCamp", "地图显示据点 PvP 掉落数", "bool"],
            ["bDisplayPvPItemNumOnWorldMap_Player", "地图显示玩家 PvP 掉落数", "bool"],
            ["AdditionalDropItemWhenPlayerKillingInPvPMode", "PvP 击杀额外掉落物 ID", "text", { hint: "填写游戏物品 ID；仅在启用 PvP 额外掉落时生效。" }],
            ["AdditionalDropItemNumWhenPlayerKillingInPvPMode", "PvP 额外掉落数量", "number", { step: "1", min: 0, max: 100 }],
            ["bAdditionalDropItemWhenPlayerKillingInPvPMode", "启用 PvP 额外掉落", "bool"],
        ],
    },
    {
        icon: "⚙",
        title: "高级与性能",
        fields: [
            ["PhysicsActiveDropItemMaxNum", "物理掉落物上限", "number", { step: "100", min: -1, max: 10000, hint: "-1 使用游戏默认值；调高会增加性能压力。" }],
            ["MaxBuildingLimitNum", "每名玩家建筑数量上限", "number", { step: "100", min: 0, max: 100000, hint: "0 表示不限制；过高会增加性能压力。" }],
            ["ServerReplicatePawnCullDistance", "帕鲁同步距离(cm)", "number", { step: "500", min: 5000, max: 15000, hint: "官方支持 5000 - 15000；较高数值会增加网络与 CPU 压力。" }],
            ["ItemContainerForceMarkDirtyInterval", "容器同步间隔(秒)", "number", { step: "0.1", min: 0.1, max: 60, hint: "较低数值会增加服务器负载。" }],
            ["PlayerDataPalStorageUpdateCheckTickInterval", "帕鲁仓库检查间隔(秒)", "number", { step: "0.1", min: 0.1, max: 60, hint: "较低数值会增加服务器负载。" }],
            ["AutoTransferMasterCheckIntervalSeconds", "公会会长转移检查间隔(秒)", "number", { step: "60", min: 60, max: 604800 }],
            ["AutoTransferMasterThresholdDays", "公会会长自动转移阈值(天)", "number", { step: "1", min: 0, max: 365 }],
            ["MaxGuildsPerFrame", "每帧处理公会数", "number", { step: "1", min: 1, max: 1000, hint: "较高数值会增加 CPU 压力。" }],
            ["BuildingNameDisplayCacheTTLSeconds", "建筑名称缓存时间(秒)", "number", { step: "1", min: 0, max: 3600 }],
            ["bEnableBuildingPlayerUIdDisplay", "显示建筑所属玩家 ID", "bool"],
            ["RESTAPIEnabled", "启用 REST API", "bool"],
            ["RESTAPIPort", "REST API 端口", "number", { step: "1", min: 1024, max: 65535, hint: "仅修改游戏 REST API 端口，不会修改 Docker 发布端口。" }],
        ],
    },
];

const configDefaults = {
    Difficulty: "None",
    RandomizerType: "None",
    RandomizerSeed: "",
    bIsRandomizerPalLevelRandom: "False",
    DayTimeSpeedRate: "1.000000",
    NightTimeSpeedRate: "1.000000",
    ExpRate: "1.000000",
    PalCaptureRate: "1.000000",
    PalSpawnNumRate: "1.000000",
    PalDamageRateAttack: "1.000000",
    PalDamageRateDefense: "1.000000",
    PlayerDamageRateAttack: "1.000000",
    PlayerDamageRateDefense: "1.000000",
    PlayerStomachDecreaceRate: "1.000000",
    PlayerStaminaDecreaceRate: "1.000000",
    PlayerAutoHPRegeneRate: "1.000000",
    PlayerAutoHpRegeneRateInSleep: "1.000000",
    PalStomachDecreaceRate: "1.000000",
    PalStaminaDecreaceRate: "1.000000",
    PalAutoHPRegeneRate: "1.000000",
    PalAutoHpRegeneRateInSleep: "1.000000",
    BuildObjectHpRate: "1.000000",
    BuildObjectDamageRate: "1.000000",
    BuildObjectDeteriorationDamageRate: "1.000000",
    CollectionDropRate: "1.000000",
    CollectionObjectHpRate: "1.000000",
    CollectionObjectRespawnSpeedRate: "1.000000",
    EnemyDropItemRate: "1.000000",
    DeathPenalty: "Item",
    bEnablePlayerToPlayerDamage: "False",
    bEnableFriendlyFire: "False",
    bEnableInvaderEnemy: "True",
    DropItemMaxNum: "3000",
    PhysicsActiveDropItemMaxNum: "-1",
    DropItemMaxNum_UNKO: "100",
    BaseCampMaxNum: "128",
    BaseCampWorkerMaxNum: "15",
    BaseCampMaxNumInGuild: "4",
    DropItemAliveMaxHours: "1.000000",
    bAutoResetGuildNoOnlinePlayers: "False",
    AutoResetGuildTimeNoOnlinePlayers: "72.000000",
    GuildPlayerMaxNum: "20",
    PalEggDefaultHatchingTime: "1.000000",
    WorkSpeedRate: "1.000000",
    AutoSaveSpan: "30.000000",
    bIsPvP: "False",
    bHardcore: "False",
    bPalLost: "False",
    bCharacterRecreateInHardcore: "False",
    bCanPickupOtherGuildDeathPenaltyDrop: "False",
    bEnableNonLoginPenalty: "True",
    bEnableFastTravel: "True",
    bEnableFastTravelOnlyBaseCamp: "False",
    bIsStartLocationSelectByMap: "False",
    bExistPlayerAfterLogout: "False",
    bEnableDefenseOtherGuildPlayer: "False",
    bInvisibleOtherGuildBaseCampAreaFX: "False",
    bBuildAreaLimit: "False",
    ItemWeightRate: "1.000000",
    CoopPlayerMaxNum: "4",
    ServerName: "Default Palworld Server",
    ServerDescription: "",
    ServerPassword: "",
    bAllowClientMod: "True",
    RESTAPIEnabled: "False",
    RESTAPIPort: "8212",
    bShowPlayerList: "False",
    ChatPostLimitPerMinute: "30",
    bIsUseBackupSaveData: "True",
    EnablePredatorBossPal: "True",
    bIsMultiplay: "False",
    bActiveUNKO: "False",
    bEnableAimAssistPad: "True",
    bEnableAimAssistKeyboard: "False",
    bIsShowJoinLeftMessage: "True",
    SupplyDropSpan: "180",
    MaxBuildingLimitNum: "0",
    ServerReplicatePawnCullDistance: "15000.000000",
    bAllowGlobalPalboxExport: "True",
    bAllowGlobalPalboxImport: "False",
    EquipmentDurabilityDamageRate: "1.000000",
    ItemContainerForceMarkDirtyInterval: "1.000000",
    PlayerDataPalStorageUpdateCheckTickInterval: "1.000000",
    ItemCorruptionMultiplier: "1.000000",
    MonsterFarmActionSpeedRate: "1.000000",
    DenyTechnologyList: "",
    GuildRejoinCooldownMinutes: "0",
    AutoTransferMasterCheckIntervalSeconds: "3600.000000",
    AutoTransferMasterThresholdDays: "14",
    MaxGuildsPerFrame: "10",
    BlockRespawnTime: "5.000000",
    RespawnPenaltyDurationThreshold: "0.000000",
    RespawnPenaltyTimeScale: "2.000000",
    bDisplayPvPItemNumOnWorldMap_BaseCamp: "False",
    bDisplayPvPItemNumOnWorldMap_Player: "False",
    AdditionalDropItemWhenPlayerKillingInPvPMode: "PlayerDropItem",
    AdditionalDropItemNumWhenPlayerKillingInPvPMode: "1",
    bAdditionalDropItemWhenPlayerKillingInPvPMode: "False",
    bEnableVoiceChat: "False",
    VoiceChatMaxVolumeDistance: "3000.000000",
    VoiceChatZeroVolumeDistance: "15000.000000",
    bAllowEnhanceStat_Health: "True",
    bAllowEnhanceStat_Attack: "True",
    bAllowEnhanceStat_Stamina: "True",
    bAllowEnhanceStat_Weight: "True",
    bAllowEnhanceStat_WorkSpeed: "True",
    bEnableBuildingPlayerUIdDisplay: "False",
    BuildingNameDisplayCacheTTLSeconds: "60",
};

const stringFields = new Set(["ServerName", "ServerDescription", "ServerPassword", "AdminPassword", "RandomizerSeed", "DenyTechnologyList", "AdditionalDropItemWhenPlayerKillingInPvPMode"]);

function stripQuotes(value) {
    const text = String(value ?? "");
    if (text.length >= 2 && text[0] === '"' && text.at(-1) === '"') {
        return text.slice(1, -1).replace(/\\(["\\])/g, "$1");
    }
    return text;
}

function normalizeSubmitValue(key, value) {
    const text = stripQuotes(value);
    if (stringFields.has(key)) return text;
    return String(value ?? "").trim();
}

function setMessage(el, text, type = "") {
    if (!el) return;
    el.textContent = text;
    el.className = `message ${type ? `is-${type}` : ""}`.trim();
    if (["configMsg", "saveMsg", "modMsg", "updateMsg", "installMsg", "auditMsg"].includes(el.id)) el.classList.add("panel-message");
}

function showToast(message, type = "info") {
    const stack = $("#toastStack");
    if (!stack || !message) return;

    const toast = document.createElement("div");
    toast.className = `toast ${type}`.trim();
    toast.textContent = message;
    stack.appendChild(toast);

    setTimeout(() => {
        toast.classList.add("is-leaving");
        setTimeout(() => toast.remove(), 180);
    }, 3200);
}

function closeDialog(result = null) {
    const modal = $("#interactionModal");
    if (!modal) return;
    modal.classList.remove("is-open", "is-danger", "is-progress");
    modal.setAttribute("aria-hidden", "true");
    $("#dialogBody").replaceChildren();
    if (state.dialogResolve) {
        state.dialogResolve(result);
        state.dialogResolve = null;
    }
}

function createDialogField(field) {
    const wrapper = document.createElement("label");
    wrapper.className = "dialog-field";
    const label = document.createElement("span");
    label.textContent = field.label;
    const input = document.createElement(field.type === "textarea" ? "textarea" : "input");
    input.name = field.name;
    input.value = field.value || "";
    input.placeholder = field.placeholder || "";
    input.required = Boolean(field.required);
    if (field.type && field.type !== "textarea") input.type = field.type;
    wrapper.append(label, input);
    if (field.hint) {
        const hint = document.createElement("small");
        hint.textContent = field.hint;
        wrapper.appendChild(hint);
    }
    return wrapper;
}

function openDialog(options = {}) {
    const modal = $("#interactionModal");
    const body = $("#dialogBody");
    const submit = $("#dialogSubmit");
    const cancel = $("#dialogCancel");
    if (!modal || !body || !submit || !cancel) return Promise.resolve(null);

    $("#dialogEyebrow").textContent = options.eyebrow || "Action";
    $("#dialogTitle").textContent = options.title || "确认操作";
    $("#dialogText").textContent = options.text || "";
    submit.textContent = options.submitText || "确认";
    cancel.textContent = options.cancelText || "取消";
    submit.className = `primary ${options.danger ? "danger" : ""}`.trim();
    cancel.style.display = options.hideCancel ? "none" : "";
    submit.style.display = options.hideSubmit ? "none" : "";
    body.replaceChildren();
    modal.classList.toggle("is-danger", Boolean(options.danger));
    modal.classList.toggle("is-progress", Boolean(options.progress));

    if (options.progress) {
        state.progressStartedAt = Date.now();
        state.progressLastError = "";
        const list = document.createElement("div");
        list.className = "progress-steps";
        (options.steps || []).forEach((step, index) => {
            const item = document.createElement("div");
            item.className = `progress-step ${index === 0 ? "is-active" : ""}`;
            item.dataset.stepIndex = String(index);
            const dot = document.createElement("span");
            dot.className = "progress-dot";
            const text = document.createElement("div");
            const title = document.createElement("b");
            title.textContent = step;
            const msg = document.createElement("small");
            msg.textContent = index === 0 ? "准备中..." : "等待中";
            text.append(title, msg);
            item.append(dot, text);
            list.appendChild(item);
        });
        body.appendChild(list);
        const meter = document.createElement("div");
        meter.className = "progress-meter";
        meter.innerHTML = `<span></span>`;
        const summary = document.createElement("div");
        summary.className = "progress-summary";
        summary.textContent = "准备执行...";
        body.append(meter, summary);
    } else if (options.fields?.length) {
        const form = document.createElement("form");
        form.className = "dialog-form";
        form.addEventListener("submit", (event) => {
            event.preventDefault();
            submit.click();
        });
        form.append(...options.fields.map(createDialogField));
        body.appendChild(form);
        setTimeout(() => form.querySelector("input, textarea")?.focus(), 50);
    } else if (options.details) {
        const details = document.createElement("div");
        details.className = "dialog-details";
        details.textContent = options.details;
        body.appendChild(details);
    }

    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");

    return new Promise((resolve) => {
        state.dialogResolve = resolve;
        submit.onclick = () => {
            if (options.progress) return;
            if (options.fields?.length) {
                const values = {};
                let valid = true;
                body.querySelectorAll("input, textarea").forEach((input) => {
                    if (input.required && !input.value.trim()) {
                        input.classList.add("is-invalid");
                        valid = false;
                    } else {
                        input.classList.remove("is-invalid");
                    }
                    values[input.name] = input.value;
                });
                if (!valid) {
                    showToast("请补全必填内容", "warn");
                    return;
                }
                closeDialog(values);
                return;
            }
            closeDialog(true);
        };
        cancel.onclick = () => {
            if (options.progress && typeof options.onCancel === "function") {
                options.onCancel();
                return;
            }
            closeDialog(null);
        };
        $("#dialogClose").onclick = () => {
            if (options.progress && typeof options.onCancel === "function") {
                options.onCancel();
                return;
            }
            closeDialog(null);
        };
    });
}

function setProgressStep(index, status = "active", message = "") {
    const item = $(`#interactionModal [data-step-index="${index}"]`);
    if (!item) return;
    item.classList.remove("is-active", "is-done", "is-error");
    item.classList.add(status === "done" ? "is-done" : status === "error" ? "is-error" : "is-active");
    const small = item.querySelector("small");
    if (small) small.textContent = message || (status === "done" ? "完成" : status === "error" ? "失败" : "进行中...");
    if (status === "error") state.progressLastError = message || "操作失败";
    const steps = $$("#interactionModal .progress-step");
    const done = steps.filter((step) => step.classList.contains("is-done")).length;
    const activeIndex = steps.findIndex((step) => step.classList.contains("is-active"));
    const progress = steps.length ? ((done + (activeIndex >= 0 ? 0.35 : 0)) / steps.length) * 100 : 0;
    const bar = $("#interactionModal .progress-meter span");
    if (bar) bar.style.width = `${Math.max(5, Math.min(100, progress))}%`;
    const summary = $("#interactionModal .progress-summary");
    if (summary) summary.textContent = message || (status === "done" ? "步骤完成" : status === "error" ? "步骤失败" : "正在执行...");
}

function openProgressDialog(title, steps, text = "", options = {}) {
    return openDialog({
        eyebrow: "Progress",
        title,
        text,
        steps,
        progress: true,
        hideCancel: !options.cancelable,
        hideSubmit: true,
        cancelText: options.cancelText || "取消",
        onCancel: options.onCancel,
    });
}

function finishProgressDialog(message, type = "success") {
    const elapsed = state.progressStartedAt ? Math.max(0, Math.round((Date.now() - state.progressStartedAt) / 1000)) : 0;
    $("#dialogText").textContent = message;
    const summary = $("#interactionModal .progress-summary");
    if (summary) {
        const resultText = type === "error" ? "操作失败" : type === "warn" ? "需要确认" : "操作完成";
        summary.textContent = `${resultText} · 耗时 ${elapsed} 秒`;
    }
    const bar = $("#interactionModal .progress-meter span");
    if (bar && type !== "error") bar.style.width = "100%";
    const body = $("#dialogBody");
    const oldCopy = $("#interactionModal .copy-error-btn");
    if (oldCopy) oldCopy.remove();
    if (type === "error" && body) {
        const copy = document.createElement("button");
        copy.type = "button";
        copy.className = "secondary copy-error-btn";
        copy.textContent = "复制错误日志";
        copy.addEventListener("click", async () => {
            try {
                await navigator.clipboard.writeText(state.progressLastError || message || "操作失败");
                showToast("错误日志已复制", "success");
            } catch {
                showToast("复制失败，请手动选择错误文本", "warn");
            }
        });
        body.appendChild(copy);
    }
    const submit = $("#dialogSubmit");
    submit.textContent = "完成";
    submit.style.display = "";
    submit.className = `primary ${type === "error" ? "danger" : ""}`.trim();
    submit.onclick = () => closeDialog(true);
}

function formatBytes(bytes) {
    const value = Number(bytes || 0);
    if (!value) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
    return `${(value / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function formatOptional(value, fallback = "-") {
    return value === undefined || value === null || value === "" ? fallback : String(value);
}

function updateUploadLimit(kind, data) {
    const specificKey = kind === "save" ? "save_upload_max_bytes" : "mod_upload_max_bytes";
    const sources = [data, data?.status, data?.limits, data?.upload_limits, data?.status?.limits];
    const keys = [specificKey, "upload_max_bytes", "max_upload_bytes", "upload_limit_bytes", "max_file_size", "max_content_length"];
    for (const source of sources) {
        if (!source || typeof source !== "object") continue;
        for (const key of keys) {
            const value = Number(source[key]);
            if (Number.isFinite(value) && value > 0) {
                state[kind === "save" ? "saveUploadMaxBytes" : "modUploadMaxBytes"] = value;
                return;
            }
        }
    }
}

function flashMetric(id, nextValue) {
    const element = $(`#${id}`);
    if (!element) return;
    const previous = state.lastMetricValues[id];
    state.lastMetricValues[id] = nextValue;
    if (previous === undefined || previous === nextValue) return;
    const card = element.closest(".cockpit-card, .system-card, .server-chip");
    if (!card) return;
    card.classList.remove("is-flashing");
    void card.offsetWidth;
    card.classList.add("is-flashing");
}

function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function resolvedTheme(theme = state.theme) {
    if (theme !== "system") return theme;
    const dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    return dark ? "dark" : "light";
}

function applyPreferences() {
    const theme = resolvedTheme();
    document.body.dataset.theme = theme;
    document.body.dataset.motion = state.motion;
    $("#themeSelect") && ($("#themeSelect").value = state.theme);
    $("#motionSelect") && ($("#motionSelect").value = state.motion);
    if (particles.canvas) {
        resizeParticles();
        if (state.motion === "off") {
            if (particles.raf !== null) cancelAnimationFrame(particles.raf);
            particles.raf = null;
            particles.ctx.clearRect(0, 0, particles.width, particles.height);
        } else if (particles.raf === null && !prefersReducedMotion()) {
            particles.raf = requestAnimationFrame(animateParticles);
        }
    }
}

function setTheme(value) {
    state.theme = value;
    localStorage.setItem("palworld-panel-theme", value);
    applyPreferences();
}

function setMotion(value) {
    state.motion = value;
    localStorage.setItem("palworld-panel-motion", value);
    applyPreferences();
}

function particleCountForViewport(width, height) {
    if (prefersReducedMotion() || state.motion === "off") return 0;
    const area = width * height;
    const isSmall = width < 720;
    const divisor = state.motion === "light" ? (isSmall ? 26000 : 16000) : (isSmall ? 17000 : 9200);
    const base = Math.round(area / divisor);
    const min = state.motion === "light" ? (isSmall ? 20 : 52) : (isSmall ? 38 : 92);
    const max = state.motion === "light" ? (isSmall ? 48 : 130) : (isSmall ? 88 : 230);
    return Math.max(min, Math.min(max, base));
}

function createParticle(width, height, initial = false) {
    const color = particles.colors[Math.floor(Math.random() * particles.colors.length)];
    const speed = 0.16 + Math.random() * 0.36;
    const angle = Math.random() * Math.PI * 2;
    return {
        x: Math.random() * width,
        y: initial ? Math.random() * height : height + Math.random() * 80,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - 0.08,
        radius: 1.2 + Math.random() * 3.6,
        alpha: 0.42 + Math.random() * 0.64,
        color,
        phase: Math.random() * Math.PI * 2,
    };
}

function createMeteor(width, height) {
    const color = particles.colors[Math.floor(Math.random() * particles.colors.length)];
    const fromLeft = Math.random() > 0.4;
    return {
        x: fromLeft ? -80 : Math.random() * width * 0.55,
        y: Math.random() * height * 0.38,
        vx: 2.6 + Math.random() * 2.4,
        vy: 1.0 + Math.random() * 1.6,
        life: 0,
        maxLife: 70 + Math.random() * 55,
        length: 72 + Math.random() * 110,
        alpha: 0.32 + Math.random() * 0.24,
        color,
    };
}

function resizeParticles() {
    const canvas = particles.canvas;
    if (!canvas) return;
    particles.dpr = Math.min(window.devicePixelRatio || 1, 2);
    particles.width = window.innerWidth;
    particles.height = window.innerHeight;
    canvas.width = Math.round(particles.width * particles.dpr);
    canvas.height = Math.round(particles.height * particles.dpr);
    canvas.style.width = `${particles.width}px`;
    canvas.style.height = `${particles.height}px`;
    particles.ctx.setTransform(particles.dpr, 0, 0, particles.dpr, 0, 0);
    particles.items = Array.from(
        { length: particleCountForViewport(particles.width, particles.height) },
        () => createParticle(particles.width, particles.height, true)
    );
    particles.meteors = [];
}

function drawParticles(time) {
    if (!particles.ctx || !particles.visible) return;
    const { ctx, width, height, pointer } = particles;
    ctx.clearRect(0, 0, width, height);
    ctx.lineWidth = 1;

    for (const particle of particles.items) {
        const pulse = 0.72 + Math.sin(time * 0.0012 + particle.phase) * 0.28;
        if (pointer.active) {
            const dx = particle.x - pointer.x;
            const dy = particle.y - pointer.y;
            const distance = Math.hypot(dx, dy);
            if (distance < 190 && distance > 0.1) {
                const force = (190 - distance) / 190;
                particle.vx += (dx / distance) * force * 0.014;
                particle.vy += (dy / distance) * force * 0.014;
                particle.vx += (pointer.x - particle.x) * force * 0.0007;
                particle.vy += (pointer.y - particle.y) * force * 0.0007;
            }
        }

        particle.x += particle.vx;
        particle.y += particle.vy;
        particle.vx *= 0.995;
        particle.vy *= 0.995;

        if (particle.x < -30) particle.x = width + 30;
        if (particle.x > width + 30) particle.x = -30;
        if (particle.y < -40) {
            particle.x = Math.random() * width;
            particle.y = height + 30;
        }
        if (particle.y > height + 60) particle.y = -20;

        const [r, g, b] = particle.color;
        const glow = particle.radius * 8.4;
        const gradient = ctx.createRadialGradient(particle.x, particle.y, 0, particle.x, particle.y, glow);
        gradient.addColorStop(0, `rgba(${r}, ${g}, ${b}, ${particle.alpha * pulse})`);
        gradient.addColorStop(0.34, `rgba(${r}, ${g}, ${b}, ${particle.alpha * 0.34 * pulse})`);
        gradient.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(particle.x, particle.y, glow, 0, Math.PI * 2);
        ctx.fill();
    }

    const linkDistance = width < 720 ? 104 : 154;
    for (let i = 0; i < particles.items.length; i += 1) {
        for (let j = i + 1; j < particles.items.length; j += 1) {
            const a = particles.items[i];
            const b = particles.items[j];
            const dx = a.x - b.x;
            const dy = a.y - b.y;
            const distance = Math.hypot(dx, dy);
            if (distance > linkDistance) continue;
            const opacity = (1 - distance / linkDistance) * 0.32;
            ctx.strokeStyle = `rgba(47, 111, 237, ${opacity})`;
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
        }
    }

    if (time - particles.lastMeteorAt > (width < 720 ? 4200 : 2600) && particles.meteors.length < (width < 720 ? 1 : 3)) {
        particles.meteors.push(createMeteor(width, height));
        particles.lastMeteorAt = time + Math.random() * 1200;
    }

    particles.meteors = particles.meteors.filter((meteor) => {
        meteor.life += 1;
        meteor.x += meteor.vx;
        meteor.y += meteor.vy;
        const progress = meteor.life / meteor.maxLife;
        const fade = Math.sin(Math.min(1, progress) * Math.PI);
        const [r, g, b] = meteor.color;
        const tailX = meteor.x - meteor.length;
        const tailY = meteor.y - meteor.length * 0.38;
        const line = ctx.createLinearGradient(tailX, tailY, meteor.x, meteor.y);
        line.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0)`);
        line.addColorStop(0.62, `rgba(${r}, ${g}, ${b}, ${meteor.alpha * 0.34 * fade})`);
        line.addColorStop(1, `rgba(255, 255, 255, ${meteor.alpha * fade})`);
        ctx.strokeStyle = line;
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.moveTo(tailX, tailY);
        ctx.lineTo(meteor.x, meteor.y);
        ctx.stroke();

        const head = ctx.createRadialGradient(meteor.x, meteor.y, 0, meteor.x, meteor.y, 18);
        head.addColorStop(0, `rgba(255, 255, 255, ${0.58 * fade})`);
        head.addColorStop(0.4, `rgba(${r}, ${g}, ${b}, ${meteor.alpha * fade})`);
        head.addColorStop(1, `rgba(${r}, ${g}, ${b}, 0)`);
        ctx.fillStyle = head;
        ctx.beginPath();
        ctx.arc(meteor.x, meteor.y, 18, 0, Math.PI * 2);
        ctx.fill();
        return meteor.life < meteor.maxLife && meteor.x < width + meteor.length && meteor.y < height + 120;
    });
}

function animateParticles(time = 0) {
    if (state.motion === "off" || prefersReducedMotion()) {
        particles.raf = null;
        return;
    }
    drawParticles(time);
    particles.raf = requestAnimationFrame(animateParticles);
}

function initParticles() {
    if (prefersReducedMotion()) return;
    const canvas = $("#ambientParticles");
    if (!canvas || !canvas.getContext) return;
    particles.canvas = canvas;
    particles.ctx = canvas.getContext("2d", { alpha: true });
    resizeParticles();
    window.addEventListener("resize", resizeParticles);
    window.addEventListener("mousemove", (event) => {
        particles.pointer = { x: event.clientX, y: event.clientY, active: true };
    });
    window.addEventListener("mouseleave", () => {
        particles.pointer.active = false;
    });
    document.addEventListener("visibilitychange", () => {
        particles.visible = !document.hidden;
        if (!particles.visible && particles.ctx) {
            particles.ctx.clearRect(0, 0, particles.width, particles.height);
        }
    });
    if (state.motion !== "off") animateParticles();
}

function initCursorGlow() {
    if (prefersReducedMotion()) return;
    const root = document.documentElement;
    const glow = $("#cursorGlow");
    let activeElement = null;

    window.addEventListener("pointermove", (event) => {
        root.style.setProperty("--cursor-x", `${event.clientX}px`);
        root.style.setProperty("--cursor-y", `${event.clientY}px`);
        document.body.classList.add("has-cursor");

        const target = event.target.closest?.(glowSelector);
        if (activeElement && activeElement !== target) {
            activeElement.classList.remove("is-pointer-hot");
        }
        activeElement = target;
        if (!target) return;

        const rect = target.getBoundingClientRect();
        target.style.setProperty("--mx", `${event.clientX - rect.left}px`);
        target.style.setProperty("--my", `${event.clientY - rect.top}px`);
        target.classList.add("is-pointer-hot");
    }, { passive: true });

    window.addEventListener("pointerleave", () => {
        document.body.classList.remove("has-cursor");
        if (activeElement) activeElement.classList.remove("is-pointer-hot");
        activeElement = null;
    });

    if (glow) {
        glow.addEventListener("transitionend", () => {
            if (!document.body.classList.contains("has-cursor")) {
                glow.style.opacity = "";
            }
        });
    }
}

function abortActiveRequest() {
    if (!state.activeAbortController) return;
    state.activeAbortController.abort();
    state.activeAbortController = null;
    state.progressLastError = "请求已取消";
    showToast("已取消当前请求", "warn");
}

async function api(path, options = {}) {
    const { timeout = 30000, controller, ...fetchOptions } = options;
    const activeController = controller || (timeout ? new AbortController() : null);
    let timer = null;
    if (activeController && timeout) {
        timer = setTimeout(() => activeController.abort(), timeout);
        fetchOptions.signal = activeController.signal;
    } else if (activeController) {
        fetchOptions.signal = activeController.signal;
    }
    try {
        const response = await fetch(path, fetchOptions);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.message || `请求失败 (${response.status})`);
        }
        return data;
    } catch (error) {
        if (error.name === "AbortError") {
            throw new Error("请求已取消或超时");
        }
        throw error;
    } finally {
        if (timer) clearTimeout(timer);
    }
}

function updateTabIndicator() {
    const tabs = $(".tabs");
    const active = $(".tab-button.is-active");
    if (!tabs || !active) return;
    const tabRect = tabs.getBoundingClientRect();
    const activeRect = active.getBoundingClientRect();
    const x = activeRect.left - tabRect.left + tabs.scrollLeft;
    tabs.style.setProperty("--tab-x", `${Math.round(x)}px`);
    tabs.style.setProperty("--tab-w", `${Math.round(activeRect.width)}px`);
}

function setRing(id, percent, label) {
    const ring = $(`#${id}`);
    if (!ring) return;
    const value = Math.max(0, Math.min(100, Number(percent || 0)));
    ring.style.setProperty("--value", value.toFixed(1));
    const text = ring.querySelector("span");
    if (text) text.textContent = label || `${Math.round(value)}%`;
}

function setUsageCard(id, percent) {
    const card = $(`#${id}`)?.closest(".system-card");
    if (!card) return;
    const value = Math.max(0, Math.min(100, Number(percent || 0)));
    card.style.setProperty("--usage", `${value}%`);
}

function switchTab(tab) {
    if (state.currentTab === tab) return;
    if (state.tabTransitionTimer) {
        clearTimeout(state.tabTransitionTimer);
        state.tabTransitionTimer = null;
    }

    const previousPanel = $(`#tab-${state.currentTab}`);
    const nextPanel = $(`#tab-${tab}`);
    if (!nextPanel) return;

    state.currentTab = tab;
    $$(".tab-button").forEach((button) => button.classList.toggle("is-active", button.dataset.tab === tab));
    updateTabIndicator();

    $$(".tab-panel").forEach((panel) => {
        panel.classList.remove("is-entering", "is-leaving");
        if (panel !== previousPanel && panel !== nextPanel) panel.classList.remove("is-active");
    });

    if (previousPanel && previousPanel !== nextPanel) {
        previousPanel.classList.add("is-leaving");
        previousPanel.classList.remove("is-active");
    }

    nextPanel.classList.add("is-active", "is-entering");
    state.tabTransitionTimer = setTimeout(() => {
        if (previousPanel) previousPanel.classList.remove("is-leaving");
        nextPanel.classList.remove("is-entering");
        state.tabTransitionTimer = null;
    }, 170);

    if (tab === "config") {
        if (state.configDirty) {
            setMessage($("#configMsg"), "保留了尚未保存的配置改动。", "warn");
        } else {
            loadConfig();
        }
    }
    if (tab === "log") loadLog();
    if (tab === "saves") loadSaves();
    if (tab === "mods") loadMods();
    if (tab === "update") loadUpdateStatus();
    if (tab === "install") loadInstallStatus();
    if (tab === "audit") loadAudit();
}

function renderStatus(data) {
    const { status, info } = data;
    const players = Array.isArray(info.online_players) ? info.online_players : [];
    const playersQueryOk = Boolean(info.players_query_ok);
    const playerListEnabled = Boolean(info.player_list_enabled);
    const playerTotal = players.length;
    const playerSource = info.players_source || "none";
    const playerSourceLabels = { rest: "REST API", rcon: "RCON 回退", none: "不可用" };
    const playerCountAvailable = playersQueryOk;
    const maxPlayers = info.max_players || "0";
    const statusBadge = $("#statusBadge");
    const dockerPending = status.backend === "docker" && status.container_running && !status.ready;
    const phaseLabels = {
        installing: "安装中",
        retrying: "重试中",
        steamcmd: "安装中",
        starting: "启动中",
        failed: "安装失败",
        error: "异常",
    };
    const statusText = dockerPending ? (phaseLabels[status.phase] || "准备中") : (status.running ? "运行中" : "已停止");
    const statusClass = dockerPending && status.phase !== "failed" && status.phase !== "error" ? "is-loading" : status.running ? "is-online" : "is-offline";

    statusBadge.textContent = statusText;
    statusBadge.className = `status-pill ${statusClass}`;

    const gameVersion = info.game_version || "-";
    const gamePort = info.port || "-";
    const playerCount = playerCountAvailable ? `${playerTotal} / ${maxPlayers}` : "玩家列表不可用";
    const maxPlayerNumber = Math.max(0, Number(maxPlayers || 0));
    const playerPercent = playerCountAvailable && maxPlayerNumber ? (playerTotal / maxPlayerNumber) * 100 : 0;
    $("#gameVersion").textContent = gameVersion;
    $("#gamePort").textContent = gamePort;
    $("#cockpitStatus") && ($("#cockpitStatus").textContent = statusText);
    $("#cockpitBackend") && ($("#cockpitBackend").textContent = `后端：${status.backend === "docker" ? "Docker" : "systemd"}`);
    $("#playerRingCount") && ($("#playerRingCount").textContent = playerCount);
    $("#playerRingValue") && ($("#playerRingValue").textContent = playerCountAvailable ? `${Math.round(playerPercent)}%` : "-");
    setRing("playerRing", playerPercent);
    $("#serverName").textContent = info.server_name || "-";
    $("#serverDesc").textContent = dockerPending ? (status.message || "Docker 正在准备 Palworld 服务端") : (info.server_description || "暂无服务器描述");
    const backendText = status.backend === "docker" ? "Docker" : "systemd";
    $("#serverUptime").textContent = status.start_time ? `模式：${backendText} · 启动时间：${status.start_time}` : `模式：${backendText}`;
    $("#playerCountBadge").textContent = playerCountAvailable ? `${playerTotal} 人` : "不可用";
    $("#playerSourceBadge").textContent = playerSourceLabels[playerSource] || "不可用";

    updateActionButtons(status.running, status.container_running);
    renderPlayers(players, {
        queryOk: playersQueryOk,
        playerListEnabled,
        source: playerSource,
        error: info.players_error || "",
        responseEmpty: Boolean(info.players_response_empty),
    });
}

function formatBytes(bytes) {
    const value = Number(bytes || 0);
    if (!value) return "-";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let size = value;
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
        size /= 1024;
        unit += 1;
    }
    return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatDuration(seconds) {
    const total = Math.max(0, Number(seconds || 0));
    const days = Math.floor(total / 86400);
    const hours = Math.floor((total % 86400) / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    if (days > 0) return `${days} 天 ${hours} 小时`;
    if (hours > 0) return `${hours} 小时 ${minutes} 分钟`;
    return `${minutes} 分钟`;
}

function appendSystemHistory(system) {
    const memory = system.memory || {};
    const disk = system.disk || {};
    const load = Array.isArray(system.load) ? system.load : [];
    state.systemHistory.push({
        ts: Date.now(),
        cpu: Number(system.cpu_percent || 0),
        memory: Number(memory.percent || 0),
        disk: Number(disk.percent || 0),
        load: Number(load[0] || 0),
    });
    state.systemHistory = state.systemHistory.slice(-30);
}

function drawTrendChart(canvas, values, color, maxValue = 100) {
    if (!canvas || !canvas.getContext) return;
    const ctx = canvas.getContext("2d");
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(160, Math.round(rect.width || canvas.width || 220));
    const height = Math.max(58, Math.round(rect.height || canvas.height || 72));
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const padding = 8;
    const plotWidth = width - padding * 2;
    const plotHeight = height - padding * 2;
    const points = values.length ? values : [0];
    const scaleMax = Math.max(1, maxValue);

    ctx.strokeStyle = "rgba(154, 190, 255, 0.18)";
    ctx.lineWidth = 1;
    [0.25, 0.5, 0.75].forEach((ratio) => {
        const y = padding + plotHeight * ratio;
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(width - padding, y);
        ctx.stroke();
    });

    const coords = points.map((value, index) => {
        const x = padding + (points.length === 1 ? plotWidth : (index / (points.length - 1)) * plotWidth);
        const y = padding + plotHeight - (Math.max(0, Math.min(value, scaleMax)) / scaleMax) * plotHeight;
        return [x, y];
    });

    const gradient = ctx.createLinearGradient(0, padding, 0, height - padding);
    gradient.addColorStop(0, color.replace("0.95", "0.22"));
    gradient.addColorStop(1, color.replace("0.95", "0"));
    ctx.beginPath();
    coords.forEach(([x, y], index) => {
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.lineTo(coords[coords.length - 1][0], height - padding);
    ctx.lineTo(coords[0][0], height - padding);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();

    ctx.beginPath();
    coords.forEach(([x, y], index) => {
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.stroke();
}

function renderSystemCharts() {
    const history = state.systemHistory;
    const loadMax = Math.max(1, ...history.map((item) => item.load), 1) * 1.2;
    drawTrendChart($("#systemCpuChart"), history.map((item) => item.cpu), "rgba(47, 111, 237, 0.95)");
    drawTrendChart($("#systemMemoryChart"), history.map((item) => item.memory), "rgba(124, 92, 255, 0.95)");
    drawTrendChart($("#systemDiskChart"), history.map((item) => item.disk), "rgba(21, 127, 92, 0.95)");
    drawTrendChart($("#systemLoadChart"), history.map((item) => item.load), "rgba(185, 107, 0, 0.95)", loadMax);
}

function renderSystem(data) {
    const system = data.system || {};
    const memory = system.memory || {};
    const disk = system.disk || {};
    const load = Array.isArray(system.load) ? system.load : [];
    const cpu = system.cpu_percent;
    const memoryPercent = memory.percent;
    const diskPercent = disk.percent;

    $("#systemCpu").textContent = cpu == null ? "-" : `${cpu}%`;
    $("#systemLoad").textContent = `负载：${load.length ? load.join(" / ") : "-"}`;
    $("#systemMemory").textContent = memoryPercent == null ? "-" : `${memoryPercent}%`;
    $("#systemMemoryDetail").textContent = `${formatBytes(memory.used)} / ${formatBytes(memory.total)}`;
    $("#systemDisk").textContent = diskPercent == null ? "-" : `${diskPercent}%`;
    $("#systemDiskDetail").textContent = `${formatBytes(disk.used)} / ${formatBytes(disk.total)}`;
    $("#systemUptime").textContent = formatDuration(system.uptime_seconds);
    $("#systemUpdated").textContent = `已刷新：${new Date().toLocaleTimeString()}`;
    setUsageCard("systemCpu", cpu);
    setUsageCard("systemMemory", memoryPercent);
    setUsageCard("systemDisk", diskPercent);
    setUsageCard("systemUptime", 100);
    setRing("cpuRing", Number(cpu || 0), cpu == null ? "-" : `${Math.round(Number(cpu))}%`);
    $("#cpuRingText") && ($("#cpuRingText").textContent = cpu == null ? "-" : `${cpu}%`);
    $("#cpuRingLoad") && ($("#cpuRingLoad").textContent = `负载：${load.length ? load.join(" / ") : "-"}`);

    appendSystemHistory(system);
    renderSystemCharts();

    flashMetric("systemCpu", $("#systemCpu").textContent);
    flashMetric("systemMemory", $("#systemMemory").textContent);
    flashMetric("systemDisk", $("#systemDisk").textContent);
    flashMetric("systemUptime", $("#systemUptime").textContent);
}

async function refreshSystem() {
    const generation = ++state.requestGenerations.system;
    try {
        const data = await api("/api/system");
        if (generation !== state.requestGenerations.system) return;
        renderSystem(data);
    } catch (error) {
        if (generation !== state.requestGenerations.system) return;
        $("#systemUpdated").textContent = "机器状态读取失败";
    }
}

function updateActionButtons(isRunning, containerRunning = false) {
    const startButton = $('[data-action="start"]');
    const restartButton = $('[data-action="restart"]');
    const stopButton = $('[data-action="stop"]');
    const active = Boolean(isRunning || containerRunning);

    if (startButton) {
        startButton.disabled = active;
        startButton.title = active ? "服务器已在运行或启动中" : "启动服务器";
    }
    if (restartButton) {
        restartButton.disabled = !active;
        restartButton.title = active ? "重启服务器" : "服务器停止时不可重启";
    }
    if (stopButton) {
        stopButton.disabled = !active;
        stopButton.title = active ? "停止服务器" : "服务器已停止";
    }
}

function renderPlayers(players, stateInfo = {}) {
    const list = $("#playerList");
    if (!stateInfo.queryOk) {
        const detail = stateInfo.error === "auth_failed" ? "REST API 认证失败。" : "REST API 与 RCON 均无法获取玩家列表。";
        list.innerHTML = `<tr><td colspan="3" class="empty">${detail}</td></tr>`;
        return;
    }
    if (!players.length) {
        list.innerHTML = `<tr><td colspan="3" class="empty">暂无在线玩家</td></tr>`;
        return;
    }
    list.replaceChildren(...players.map((player) => {
        const row = document.createElement("tr");
        const identity = player.account_name || player.player_id || "-";
        const details = [player.level ? `等级 ${player.level}` : "", player.ping ? `${player.ping} ms` : ""].filter(Boolean).join(" · ") || "-";
        [player.name, identity, details].forEach((value) => {
            const cell = document.createElement("td");
            cell.textContent = value || "-";
            row.appendChild(cell);
        });
        return row;
    }));
}

async function refreshAll() {
    const generation = ++state.requestGenerations.status;
    try {
        const data = await api("/api/status");
        if (generation !== state.requestGenerations.status) return;
        updateUploadLimit("save", data);
        updateUploadLimit("mod", data);
        renderStatus(data);
        refreshSystem();
    } catch (error) {
        if (generation !== state.requestGenerations.status) return;
        $("#statusBadge").textContent = "连接失败";
        $("#statusBadge").className = "status-pill is-offline";
        updateActionButtons(false);
        setMessage($("#actionMsg"), error.message, "error");
        refreshSystem();
    }

    if (state.currentTab === "log" && state.logAutoRefresh) {
        loadLog();
    }
    if (state.currentTab === "dashboard" || state.currentTab === "saves") {
        loadSaves(false);
    }
    if (state.currentTab === "mods") {
        loadMods(false);
    }
    if (state.currentTab === "update") {
        loadUpdateStatus(false);
    }
    if (state.currentTab === "install") {
        loadInstallStatus(false);
    }
    if (state.currentTab === "audit") {
        loadAudit(false);
    }
}

async function serverAction(action) {
    if (state.loadingAction) return;
    if (action === "stop" || action === "restart") {
        const confirmed = await openDialog({
            eyebrow: "Server Action",
            title: action === "stop" ? "确认停止服务器" : "确认重启服务器",
            text: action === "stop"
                ? "停止后玩家会断开连接，直到你重新启动 Palworld 服务。"
                : "重启会短暂中断连接，适合应用配置或刷新服务器状态。",
            submitText: action === "stop" ? "确认停止" : "确认重启",
            danger: action === "stop",
        });
        if (!confirmed) return;
    }

    state.loadingAction = true;
    const activeButton = document.querySelector(`[data-action="${action}"]`);
    const heroPanel = $("#tab-dashboard .hero-panel");
    if (activeButton) activeButton.classList.add("is-busy");
    if (heroPanel) heroPanel.classList.add("is-working");
    $$("[data-action]").forEach((button) => button.disabled = true);
    setMessage($("#actionMsg"), "正在执行操作...");

    try {
        const data = await api(`/api/${action}`, { method: "POST" });
        setMessage($("#actionMsg"), data.message || "操作完成", data.success ? "success" : "error");
        showToast(data.message || "操作完成", data.success ? "success" : "error");
    } catch (error) {
        setMessage($("#actionMsg"), error.message, "error");
        showToast(error.message, "error");
    } finally {
        state.loadingAction = false;
        if (activeButton) activeButton.classList.remove("is-busy");
        if (heroPanel) heroPanel.classList.remove("is-working");
        setTimeout(refreshAll, action === "restart" ? 5000 : 2000);
    }
}

async function loadLog() {
    const log = $("#logContainer");
    const generation = ++state.requestGenerations.log;
    try {
        const data = await api("/api/log?lines=80");
        if (generation !== state.requestGenerations.log) return;
        state.rawLogLines = data.lines || [];
        renderLogLines();
        if (state.logAutoScroll) log.scrollTop = log.scrollHeight;
    } catch (error) {
        if (generation !== state.requestGenerations.log) return;
        state.rawLogLines = [error.message];
        renderLogLines();
    }
}

function renderLogLines() {
    const log = $("#logContainer");
    const search = state.logSearch.trim().toLowerCase();
    const lines = (state.rawLogLines || []).filter((line) => {
        const level = classifyLogLine(line) || "info";
        const matchesLevel = state.logLevel === "all" || level === state.logLevel;
        const matchesSearch = !search || String(line).toLowerCase().includes(search);
        return matchesLevel && matchesSearch;
    });
    log.replaceChildren(...(lines.length ? lines : ["暂无匹配日志"]).map((line) => {
        const row = document.createElement("span");
        row.className = `log-line ${classifyLogLine(line)}`.trim();
        row.textContent = line;
        return row;
    }));
    if (state.logAutoScroll) log.scrollTop = log.scrollHeight;
}

function classifyLogLine(line) {
    const value = String(line).toLowerCase();
    if (value.includes("error") || value.includes("fail") || value.includes("exception")) return "error";
    if (value.includes("warn")) return "warn";
    if (value.includes("success") || value.includes("running") || value.includes("version")) return "success";
    return "";
}

const auditActionLabels = {
    "service.start": "启动服务",
    "service.stop": "停止服务",
    "service.restart": "重启服务",
    "config.save": "保存配置",
    "config.save_restart": "保存并重启",
    "rcon.command": "RCON 命令",
    "saves.backup_current": "备份当前存档",
    "saves.create_slot": "创建存档槽",
    "saves.import_slot": "导入存档",
    "saves.upload_slot": "上传存档",
    "saves.switch": "切换存档",
    "saves.delete_slot": "删除存档",
    "mods.upload": "上传 MOD",
    "mods.enable": "启用 MOD",
    "mods.disable": "禁用 MOD",
    "mods.delete": "删除 MOD",
    "mods.empty_trash": "清理 MOD 废纸篓",
    "mods.apply_restart": "应用 MOD 并重启",
};

Object.assign(auditActionLabels, {
    "update.check": "检查更新",
    "update.apply": "执行更新",
    "update.failed": "更新失败",
    "install.check": "检查安装环境",
    "install.palworld": "安装 Palworld",
    "install.repair": "修复安装",
});

function formatAuditTime(value) {
    if (!value) return "-";
    const normalized = String(value).replace(/([+-]\d{2})(\d{2})$/, "$1:$2");
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
}

function auditDetails(record) {
    const details = [];
    if (record.message) details.push(record.message);
    if (record.command) details.push(`命令：${record.command}`);
    if (Array.isArray(record.changed_keys) && record.changed_keys.length) details.push(`配置项：${record.changed_keys.join(", ")}`);
    if (record.slot_id) details.push(`存档槽：${record.slot_id}`);
    if (record.mod_id) details.push(`MOD：${record.mod_id}`);
    if (record.mod_type) details.push(`类型：${record.mod_type}`);
    if (record.backup_id) details.push(`备份：${record.backup_id}`);
    if (record.filename) details.push(`文件：${record.filename}`);
    if (record.source_path) details.push(`来源：${record.source_path}`);
    return details;
}

function renderAudit() {
    const list = $("#auditList");
    if (!list) return;
    const records = state.auditRecords.filter((record) => {
        if (state.auditFilter === "success") return record.success;
        if (state.auditFilter === "failed") return !record.success;
        return true;
    });

    $$(".audit-filter").forEach((button) => {
        button.classList.toggle("is-active", button.dataset.auditFilter === state.auditFilter);
    });

    if (!records.length) {
        const empty = document.createElement("div");
        empty.className = "empty audit-empty";
        empty.textContent = "暂无匹配的操作记录。";
        list.replaceChildren(empty);
        return;
    }

    list.replaceChildren(...records.map((record) => {
        const item = document.createElement("article");
        item.className = `audit-item ${record.success ? "is-success" : "is-error"}`;

        const header = document.createElement("div");
        header.className = "audit-item-head";
        const title = document.createElement("div");
        const label = document.createElement("h3");
        label.textContent = auditActionLabels[record.action] || record.action || "未知操作";
        const meta = document.createElement("p");
        meta.className = "muted";
        meta.textContent = `${formatAuditTime(record.time || record.ts)} · ${record.source_ip || "unknown"}`;
        title.append(label, meta);
        const badge = document.createElement("span");
        badge.className = `soft-pill ${record.success ? "is-success" : "is-error"}`;
        badge.textContent = record.success ? "成功" : "失败";
        header.append(title, badge);

        const detailWrap = document.createElement("div");
        detailWrap.className = "audit-detail-list";
        const details = auditDetails(record);
        detailWrap.replaceChildren(...(details.length ? details : ["无附加信息"]).map((detail) => {
            const chip = document.createElement("span");
            chip.textContent = detail;
            return chip;
        }));

        item.append(header, detailWrap);
        return item;
    }));
}

async function loadAudit(showLoading = true) {
    if (state.auditLoading) return;
    state.auditLoading = true;
    if (showLoading) setMessage($("#auditMsg"), "正在读取操作记录...");
    try {
        const data = await api("/api/audit?limit=80");
        state.auditRecords = data.records || [];
        renderAudit();
        if (showLoading) setMessage($("#auditMsg"), "操作记录已刷新。", "success");
    } catch (error) {
        setMessage($("#auditMsg"), error.message, "error");
        showToast(error.message, "error");
    } finally {
        state.auditLoading = false;
    }
}

function setAuditFilter(filter) {
    state.auditFilter = filter;
    renderAudit();
}

const updateStepLabels = {
    detect: "检测版本",
    notify: "通知玩家",
    save: "保存世界",
    backup: "备份存档",
    stop: "停止服务",
    update: "SteamCMD 更新",
    permissions: "修复权限",
    start: "启动服务",
    complete: "完成",
    failed: "失败",
};

function shortManifest(value) {
    const text = String(value || "-");
    return text.length > 16 ? `${text.slice(0, 8)}...${text.slice(-6)}` : text;
}

function renderUpdateStatus(status = {}) {
    state.updateStatus = status;
    const dockerMode = status.backend === "docker";
    $("#updateLocalManifest").textContent = shortManifest(status.local_manifest);
    $("#updateLocalBuild").textContent = status.local_buildid ? `Build ${status.local_buildid}` : "Build -";
    $("#updateLatestManifest").textContent = shortManifest(status.latest_manifest);
    $("#updateCheckedAt").textContent = status.checked_at ? `检查于 ${formatAuditTime(status.checked_at)}` : "尚未检查";
    $("#updateAvailability").textContent = status.running
        ? "更新进行中"
        : status.update_available
            ? "发现新版本"
            : status.success === false
                ? "上次失败"
                : "已是最新";
    $("#updateAutoState").textContent = dockerMode ? "Docker Compose 模式 · 自动检测关闭" : `自动更新 ${status.auto_update_enabled ? "开启" : "关闭"} · 倒计时 ${status.warn_minutes || 0} 分钟`;
    $("#updateServiceState").textContent = dockerMode ? "容器触发" : status.service_active ? "运行中" : "空闲";
    $("#updateTimerState").textContent = dockerMode ? "重启 Palworld 容器后自动 validate" : `Timer ${status.timer_active ? "已启用" : "未启用"}`;

    const applyButton = $("#applyUpdateBtn");
    if (applyButton) {
        const canApply = Boolean(status.update_available) && !status.running && !status.service_active;
        applyButton.disabled = !canApply;
        applyButton.textContent = status.running || status.service_active
            ? "更新进行中"
            : status.update_available
                ? dockerMode ? "重启容器更新" : "立即后台更新"
                : status.checked_at
                    ? "已是最新"
                    : "先检查更新";
        applyButton.title = canApply ? "启动后台更新流程" : "没有检测到新版本时不会启动后台更新";
    }

    const steps = Array.isArray(status.steps) ? status.steps : [];
    const stepWrap = $("#updateSteps");
    if (stepWrap) {
        stepWrap.replaceChildren(...(steps.length ? steps : [{ name: "detect", status: "idle", message: status.message || "等待检查" }]).map((step) => {
            const item = document.createElement("div");
            item.className = `update-step is-${step.status || "idle"}`;
            const dot = document.createElement("span");
            dot.className = "progress-dot";
            const text = document.createElement("div");
            const title = document.createElement("b");
            title.textContent = updateStepLabels[step.name] || step.name || "步骤";
            const msg = document.createElement("small");
            msg.textContent = step.message || step.status || "-";
            text.append(title, msg);
            item.append(dot, text);
            return item;
        }));
    }

    const log = $("#updateLog");
    if (log) {
        const lines = Array.isArray(status.log_tail) ? status.log_tail : [];
        log.textContent = lines.length ? lines.join("\n") : "等待更新日志...";
        log.scrollTop = log.scrollHeight;
    }

    const type = status.success === false ? "error" : status.update_available ? "warn" : status.running ? "" : "success";
    setMessage($("#updateMsg"), status.message || "更新状态已刷新", type);
}

function loadUpdateStatus(showLoading = true) {
    if (state.updateLoadPromise) return state.updateLoadPromise;
    state.updateLoading = true;
    if (showLoading) setMessage($("#updateMsg"), "正在读取更新状态...");
    const promise = (async () => {
        try {
            const data = await api("/api/update/status");
            renderUpdateStatus(data.status || {});
        } catch (error) {
            setMessage($("#updateMsg"), error.message, "error");
            showToast(error.message, "error");
        } finally {
            state.updateLoading = false;
            if (state.updateLoadPromise === promise) state.updateLoadPromise = null;
        }
    })();
    state.updateLoadPromise = promise;
    return promise;
}

async function checkUpdateNow() {
    const button = $("#checkUpdateBtn");
    if (button) button.classList.add("is-busy");
    setMessage($("#updateMsg"), "正在联网检查 Palworld 更新...");
    try {
        const data = await api("/api/update/check", { method: "POST" });
        renderUpdateStatus(data.status || {});
        showToast(data.message || "检查完成", data.success ? "success" : "error");
    } catch (error) {
        setMessage($("#updateMsg"), error.message, "error");
        showToast(error.message, "error");
        await loadUpdateStatus(false);
    } finally {
        if (button) button.classList.remove("is-busy");
    }
}

async function applyUpdateNow() {
    if (!state.updateStatus?.update_available) {
        showToast("当前没有检测到可用更新，请先检查更新", "info");
        setMessage($("#updateMsg"), "当前没有检测到可用更新，请先点击检查更新。", "info");
        return;
    }
    const confirmed = await openDialog({
        eyebrow: "Auto Update",
        title: "确认后台更新 Palworld",
        text: "如果检测到新版本，后台会广播倒计时、保存、备份、停止 Palworld、更新并重新启动。有人在线也会在倒计时结束后强制更新。",
        submitText: "启动后台更新",
        danger: true,
    });
    if (!confirmed) return;

    const button = $("#applyUpdateBtn");
    if (button) button.classList.add("is-busy");
    openProgressDialog("Palworld 后台更新", ["检测版本", "通知玩家", "保存世界", "停止服务", "备份存档", "SteamCMD 更新", "修复权限", "启动服务", "完成"], "更新会在 systemd 后台执行，面板会持续读取进度。");
    try {
        const data = await api("/api/update/apply", { method: "POST" });
        renderUpdateStatus(data.status || {});
        showToast(data.message || "后台更新已启动", "success");
        pollUpdateProgress();
    } catch (error) {
        finishProgressDialog(error.message, "error");
        setMessage($("#updateMsg"), error.message, "error");
        showToast(error.message, "error");
    } finally {
        if (button) button.classList.remove("is-busy");
    }
}

async function pollUpdateProgress() {
    const map = ["detect", "notify", "save", "stop", "backup", "update", "permissions", "start", "complete"];
    for (let attempt = 0; attempt < 240; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 3000));
        await loadUpdateStatus(false);
        const status = state.updateStatus || {};
        const steps = Array.isArray(status.steps) ? status.steps : [];
        steps.forEach((step) => {
            const index = map.indexOf(step.name);
            if (index >= 0) {
                setProgressStep(index, step.status === "done" ? "done" : step.status === "error" ? "error" : "active", step.message || "");
            }
        });
        if (!status.running && status.phase !== "running" && status.phase !== "checking") {
            if (status.success === false) {
                finishProgressDialog(status.message || "更新失败", "error");
            } else {
                setProgressStep(8, "done", status.message || "更新完成");
                finishProgressDialog(status.message || "更新完成", "success");
            }
            await refreshAll();
            return;
        }
    }
    finishProgressDialog("更新仍在后台运行，请稍后查看更新日志", "warn");
}

const installStepLabels = {
    environment: "环境检查",
    user: "运行用户",
    dependencies: "系统依赖",
    steamcmd: "SteamCMD",
    panel: "面板目录",
    palworld: "下载 Palworld",
    config: "生成配置",
    systemd: "安装服务",
    permissions: "修复权限",
    complete: "完成",
    failed: "失败",
};

const installCheckLabels = {
    docker_backend: "Docker 模式",
    os_supported: "Ubuntu/Debian",
    apt_get: "apt",
    systemd: "systemd",
    python3: "Python 3",
    curl: "curl",
    tar: "tar",
    steamcmd_installed: "SteamCMD",
    palworld_installed: "Palworld",
    palworld_manifest: "Steam Manifest",
    panel_installed: "面板文件",
    env_file: "环境变量",
    container_running: "Palworld 容器",
    palworld_service_active: "游戏服务",
    panel_service_active: "面板服务",
};

function boolText(value, yes = "已就绪", no = "未就绪") {
    return value ? yes : no;
}

function renderInstallStatus(status = {}) {
    state.installStatus = status;
    const checks = status.checks || {};
    const dockerMode = status.backend === "docker";
    const running = Boolean(status.running || status.service_active);

    $("#installPalworldDir").textContent = status.palworld_dir || "-";
    $("#installPalworldState").textContent = boolText(checks.palworld_installed, "已安装", "未安装");
    $("#installSteamcmdState").textContent = boolText(checks.steamcmd_installed, "已安装", "未安装");
    $("#installSteamcmdPath").textContent = status.steamcmd || "-";
    $("#installSystemState").textContent = dockerMode ? "Docker Compose" : checks.os_supported === false ? "系统不支持" : boolText(checks.systemd && checks.apt_get, "环境正常", "待检查");
    $("#installUserState").textContent = dockerMode ? "容器部署 · 无需 systemd 修复" : `用户 ${status.panel_user || "-"} · ${checks.python3 ? "Python 已就绪" : "Python 待检查"}`;
    $("#installServiceState").textContent = dockerMode ? boolText(checks.container_running, "容器运行中", "容器未运行") : running ? "任务运行中" : "空闲";
    $("#installPanelState").textContent = dockerMode ? "面板容器已加载" : boolText(checks.panel_installed, "面板已安装", "面板待安装");

    const checkWrap = $("#installChecks");
    if (checkWrap) {
        const entries = Object.entries(installCheckLabels);
        checkWrap.replaceChildren(...entries.map(([key, label]) => {
            const item = document.createElement("span");
            const value = checks[key];
            item.className = `install-check ${value ? "is-ok" : value === false ? "is-missing" : "is-unknown"}`;
            item.textContent = `${label}: ${value === undefined ? "待检查" : value ? "正常" : "缺失"}`;
            return item;
        }));
    }

    const stepWrap = $("#installSteps");
    if (stepWrap) {
        const steps = Array.isArray(status.steps) ? status.steps : [];
        const visibleSteps = steps.length ? steps : [{ name: "environment", status: "idle", message: status.message || "等待检查或安装" }];
        stepWrap.replaceChildren(...visibleSteps.map((step) => {
            const item = document.createElement("div");
            item.className = `update-step install-step is-${step.status || "idle"}`;
            const dot = document.createElement("span");
            dot.className = "progress-dot";
            const text = document.createElement("div");
            const title = document.createElement("b");
            title.textContent = installStepLabels[step.name] || step.name || "步骤";
            const msg = document.createElement("small");
            msg.textContent = step.message || step.status || "-";
            text.append(title, msg);
            item.append(dot, text);
            return item;
        }));
    }

    const log = $("#installLog");
    if (log) {
        const lines = Array.isArray(status.log_tail) ? status.log_tail : [];
        log.textContent = lines.length ? lines.join("\n") : "等待安装日志...";
        log.scrollTop = log.scrollHeight;
    }

    const checkButton = $("#checkInstallBtn");
    const installButton = $("#installPalworldBtn");
    const repairButton = $("#repairInstallBtn");
    if (checkButton) checkButton.disabled = running;
    if (installButton) {
        const installed = Boolean(checks.palworld_installed);
        installButton.disabled = dockerMode || running || installed;
        installButton.textContent = dockerMode ? "Docker 已接管" : running ? "安装中..." : installed ? "Palworld 已安装" : "安装 Palworld";
        installButton.title = dockerMode ? "Docker 模式由 docker compose 和容器 entrypoint 完成安装" : installed ? "检测到已有 Palworld，不会重复安装；如需修复请点修复安装" : "下载并安装 Palworld Dedicated Server";
    }
    if (repairButton) {
        repairButton.disabled = dockerMode || running;
        repairButton.textContent = dockerMode ? "无需修复" : "修复安装";
    }

    const type = status.success === false ? "error" : running ? "" : status.success ? "success" : "info";
    setMessage($("#installMsg"), status.message || "安装状态已刷新", type);
}

function loadInstallStatus(showLoading = true) {
    if (state.installLoadPromise) return state.installLoadPromise;
    state.installLoading = true;
    if (showLoading) setMessage($("#installMsg"), "正在读取安装状态...");
    const promise = (async () => {
        try {
            const data = await api("/api/install/status");
            renderInstallStatus(data.status || {});
        } catch (error) {
            setMessage($("#installMsg"), error.message, "error");
            showToast(error.message, "error");
        } finally {
            state.installLoading = false;
            if (state.installLoadPromise === promise) state.installLoadPromise = null;
        }
    })();
    state.installLoadPromise = promise;
    return promise;
}

async function checkInstallNow() {
    const button = $("#checkInstallBtn");
    if (button) button.classList.add("is-busy");
    setMessage($("#installMsg"), "正在检查系统环境和安装状态...");
    try {
        const data = await api("/api/install/check", { method: "POST" });
        renderInstallStatus(data.status || {});
        showToast(data.message || "环境检查完成", data.success ? "success" : "error");
    } catch (error) {
        setMessage($("#installMsg"), error.message, "error");
        showToast(error.message, "error");
        await loadInstallStatus(false);
    } finally {
        if (button) button.classList.remove("is-busy");
    }
}

async function startInstallAction(action) {
    const isRepair = action === "repair";
    const installed = Boolean(state.installStatus?.checks?.palworld_installed);
    if (!isRepair && installed) {
        showToast("检测到已有 Palworld，请使用修复安装。", "info");
        return;
    }

    const confirmed = await openDialog({
        eyebrow: "Installer",
        title: isRepair ? "确认修复安装" : "确认安装 Palworld 服务器",
        text: isRepair
            ? "修复会重新写入 systemd、sudoers、环境变量并修复权限，不会覆盖现有存档。"
            : "安装会下载 SteamCMD 和 Palworld Dedicated Server，生成配置、systemd 服务和面板环境变量。已有存档不会被覆盖。",
        submitText: isRepair ? "开始修复" : "开始安装",
        danger: false,
    });
    if (!confirmed) return;

    const button = isRepair ? $("#repairInstallBtn") : $("#installPalworldBtn");
    if (button) button.classList.add("is-busy");
    openProgressDialog(
        isRepair ? "修复安装" : "安装 Palworld",
        ["环境检查", "运行用户", "系统依赖", "SteamCMD", "下载 Palworld", "生成配置", "安装服务", "完成"],
        isRepair ? "后台会修复服务、权限和配置，不会触碰存档内容。" : "安装过程由 systemd 后台执行，下载可能需要较久。"
    );
    try {
        const endpoint = isRepair ? "/api/install/repair" : "/api/install/palworld";
        const data = await api(endpoint, { method: "POST" });
        renderInstallStatus(data.status || {});
        showToast(data.message || (isRepair ? "修复任务已启动" : "安装任务已启动"), "success");
        pollInstallProgress();
    } catch (error) {
        finishProgressDialog(error.message, "error");
        setMessage($("#installMsg"), error.message, "error");
        showToast(error.message, "error");
        await loadInstallStatus(false);
    } finally {
        if (button) button.classList.remove("is-busy");
    }
}

async function pollInstallProgress() {
    const map = ["environment", "user", "dependencies", "steamcmd", "palworld", "config", "systemd", "complete"];
    for (let attempt = 0; attempt < 240; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 3000));
        await loadInstallStatus(false);
        const status = state.installStatus || {};
        const steps = Array.isArray(status.steps) ? status.steps : [];
        steps.forEach((step) => {
            const mappedName = step.name === "panel" ? "user" : step.name;
            const index = map.indexOf(mappedName);
            if (index >= 0) {
                setProgressStep(index, step.status === "done" ? "done" : step.status === "error" ? "error" : "active", step.message || "");
            }
        });
        if (!status.running && !status.service_active && status.phase !== "installing" && status.phase !== "repair") {
            if (status.success === false) {
                finishProgressDialog(status.message || "安装任务失败", "error");
            } else {
                setProgressStep(7, "done", status.message || "安装任务完成");
                finishProgressDialog(status.message || "安装任务完成", "success");
            }
            await refreshAll();
            return;
        }
    }
    finishProgressDialog("安装任务仍在后台运行，请稍后查看安装日志", "warn");
}

function modTypeLabel(type) {
    if (type === "official") return "官方 Info.json";
    if (type === "sig") return "签名文件";
    return "PAK";
}

function setModControlsBusy(isBusy) {
    state.modBusy = isBusy;
    const panel = $("#tab-mods .panel");
    if (panel) panel.classList.toggle("is-working", isBusy);
    ["#refreshModsBtn", "#uploadModBtn", "#applyModsRestartBtn", "#emptyModTrashBtn"].forEach((selector) => {
        const button = $(selector);
        if (!button) return;
        button.disabled = isBusy;
        button.classList.toggle("is-busy", isBusy);
    });
    $$("#modList button").forEach((button) => {
        button.disabled = isBusy;
        button.classList.toggle("is-busy", isBusy);
    });
}

function renderModStatus() {
    const status = state.modStatus || {};
    $("#modBackend").textContent = status.backend || "-";
    $("#modMode").textContent = status.mode || "-";
    $("#modCount").textContent = String(status.mods_count ?? state.mods.length ?? 0);
    $("#modEnabledCount").textContent = `已启用 ${status.enabled_count ?? state.mods.filter((mod) => mod.enabled).length} 个`;
    $("#modPakDir").textContent = status.pak_enabled_dir || "-";
    const warning = $("#modWarning");
    if (warning) {
        warning.textContent = status.warning || "PAK MOD 通常需要客户端也安装同款 MOD；启用、禁用、删除后需要重启服务器。";
    }
    const applyButton = $("#applyModsRestartBtn");
    if (applyButton) {
        applyButton.disabled = state.modBusy || !state.mods.length;
        applyButton.title = state.mods.length ? "备份当前存档并重启服务器，让 MOD 变更生效" : "暂无 MOD 可应用";
    }
}

function renderMods() {
    renderModStatus();
    const list = $("#modList");
    if (!list) return;
    const mods = state.mods || [];
    if (!mods.length) {
        const empty = document.createElement("div");
        empty.className = "empty mod-empty";
        empty.textContent = "还没有导入 MOD。可以上传 .pak、.sig 或包含 Info.json 的 .zip。";
        list.replaceChildren(empty);
        return;
    }

    list.replaceChildren(...mods.map((mod) => {
        const card = document.createElement("article");
        card.className = `mod-card ${mod.enabled ? "is-enabled" : ""} ${mod.type === "official" ? "is-official" : ""}`.trim();

        const head = document.createElement("div");
        head.className = "mod-card-head";
        const titleWrap = document.createElement("div");
        const title = document.createElement("h3");
        title.textContent = mod.name || mod.package_name || mod.id;
        const subtitle = document.createElement("p");
        subtitle.className = "muted";
        subtitle.textContent = mod.type === "official"
            ? `PackageName: ${mod.package_name || "-"}${mod.version ? ` · v${mod.version}` : ""}`
            : `MOD ID: ${mod.id}`;
        titleWrap.append(title, subtitle);
        const badge = document.createElement("span");
        badge.className = `soft-pill ${mod.enabled ? "is-success" : ""}`.trim();
        badge.textContent = mod.enabled ? "已启用" : "已禁用";
        head.append(titleWrap, badge);

        const meta = document.createElement("div");
        meta.className = "save-slot-meta mod-meta";
        meta.append(
            createSaveMeta("类型", modTypeLabel(mod.type)),
            createSaveMeta("大小", formatBytes(mod.size_bytes)),
            createSaveMeta("更新时间", formatOptional(mod.updated_at)),
            createSaveMeta("重启", mod.needs_restart ? "需要" : "不需要")
        );

        const compatibility = document.createElement("p");
        compatibility.className = mod.type === "official" ? "mod-compat is-warning" : "mod-compat";
        compatibility.textContent = mod.compatibility || "启用后需要重启服务器；多数 MOD 也要求玩家客户端安装同款文件。";

        const notes = document.createElement("p");
        notes.className = "save-notes";
        notes.textContent = mod.notes || (Array.isArray(mod.files) && mod.files.length ? mod.files.map((file) => file.name).join(", ") : "无备注");

        const actions = document.createElement("div");
        actions.className = "save-slot-actions mod-actions";
        const toggleButton = document.createElement("button");
        toggleButton.className = mod.enabled ? "secondary" : "primary";
        toggleButton.type = "button";
        toggleButton.textContent = mod.enabled ? "禁用" : "启用";
        toggleButton.addEventListener("click", () => toggleMod(mod));

        const deleteButton = document.createElement("button");
        deleteButton.className = "secondary danger-soft";
        deleteButton.type = "button";
        deleteButton.textContent = "移入废纸篓";
        deleteButton.addEventListener("click", () => deleteMod(mod));
        actions.append(toggleButton, deleteButton);

        card.append(head, meta, compatibility, notes, actions);
        return card;
    }));
}

async function loadMods(showLoading = true) {
    if (state.modLoading) return;
    state.modLoading = true;
    if (showLoading) setMessage($("#modMsg"), "正在读取 MOD 状态...");
    try {
        const [statusData, listData] = await Promise.all([
            api("/api/mods/status"),
            api("/api/mods/list"),
        ]);
        state.modStatus = statusData.status || {};
        updateUploadLimit("mod", statusData);
        state.mods = listData.mods || [];
        renderMods();
        if (showLoading) setMessage($("#modMsg"), "MOD 信息已刷新。", "success");
    } catch (error) {
        setMessage($("#modMsg"), error.message, "error");
        showToast(error.message, "error");
    } finally {
        state.modLoading = false;
    }
}

async function uploadMod() {
    if (state.modBusy) return;
    const input = $("#modUploadInput");
    const file = input?.files?.[0];
    if (!file) return;
    const lower = file.name.toLowerCase();
    if (![".pak", ".sig", ".zip"].some((suffix) => lower.endsWith(suffix))) {
        setMessage($("#modMsg"), "只支持上传 .pak、.sig 或 .zip MOD 文件。", "error");
        showToast("MOD 文件格式不支持", "error");
        input.value = "";
        return;
    }

    if (file.size > state.modUploadMaxBytes) {
        setMessage($("#modMsg"), `MOD 文件不能超过 ${formatBytes(state.modUploadMaxBytes)}。`, "error");
        showToast("MOD 文件太大", "error");
        input.value = "";
        return;
    }

    const defaultName = file.name.replace(/\.(pak|sig|zip)$/i, "");
    const values = await openDialog({
        eyebrow: "Mod Upload",
        title: "上传 MOD",
        text: `已选择：${file.name}\nPAK MOD 通常需要玩家客户端也安装同款 MOD；官方 Info.json 包在 Linux/Docker 后端有兼容风险。`,
        submitText: "上传并导入",
        fields: [
            { name: "name", label: "MOD 名称", required: true, value: defaultName },
            { name: "notes", label: "备注", type: "textarea", placeholder: "可留空，例如来源、版本、是否需要客户端安装" },
        ],
    });
    if (!values) {
        input.value = "";
        return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("name", values.name.trim());
    formData.append("notes", values.notes || "");

    setModControlsBusy(true);
    state.activeAbortController = new AbortController();
    openProgressDialog(
        "上传 MOD",
        ["选择文件", "上传", "识别类型", "刷新列表"],
        "面板只会移动 .pak/.sig 或 Info.json 包，不会执行 MOD 内任何脚本。",
        { cancelable: true, onCancel: abortActiveRequest }
    );
    setProgressStep(0, "done", file.name);
    setProgressStep(1, "active", "正在上传...");
    setMessage($("#modMsg"), `正在上传 ${file.name}...`);
    try {
        const data = await api("/api/mods/upload", { method: "POST", body: formData, controller: state.activeAbortController, timeout: 0 });
        setProgressStep(1, "done", "上传完成");
        setProgressStep(2, "done", `${modTypeLabel(data.mod?.type)} 已导入`);
        setProgressStep(3, "active", "正在刷新列表...");
        showToast(data.message || "MOD 上传完成", "success");
        await loadMods(false);
        setProgressStep(3, "done", "列表已刷新");
        finishProgressDialog(data.message || "MOD 上传并导入完成", "success");
        setMessage($("#modMsg"), data.message || "MOD 上传并导入完成，重启服务器后生效。", "success");
    } catch (error) {
        setProgressStep(1, "error", error.message);
        finishProgressDialog(error.message, "error");
        setMessage($("#modMsg"), error.message, "error");
        showToast(error.message, "error");
    } finally {
        input.value = "";
        state.activeAbortController = null;
        setModControlsBusy(false);
    }
}

async function toggleMod(mod) {
    if (state.modBusy) return;
    const enabling = !mod.enabled;
    const isOfficial = mod.type === "official";
    const confirmed = await openDialog({
        eyebrow: "Mod Manager",
        title: `${enabling ? "启用" : "禁用"} MOD：${mod.name || mod.id}`,
        text: isOfficial && enabling
            ? "官方 Info.json 服务端 MOD 目前官方标注仅 Windows dedicated server 支持。当前 Linux/Docker 后端允许受控启用，但可能无效或导致服务器异常。确认后才会写入 ActiveModList。"
            : "启用或禁用 MOD 只会移动受管理的文件。变更需要重启 Palworld 后生效。",
        submitText: enabling ? "确认启用" : "确认禁用",
        danger: isOfficial && enabling,
    });
    if (!confirmed) return;

    setModControlsBusy(true);
    setMessage($("#modMsg"), `${enabling ? "正在启用" : "正在禁用"} MOD...`);
    try {
        const data = await api(enabling ? "/api/mods/enable" : "/api/mods/disable", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mod_id: mod.id, allow_official: isOfficial && enabling }),
        });
        setMessage($("#modMsg"), data.message || "MOD 状态已更新，重启后生效。", "success");
        showToast(data.message || "MOD 状态已更新", "success");
        await loadMods(false);
    } catch (error) {
        setMessage($("#modMsg"), error.message, "error");
        showToast(error.message, "error");
    } finally {
        setModControlsBusy(false);
    }
}

async function deleteMod(mod) {
    if (state.modBusy) return;
    const confirmed = await openDialog({
        eyebrow: "Delete Mod",
        title: `移入废纸篓：${mod.name || mod.id}`,
        text: "文件会移动到面板 MOD 库的 trash 目录，不会直接物理删除。若 MOD 当前启用，重启服务器后才会完全生效。",
        submitText: "确认移入废纸篓",
        danger: true,
    });
    if (!confirmed) return;

    setModControlsBusy(true);
    setMessage($("#modMsg"), "正在移动 MOD 到废纸篓...");
    try {
        const data = await api(`/api/mods/${encodeURIComponent(mod.id)}`, { method: "DELETE" });
        setMessage($("#modMsg"), data.message || "MOD 已移入废纸篓。", "success");
        showToast(data.message || "MOD 已移入废纸篓", "success");
        await loadMods(false);
    } catch (error) {
        setMessage($("#modMsg"), error.message, "error");
        showToast(error.message, "error");
    } finally {
        setModControlsBusy(false);
    }
}

async function emptyModTrash() {
    if (state.modBusy) return;
    const confirmed = await openDialog({
        eyebrow: "Mod Trash",
        title: "清理 MOD 废纸篓",
        text: "这会永久删除面板 MOD 库 trash 目录中的项目。已启用和已禁用的 MOD 不会受影响。",
        submitText: "确认清理",
        danger: true,
    });
    if (!confirmed) return;

    setModControlsBusy(true);
    setMessage($("#modMsg"), "正在清理 MOD 废纸篓...");
    try {
        const data = await api("/api/mods/empty_trash", { method: "POST" });
        setMessage($("#modMsg"), data.message || "MOD 废纸篓已清理。", "success");
        showToast(data.message || "MOD 废纸篓已清理", "success");
        await loadMods(false);
    } catch (error) {
        setMessage($("#modMsg"), error.message, "error");
        showToast(error.message, "error");
    } finally {
        setModControlsBusy(false);
    }
}

async function applyModsRestart() {
    if (state.modBusy) return;
    const confirmed = await openDialog({
        eyebrow: "Apply Mods",
        title: "应用 MOD 变更并重启",
        text: "面板会先尝试备份当前存档，然后重启 Palworld，让启用、禁用或删除的 MOD 生效。",
        submitText: "备份并重启",
        danger: true,
    });
    if (!confirmed) return;

    setModControlsBusy(true);
    openProgressDialog("应用 MOD 变更", ["备份当前存档", "重启服务", "等待恢复", "刷新状态"], "如果某个 MOD 不兼容，服务器可能启动失败，请查看实时日志。");
    setProgressStep(0, "active", "正在备份当前存档...");
    try {
        const data = await api("/api/mods/apply_restart", { method: "POST" });
        const backupStep = (data.steps || []).find((step) => step.step === "backup");
        setProgressStep(0, backupStep?.success === false ? "error" : "done", backupStep?.message || "备份步骤完成");
        setProgressStep(1, "done", "重启命令已执行");
        setProgressStep(2, data.running ? "done" : "error", data.running ? "服务器已恢复运行" : "未确认服务器恢复");
        setProgressStep(3, "active", "正在刷新状态...");
        await refreshAll();
        await loadMods(false);
        setProgressStep(3, "done", "状态已刷新");
        const hasFailedStep = (data.steps || []).some((step) => step.success === false);
        const ok = Boolean(data.success && data.running && !hasFailedStep);
        const resultMessage = ok
            ? (data.message || "MOD 变更已应用，服务器已恢复运行")
            : (data.message || "MOD 变更已提交，但未确认服务器恢复，请查看实时日志");
        finishProgressDialog(resultMessage, ok ? "success" : "error");
        setMessage($("#modMsg"), resultMessage, ok ? "success" : "error");
        showToast(resultMessage, ok ? "success" : "error");
    } catch (error) {
        setProgressStep(1, "error", error.message);
        finishProgressDialog(error.message, "error");
        setMessage($("#modMsg"), error.message, "error");
        showToast(error.message, "error");
    } finally {
        setModControlsBusy(false);
    }
}

function toggleLogAutoRefresh() {
    state.logAutoRefresh = !state.logAutoRefresh;
    $("#logAutoBtn").textContent = state.logAutoRefresh ? "自动刷新：开" : "自动刷新：关";
    $("#logAutoBtn").classList.toggle("is-on", state.logAutoRefresh);
}

function toggleLogAutoScroll() {
    state.logAutoScroll = !state.logAutoScroll;
    $("#logScrollBtn").textContent = state.logAutoScroll ? "自动滚动：开" : "自动滚动：关";
    $("#logScrollBtn").classList.toggle("is-on", state.logAutoScroll);
    renderLogLines();
}

function setLogLevel(level) {
    state.logLevel = level;
    $$(".terminal-filter").forEach((button) => {
        button.classList.toggle("is-active", button.dataset.logLevel === level);
    });
    renderLogLines();
}

function renderConfigForm() {
    const container = $("#configSections");
    container.replaceChildren(...configGroups.map((group) => {
        const section = document.createElement("section");
        section.className = "config-group";

        const title = document.createElement("h3");
        title.className = "config-title";
        const icon = document.createElement("span");
        icon.className = "config-icon";
        icon.textContent = group.icon || "•";
        const text = document.createElement("span");
        text.textContent = group.title;
        title.append(icon, text);
        section.appendChild(title);

        const grid = document.createElement("div");
        grid.className = "form-grid";
        group.fields.forEach((field) => grid.appendChild(createField(field)));
        section.appendChild(grid);
        return section;
    }));
}

function isRateField(key, meta) {
    return meta && typeof meta === "object" && (key.includes("Rate") || key.includes("Speed") || key.includes("Span"));
}

function getFieldHint(type, meta) {
    if (!meta || typeof meta !== "object" || Array.isArray(meta)) return "";
    const details = [];
    if (type === "number" && meta.min !== undefined && meta.max !== undefined) {
        details.push(`支持范围：${meta.min} - ${meta.max}`);
    }
    if (meta.hint) details.push(String(meta.hint).replace(/^范围：[^，。；]+[，。；]?\s*/, ""));
    return details.filter(Boolean).join("；");
}

function syncFieldState(input) {
    if (!input || !input.dataset.key) return;
    const field = input.closest(".field");
    if (!field) return;
    const key = input.dataset.key;
    const defaultValue = normalizeSubmitValue(key, configDefaults[key]);
    const currentValue = normalizeSubmitValue(key, input.value);
    const range = field.querySelector("input[type='range']");
    const defaultBadge = field.querySelector("[data-default-badge]");
    if (range && range.value !== input.value) range.value = input.value;
    if (defaultBadge) {
        defaultBadge.textContent = String(currentValue) === String(defaultValue) ? "默认值" : "已自定义";
        defaultBadge.classList.toggle("is-default", String(currentValue) === String(defaultValue));
    }
}

function updateConfigDirtyState() {
    state.configDirty = getConfigDiff(collectConfig()).length > 0;
}

function createField([key, label, type, meta]) {
    const wrapper = document.createElement("div");
    wrapper.className = "field";
    const fieldHint = getFieldHint(type, meta);
    if (fieldHint.includes("性能压力") || fieldHint.includes("服务器负载")) wrapper.classList.add("is-risk");

    const labelEl = document.createElement("label");
    labelEl.htmlFor = `cfg_${key}`;
    const labelText = document.createElement("span");
    labelText.textContent = label;
    const badgeRow = document.createElement("span");
    badgeRow.className = "field-badges";
    if (configDefaults[key] !== undefined) {
        const defaultBadge = document.createElement("b");
        defaultBadge.dataset.defaultBadge = "true";
        defaultBadge.textContent = "默认值";
        badgeRow.appendChild(defaultBadge);
    }
    const recommendValue = meta && typeof meta === "object" && (meta.recommend ?? configDefaults[key]);
    if (recommendValue !== undefined && recommendValue !== null && recommendValue !== "") {
        const recBadge = document.createElement("b");
        recBadge.className = "is-recommend";
        recBadge.textContent = `推荐 ${stripQuotes(recommendValue)}`;
        badgeRow.appendChild(recBadge);
    }
    if (wrapper.classList.contains("is-risk")) {
        const riskBadge = document.createElement("b");
        riskBadge.className = "is-risk";
        riskBadge.textContent = "高影响";
        badgeRow.appendChild(riskBadge);
    }
    labelEl.append(labelText, badgeRow);
    wrapper.appendChild(labelEl);

    let input;
    if (type === "bool") {
        input = document.createElement("select");
        [["True", "开启"], ["False", "关闭"]].forEach(([value, text]) => {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = text;
            input.appendChild(option);
        });
    } else if (type === "select") {
        input = document.createElement("select");
        meta.forEach(([value, text]) => {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = text;
            input.appendChild(option);
        });
    } else {
        input = document.createElement("input");
        input.type = type;
        if (typeof meta === "string") input.step = meta;
        if (meta && typeof meta === "object") {
            if (meta.step) input.step = meta.step;
            if (meta.min !== undefined) input.min = meta.min;
            if (meta.max !== undefined) input.max = meta.max;
        }
    }

    input.id = `cfg_${key}`;
    input.dataset.key = key;
    wrapper.appendChild(input);
    input.addEventListener("input", () => {
        syncFieldState(input);
        updateConfigDirtyState();
    });

    if (type === "number" && isRateField(key, meta)) {
        const control = document.createElement("div");
        control.className = "field-slider-row";
        const slider = document.createElement("input");
        slider.type = "range";
        slider.min = input.min || "0";
        slider.max = input.max || "10";
        slider.step = input.step || "0.1";
        slider.addEventListener("input", () => {
            input.value = slider.value;
            syncFieldState(input);
            updateConfigDirtyState();
        });
        const reset = document.createElement("button");
        reset.type = "button";
        reset.className = "field-reset";
        reset.textContent = "重置";
        reset.addEventListener("click", () => {
            input.value = stripQuotes(configDefaults[key] ?? "");
            syncFieldState(input);
            updateConfigDirtyState();
        });
        control.append(slider, reset);
        wrapper.appendChild(control);
    }

    if (fieldHint) {
        const hint = document.createElement("p");
        hint.className = "field-hint";
        if (fieldHint.includes("性能压力") || fieldHint.includes("服务器负载") || key.includes("Port")) hint.classList.add("is-warning");
        if (key.includes("Password")) hint.classList.add("is-danger");
        hint.textContent = fieldHint;
        wrapper.appendChild(hint);
    }
    return wrapper;
}

async function loadConfig() {
    if (state.configDirty) return;
    try {
        const data = await api("/api/config");
        if (state.configDirty) {
            setMessage($("#configMsg"), "配置读取完成，但保留了尚未保存的本地改动。", "warn");
            return;
        }
        const settings = { ...configDefaults, ...(data.settings || {}) };
        state.currentConfig = {};
        $$("[data-key]").forEach((input) => {
            const value = settings[input.dataset.key];
            input.value = stripQuotes(value);
            state.currentConfig[input.dataset.key] = normalizeSubmitValue(input.dataset.key, value);
            syncFieldState(input);
        });
        state.configDirty = false;
    } catch (error) {
        setMessage($("#configMsg"), `读取配置失败：${error.message}`, "error");
    }
}

function collectConfig() {
    const config = {};
    $$("[data-key]").forEach((input) => {
        const key = input.dataset.key;
        config[key] = normalizeSubmitValue(key, input.value);
    });
    return config;
}

function getFieldLabel(key) {
    const input = $$("[data-key]").find((field) => field.dataset.key === key);
    const label = input?.closest(".field")?.querySelector("label");
    return label?.querySelector("span:first-child")?.textContent || label?.textContent || key;
}

function formatDiffValue(key, value) {
    if (key.toLowerCase().includes("password")) return value ? "********" : "空";
    const text = stringFields.has(key) ? stripQuotes(value) : String(value ?? "");
    return text === "" ? "空" : text;
}

function getConfigDiff(nextConfig) {
    return Object.keys(nextConfig)
        .filter((key) => String(state.currentConfig[key] ?? "") !== String(nextConfig[key] ?? ""))
        .sort((a, b) => getFieldLabel(a).localeCompare(getFieldLabel(b), "zh-CN"))
        .map((key) => ({
            key,
            label: getFieldLabel(key),
            oldValue: formatDiffValue(key, state.currentConfig[key]),
            newValue: formatDiffValue(key, nextConfig[key]),
        }));
}

function getConfigGroupTitle(key) {
    return configGroups.find((group) => group.fields.some((field) => field[0] === key))?.title || "其他配置";
}

function showConfigDiffConfirm(diffs, restart) {
    const modal = $("#configConfirmModal");
    const list = $("#configDiffList");
    $("#configConfirmTitle").textContent = restart ? "确认保存并重启" : "确认保存配置";
    $("#configConfirmText").textContent = restart
        ? "这些改动会保存到配置文件，并立即重启 Palworld 服务器。"
        : "这些改动会保存到配置文件，重启 Palworld 后生效。";
    $("#configConfirmSubmit").textContent = restart ? "确认保存并重启" : "确认保存";

    const groups = new Map();
    diffs.forEach((diff) => {
        const title = getConfigGroupTitle(diff.key);
        if (!groups.has(title)) groups.set(title, []);
        groups.get(title).push(diff);
    });

    list.replaceChildren(...Array.from(groups.entries()).map(([titleText, groupDiffs]) => {
        const group = document.createElement("section");
        group.className = "diff-group";
        const title = document.createElement("h3");
        title.textContent = titleText;
        group.appendChild(title);
        groupDiffs.forEach((diff) => {
            const item = document.createElement("div");
            item.className = "diff-item";

            const label = document.createElement("span");
            label.className = "diff-label";
            label.textContent = diff.label;
            item.appendChild(label);

            const values = document.createElement("div");
            values.className = "diff-values";
            [diff.oldValue, "→", diff.newValue].forEach((value, index) => {
                const node = document.createElement("span");
                node.className = index === 1 ? "diff-arrow" : "diff-value";
                node.textContent = value;
                values.appendChild(node);
            });
            item.appendChild(values);
            group.appendChild(item);
        });
        return group;
    }));

    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");

    return new Promise((resolve) => {
        state.configConfirmResolve = resolve;
    });
}

function closeConfigDiffConfirm(result) {
    const modal = $("#configConfirmModal");
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    if (state.configConfirmResolve) {
        state.configConfirmResolve(result);
        state.configConfirmResolve = null;
    }
}

function validateConfig() {
    const errors = [];
    $$("[data-key]").forEach((input) => {
        if (input.type !== "number" || input.value.trim() === "") return;
        const value = Number(input.value);
        const min = input.min === "" ? null : Number(input.min);
        const max = input.max === "" ? null : Number(input.max);
        const step = input.step === "" || input.step === "any" ? null : Number(input.step);
        const label = input.closest(".field")?.querySelector("label")?.textContent || input.dataset.key;

        if (!Number.isFinite(value)) {
            errors.push(`${label} 必须是数字`);
        } else if (min !== null && value < min) {
            errors.push(`${label} 不能低于 ${min}`);
        } else if (max !== null && value > max) {
            errors.push(`${label} 不能高于 ${max}`);
        } else if (step !== null && Number.isFinite(step) && step > 0) {
            const base = min ?? 0;
            const steps = (value - base) / step;
            if (Math.abs(steps - Math.round(steps)) > 1e-9) {
                errors.push(step === 1 ? `${label} 必须是整数` : `${label} 必须按 ${step} 递增`);
            }
        }
    });
    return errors;
}

async function saveConfig(restart) {
    const saveButton = $("#saveConfigBtn");
    const restartButton = $("#saveRestartBtn");
    const configPanel = $("#tab-config .panel");
    const originalSaveText = saveButton.textContent;
    const originalRestartText = restartButton.textContent;

    saveButton.disabled = true;
    restartButton.disabled = true;
    const busyButton = restart ? restartButton : saveButton;
    busyButton.classList.add("is-busy");
    if (restart) restartButton.textContent = "保存并重启中...";
    else saveButton.textContent = "保存中...";

    const validationErrors = validateConfig();
    if (validationErrors.length) {
        setMessage($("#configMsg"), validationErrors.slice(0, 3).join("；"), "error");
        showToast("配置校验未通过", "error");
        saveButton.disabled = false;
        restartButton.disabled = false;
        busyButton.classList.remove("is-busy");
        saveButton.textContent = originalSaveText;
        restartButton.textContent = originalRestartText;
        return;
    }

    const config = collectConfig();
    const diffs = getConfigDiff(config);
    if (!diffs.length) {
        setMessage($("#configMsg"), "没有配置改动，不需要保存。");
        showToast("没有配置改动", "info");
        saveButton.disabled = false;
        restartButton.disabled = false;
        busyButton.classList.remove("is-busy");
        saveButton.textContent = originalSaveText;
        restartButton.textContent = originalRestartText;
        return;
    }

    const confirmed = await showConfigDiffConfirm(diffs, restart);
    if (!confirmed) {
        setMessage($("#configMsg"), "已取消保存，配置没有变化。");
        showToast("已取消保存", "info");
        saveButton.disabled = false;
        restartButton.disabled = false;
        busyButton.classList.remove("is-busy");
        saveButton.textContent = originalSaveText;
        restartButton.textContent = originalRestartText;
        return;
    }

    if (restart) {
        openProgressDialog("保存并重启", ["保存配置", "发送重启", "等待服务恢复", "刷新状态"], "配置会先写入文件，然后重启 Palworld 服务。");
        setProgressStep(0, "active", "正在保存配置...");
    }

    setMessage($("#configMsg"), restart ? "正在保存配置，并向服务器发送重启指令..." : "正在保存配置...");
    if (configPanel) configPanel.classList.add("is-working");
    try {
        const changes = Object.fromEntries(diffs.map((diff) => [diff.key, config[diff.key]]));
        const data = await api(restart ? "/api/config/apply_restart" : "/api/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(changes),
        });
        if (!data.success) {
            setMessage($("#configMsg"), data.message || "保存失败", "error");
            showToast(data.message || "保存失败", "error");
            if (restart) {
                setProgressStep(0, "error", data.message || "保存失败");
                finishProgressDialog(data.message || "保存失败", "error");
            }
            return;
        }

        if (restart) {
            setProgressStep(0, "done", "配置已保存");
            setProgressStep(1, "done", "重启指令已发送");
            setProgressStep(2, "active", "正在等待服务恢复...");
            restartButton.textContent = "等待服务器恢复...";
            setMessage($("#configMsg"), "配置已保存，服务器正在重启；正在等待状态恢复...");
            state.currentConfig = { ...config };
            updateConfigDirtyState();
            const restored = await waitForServerAfterRestart(true);
            if (restored) {
                setProgressStep(2, "done", "服务已恢复");
                setProgressStep(3, "done", "状态已刷新");
                finishProgressDialog("保存并重启完成，服务器已恢复运行。");
            }
        } else {
            state.currentConfig = { ...config };
            updateConfigDirtyState();
            setMessage($("#configMsg"), "配置已保存。重启 Palworld 后配置才会生效。", "success");
            showToast("配置已保存", "success");
        }
    } catch (error) {
        setMessage($("#configMsg"), error.message, "error");
        showToast(error.message, "error");
        if (restart) {
            setProgressStep(2, "error", error.message);
            finishProgressDialog(error.message, "error");
        }
    } finally {
        saveButton.disabled = false;
        restartButton.disabled = false;
        busyButton.classList.remove("is-busy");
        if (configPanel) configPanel.classList.remove("is-working");
        saveButton.textContent = originalSaveText;
        restartButton.textContent = originalRestartText;
    }
}

async function waitForServerAfterRestart(updateProgress = false) {
    const startedAt = Date.now();
    const timeoutMs = 90000;
    let attempt = 0;

    while (Date.now() - startedAt < timeoutMs) {
        attempt += 1;
        await new Promise((resolve) => setTimeout(resolve, attempt < 3 ? 3000 : 5000));

        try {
            const generation = ++state.requestGenerations.status;
            const data = await api("/api/status");
            if (generation === state.requestGenerations.status) renderStatus(data);
            if (data.status && data.status.running) {
                setMessage($("#configMsg"), "配置已保存，服务器重启完成并已恢复运行。", "success");
                showToast("服务器已恢复运行", "success");
                if (updateProgress) setProgressStep(3, "active", "正在刷新最终状态...");
                return true;
            }
            setMessage($("#configMsg"), "配置已保存，服务器仍在重启中...");
            if (updateProgress) setProgressStep(2, "active", `等待恢复中，第 ${attempt} 次检查`);
        } catch (error) {
            setMessage($("#configMsg"), `配置已保存，正在等待服务器恢复连接：${error.message}`);
            if (updateProgress) setProgressStep(2, "active", `等待连接恢复：${error.message}`);
        }
    }

    setMessage($("#configMsg"), "配置已保存，但 90 秒内没有确认服务器恢复。请查看实时日志或稍后刷新状态。", "error");
    showToast("未确认服务器恢复，请查看日志", "warn");
    if (updateProgress) {
        setProgressStep(2, "error", "90 秒内未确认恢复");
        finishProgressDialog("配置已保存，但未确认服务器恢复。请查看日志。", "error");
    }
    return false;
}

async function loadSaves(showLoading = true) {
    if (state.saveLoading) return;
    state.saveLoading = true;
    const msg = $("#saveMsg");
    if (showLoading) setMessage(msg, "正在读取存档信息...");
    try {
        const [statusData, slotsData] = await Promise.all([
            api("/api/saves/status"),
            api("/api/saves/slots"),
        ]);
        updateUploadLimit("save", statusData);
        state.saveStatus = statusData;
        state.saveSlots = slotsData.slots || [];
        renderSaveStatus();
        renderSaveSlots();
        if (showLoading) setMessage(msg, "存档信息已刷新。", "success");
    } catch (error) {
        setMessage(msg, error.message, "error");
        showToast(error.message, "error");
    } finally {
        state.saveLoading = false;
    }
}

function setSaveControlsBusy(isBusy) {
    state.saveBusy = isBusy;
    const savePanel = $("#tab-saves .panel");
    if (savePanel) savePanel.classList.toggle("is-working", isBusy);
    [
        "#refreshSavesBtn",
        "#backupCurrentSaveBtn",
        "#createSaveSlotBtn",
        "#importSaveSlotBtn",
        "#uploadSaveSlotBtn",
    ].forEach((selector) => {
        const button = $(selector);
        if (!button) return;
        button.disabled = isBusy;
        button.classList.toggle("is-busy", isBusy);
    });
    $$("#saveSlotList button").forEach((button) => {
        button.disabled = isBusy || button.dataset.locked === "true";
        button.classList.toggle("is-busy", isBusy);
    });
}

function createSaveMeta(label, value) {
    const item = document.createElement("span");
    const key = document.createElement("b");
    key.textContent = label;
    const text = document.createElement("span");
    text.textContent = value;
    item.append(key, text);
    return item;
}

function renderSaveStatus() {
    const card = $("#activeSaveCard");
    const active = state.saveStatus?.active || {};
    const service = state.saveStatus?.service || {};
    const dashboardWorld = $("#dashboardSaveWorld");
    const dashboardMeta = $("#dashboardSaveMeta");
    if (dashboardWorld) dashboardWorld.textContent = active.world_id || "未检测到";
    if (dashboardMeta) {
        dashboardMeta.textContent = active.world_id
            ? `${formatBytes(active.size_bytes)} · ${formatOptional(active.updated_at)}`
            : "等待存档状态";
    }
    if (!card) return;

    const title = document.createElement("div");
    const eyebrow = document.createElement("p");
    eyebrow.className = "eyebrow";
    eyebrow.textContent = "Active World";
    const name = document.createElement("h3");
    name.textContent = active.world_id || "未检测到当前世界 ID";
    const desc = document.createElement("p");
    desc.className = "muted";
    desc.textContent = active.path || "当前 SaveGames 目录暂无可识别存档";
    title.append(eyebrow, name, desc);

    const badge = document.createElement("span");
    badge.className = `status-pill ${service.running ? "is-online" : "is-offline"}`;
    badge.textContent = service.running ? "服务器运行中" : "服务器已停止";

    const meta = document.createElement("div");
    meta.className = "save-slot-meta";
    meta.append(
        createSaveMeta("大小", formatBytes(active.size_bytes)),
        createSaveMeta("更新时间", formatOptional(active.updated_at)),
        createSaveMeta("存档根目录", formatOptional(active.savegames_root))
    );

    card.replaceChildren(title, badge, meta);
}

function saveTimelineGroup(slot) {
    const raw = slot.last_used_at || slot.updated_at || slot.created_at;
    if (!raw) return "更早";
    const normalized = String(raw).replace(/([+-]\d{2})(\d{2})$/, "$1:$2");
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) return "更早";
    const now = new Date();
    const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const startYesterday = startToday - 86400000;
    const time = date.getTime();
    if (time >= startToday) return "今天";
    if (time >= startYesterday) return "昨天";
    return "更早";
}

function saveSourceLabel(slot) {
    if (slot.is_active) return "当前使用";
    if (slot.is_same_world_copy) return "同世界副本";
    if (slot.source === "imported") return "导入";
    if (slot.is_new) return "新世界";
    return "备用";
}

function renderSaveSlots() {
    const list = $("#saveSlotList");
    if (!list) return;
    const slots = state.saveSlots || [];
    if (!slots.length) {
        const empty = document.createElement("div");
        empty.className = "empty save-empty";
        empty.textContent = "还没有存档槽。可以先创建新档，或把外部存档放到导入目录后导入。";
        list.replaceChildren(empty);
        return;
    }

    const groups = new Map();
    slots.forEach((slot) => {
        const group = slot.is_active ? "主存档保险箱" : saveTimelineGroup(slot);
        if (!groups.has(group)) groups.set(group, []);
        groups.get(group).push(slot);
    });

    const groupOrder = ["主存档保险箱", "今天", "昨天", "更早"];
    list.replaceChildren(...groupOrder.filter((group) => groups.has(group)).map((group) => {
        const section = document.createElement("section");
        section.className = "save-timeline-group";
        const heading = document.createElement("h3");
        heading.textContent = group;
        section.appendChild(heading);
        groups.get(group).forEach((slot) => {
        const card = document.createElement("article");
        card.className = `save-slot-card ${slot.is_active ? "is-active" : ""}`.trim();

        const header = document.createElement("div");
        header.className = "save-slot-head";
        const heading = document.createElement("div");
        const title = document.createElement("h3");
        title.textContent = slot.name || slot.id;
        const subtitle = document.createElement("p");
        subtitle.className = "muted";
        subtitle.textContent = slot.is_new ? "新世界槽，切换后由 Palworld 自动生成世界文件" : `World ID: ${slot.world_id || "-"}`;
        heading.append(title, subtitle);

        const badge = document.createElement("span");
        badge.className = `soft-pill ${slot.is_active ? "is-success" : ""}`.trim();
        badge.textContent = saveSourceLabel(slot);
        header.append(heading, badge);

        const meta = document.createElement("div");
        meta.className = "save-slot-meta";
        meta.append(
            createSaveMeta("槽 ID", slot.id),
            createSaveMeta("大小", formatBytes(slot.size_bytes)),
            createSaveMeta("更新时间", formatOptional(slot.updated_at)),
            createSaveMeta("最近使用", formatOptional(slot.last_used_at, "未使用")),
            createSaveMeta("来源", saveSourceLabel(slot))
        );

        const notes = document.createElement("p");
        notes.className = "save-notes";
        notes.textContent = slot.notes || "无备注";

        const actions = document.createElement("div");
        actions.className = "save-slot-actions";
        const switchButton = document.createElement("button");
        switchButton.className = "primary";
        switchButton.type = "button";
        switchButton.textContent = slot.is_active ? "当前存档" : "切换并启动";
        switchButton.disabled = slot.is_active;
        switchButton.dataset.locked = slot.is_active ? "true" : "false";
        switchButton.addEventListener("click", () => switchSaveSlot(slot.id, slot.name || slot.id));

        const deleteButton = document.createElement("button");
        deleteButton.className = "save-more-action";
        deleteButton.type = "button";
        deleteButton.textContent = "删除";
        deleteButton.disabled = slot.is_active;
        deleteButton.dataset.locked = slot.is_active ? "true" : "false";
        deleteButton.addEventListener("click", () => deleteSaveSlot(slot.id, slot.name || slot.id));
        const more = document.createElement("details");
        more.className = "save-more";
        const summary = document.createElement("summary");
        summary.textContent = "更多";
        more.append(summary, deleteButton);
        actions.append(switchButton, more);

        card.append(header, meta, notes, actions);
        section.appendChild(card);
        });
        return section;
    }));
}

async function backupCurrentSave() {
    if (state.saveBusy) return;
    const confirmed = await openDialog({
        eyebrow: "Save Backup",
        title: "确认备份当前存档",
        text: "手动备份要求 Palworld 服务已停止。请确认当前状态适合备份。",
        submitText: "开始备份",
    });
    if (!confirmed) return;
    setSaveControlsBusy(true);
    setMessage($("#saveMsg"), "正在备份当前存档...");
    try {
        const data = await api("/api/saves/backup_current", { method: "POST" });
        setMessage($("#saveMsg"), data.message || "当前存档已备份。", "success");
        showToast(data.message || "当前存档已备份", "success");
        await loadSaves(false);
    } catch (error) {
        setMessage($("#saveMsg"), error.message, "error");
        showToast(error.message, "error");
    } finally {
        setSaveControlsBusy(false);
    }
}

async function createSaveSlot() {
    if (state.saveBusy) return;
    const values = await openDialog({
        eyebrow: "New Save",
        title: "创建新存档槽",
        text: "切换到新存档槽后，Palworld 会自动生成新世界文件。",
        submitText: "创建存档",
        fields: [
            { name: "name", label: "存档名称", required: true, placeholder: "例如：新世界测试档" },
            { name: "notes", label: "备注", type: "textarea", placeholder: "可留空" },
        ],
    });
    if (!values) return;
    const name = values.name;
    const notes = values.notes || "";
    setSaveControlsBusy(true);
    setMessage($("#saveMsg"), "正在创建新存档槽...");
    try {
        const data = await api("/api/saves/create_slot", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name.trim(), notes }),
        });
        setMessage($("#saveMsg"), data.message || "新存档槽已创建。", "success");
        showToast(data.message || "新存档槽已创建", "success");
        await loadSaves(false);
    } catch (error) {
        setMessage($("#saveMsg"), error.message, "error");
        showToast(error.message, "error");
    } finally {
        setSaveControlsBusy(false);
    }
}

async function importSaveSlot() {
    if (state.saveBusy) return;
    const hint = state.saveStatus?.import_hint || "/home/demo/palworld-panel/save-slots/imports";
    const values = await openDialog({
        eyebrow: "Import Save",
        title: "从服务器路径导入存档",
        text: "请输入服务器上的存档目录路径。建议先把外部存档放到导入目录。",
        submitText: "开始导入",
        fields: [
            { name: "sourcePath", label: "服务器存档路径", required: true, value: hint, hint: "可以是世界目录、SaveGames/0 目录或包含 SaveGames 的目录。" },
            { name: "name", label: "导入后的存档名称", required: true, placeholder: "例如：朋友发来的世界档" },
            { name: "notes", label: "备注", type: "textarea", placeholder: "可留空" },
        ],
    });
    if (!values) return;
    const sourcePath = values.sourcePath;
    const name = values.name;
    const notes = values.notes || "";
    setSaveControlsBusy(true);
    setMessage($("#saveMsg"), "正在导入存档...");
    try {
        const data = await api("/api/saves/import_slot", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ source_path: sourcePath.trim(), name: name.trim(), notes }),
        });
        setMessage($("#saveMsg"), data.message || "存档已导入。", "success");
        showToast(data.message || "存档已导入", "success");
        await loadSaves(false);
    } catch (error) {
        setMessage($("#saveMsg"), error.message, "error");
        showToast(error.message, "error");
    } finally {
        setSaveControlsBusy(false);
    }
}

async function uploadSaveSlot() {
    if (state.saveBusy) return;
    const input = $("#saveUploadInput");
    const file = input?.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".zip")) {
        setMessage($("#saveMsg"), "请上传 .zip 格式的存档包。", "error");
        showToast("只支持 .zip 存档包", "error");
        input.value = "";
        return;
    }

    if (file.size > state.saveUploadMaxBytes) {
        setMessage($("#saveMsg"), `存档包不能超过 ${formatBytes(state.saveUploadMaxBytes)}。`, "error");
        showToast("存档包太大", "error");
        input.value = "";
        return;
    }

    const defaultName = file.name.replace(/\.zip$/i, "");
    const values = await openDialog({
        eyebrow: "Upload Save",
        title: "上传并导入存档",
        text: `已选择：${file.name}`,
        submitText: "上传导入",
        fields: [
            { name: "name", label: "导入后的存档名称", required: true, value: defaultName },
            { name: "notes", label: "备注", type: "textarea", placeholder: "可留空" },
        ],
    });
    if (!values) {
        input.value = "";
        return;
    }
    const name = values.name;
    const notes = values.notes || "";
    const formData = new FormData();
    formData.append("file", file);
    formData.append("name", name.trim());
    formData.append("notes", notes);

    setSaveControlsBusy(true);
    state.activeAbortController = new AbortController();
    openProgressDialog(
        "上传并导入存档",
        ["选择文件", "上传 ZIP", "解压导入", "刷新列表"],
        "大存档可能需要一些时间，请保持页面打开。",
        { cancelable: true, onCancel: abortActiveRequest }
    );
    setProgressStep(0, "done", file.name);
    setProgressStep(1, "active", "正在上传...");
    setMessage($("#saveMsg"), `正在上传并导入 ${file.name}，大存档可能需要一些时间...`);
    showToast("开始上传存档", "info");
    try {
        const data = await api("/api/saves/upload_slot", {
            method: "POST",
            body: formData,
            controller: state.activeAbortController,
            timeout: 0,
        });
        setProgressStep(1, "done", "上传完成");
        setProgressStep(2, "done", "解压并导入完成");
        setProgressStep(3, "active", "正在刷新列表...");
        setMessage($("#saveMsg"), data.message || "存档上传并导入完成。", "success");
        showToast(data.message || "存档上传完成", "success");
        await loadSaves(false);
        setProgressStep(3, "done", "列表已刷新");
        finishProgressDialog(data.message || "存档上传并导入完成。");
    } catch (error) {
        setProgressStep(1, "error", error.message);
        finishProgressDialog(error.message, "error");
        setMessage($("#saveMsg"), error.message, "error");
        showToast(error.message, "error");
    } finally {
        input.value = "";
        state.activeAbortController = null;
        setSaveControlsBusy(false);
    }
}

function renderSwitchSteps(steps = []) {
    if (!steps.length) return "切换完成。";
    return steps.map((item) => {
        const status = item.success ? "完成" : "失败";
        return `${item.step}: ${status}${item.message ? ` - ${item.message}` : ""}`;
    }).join("\n");
}

async function switchSaveSlot(slotId, name) {
    if (state.saveBusy) return;
    const confirmed = await openDialog({
        eyebrow: "Switch Save",
        title: `切换到“${name}”`,
        text: "流程会自动停止 Palworld、备份当前存档、替换存档、修正权限，然后重新启动服务器。",
        submitText: "切换并启动",
        danger: true,
    });
    if (!confirmed) return;
    setSaveControlsBusy(true);
    openProgressDialog("切换存档", ["停止服务", "备份当前存档", "替换存档", "修复权限", "启动服务", "完成"], `目标存档：${name}`);
    setProgressStep(0, "active", "正在停止 Palworld...");
    setMessage($("#saveMsg"), "正在切换存档：停服、备份、替换、启动中，请等待...");
    showToast("开始切换存档，请等待完成", "info");
    try {
        const data = await api("/api/saves/switch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ slot_id: slotId }),
        });
        (data.steps || []).forEach((step, index) => {
            setProgressStep(index, step.success ? "done" : "error", step.message || (step.success ? "完成" : "失败"));
        });
        const hasFailedStep = (data.steps || []).some((step) => step.success === false);
        const ok = Boolean(data.success && data.running && !hasFailedStep);
        const resultMessage = ok
            ? (data.message || "存档切换完成，服务器已恢复运行")
            : (data.message || "存档切换流程结束，但未确认服务器恢复，请查看实时日志");
        setProgressStep(5, ok ? "done" : "error", resultMessage);
        setMessage($("#saveMsg"), `${resultMessage}\n${renderSwitchSteps(data.steps)}`, ok ? "success" : "error");
        showToast(resultMessage, ok ? "success" : "error");
        await refreshAll();
        await loadSaves(false);
        finishProgressDialog(resultMessage, ok ? "success" : "error");
    } catch (error) {
        setProgressStep(0, "error", error.message);
        finishProgressDialog(error.message, "error");
        setMessage($("#saveMsg"), error.message, "error");
        showToast(error.message, "error");
        await loadSaves(false);
    } finally {
        setSaveControlsBusy(false);
    }
}

async function deleteSaveSlot(slotId, name) {
    if (state.saveBusy) return;
    const confirmed = await openDialog({
        eyebrow: "Delete Save",
        title: `删除存档槽“${name}”`,
        text: "此操作不会删除当前正在使用的存档，但会删除该备用槽。删除后无法从面板恢复。",
        submitText: "确认删除",
        danger: true,
    });
    if (!confirmed) return;
    setSaveControlsBusy(true);
    setMessage($("#saveMsg"), "正在删除存档槽...");
    try {
        const data = await api(`/api/saves/slots/${encodeURIComponent(slotId)}`, { method: "DELETE" });
        setMessage($("#saveMsg"), data.message || "存档槽已删除。", "success");
        showToast(data.message || "存档槽已删除", "success");
        await loadSaves(false);
    } catch (error) {
        setMessage($("#saveMsg"), error.message, "error");
        showToast(error.message, "error");
    } finally {
        setSaveControlsBusy(false);
    }
}

function appendConsoleLine(text, className = "") {
    const output = $("#rconOutput");
    if (output.textContent === "等待命令...") output.textContent = "";
    const line = document.createElement("span");
    line.className = `console-line ${className || "response"}`.trim();
    line.textContent = text;
    output.appendChild(line);
    output.scrollTop = output.scrollHeight;
}

async function sendRcon(event) {
    event.preventDefault();
    const input = $("#rconInput");
    const command = input.value.trim();
    if (!command) return;
    input.value = "";
    await executeRconCommand(command);
}

async function executeRconCommand(command) {
    appendConsoleLine(`> ${command}`, "command");

    try {
        const data = await api("/api/rcon", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ command }),
            timeout: 15000,
        });
        if (data.success) {
            appendConsoleLine(data.response || data.message || "命令已送达", "response");
        } else {
            appendConsoleLine(`Error: ${data.message || "RCON command failed"}`, "error");
            showToast(data.message || "RCON command failed", "error");
        }
    } catch (error) {
        appendConsoleLine(`Error: ${error.message}`, "error");
        showToast(error.message, "error");
    }
}

async function quickRconCommand(command) {
    if (command === "Broadcast") {
        const values = await openDialog({
            eyebrow: "Broadcast",
            title: "广播消息",
            text: "向当前服务器内玩家发送一条公告。",
            submitText: "发送广播",
            fields: [
                { name: "message", label: "广播内容", required: true, placeholder: "服务器将在 5 分钟后重启" },
            ],
        });
        if (!values) return;
        const message = values.message.trim();
        if (/[^\x20-\x7E]/.test(message)) {
            const error = "Palworld RCON 广播仅可靠支持英文/ASCII 字符；中文或表情会被游戏端错误解析。";
            appendConsoleLine(`Error: ${error}`, "error");
            showToast(error, "error");
            return;
        }
        await executeRconCommand(`Broadcast ${message}`);
        return;
    }
    await executeRconCommand(command);
}

function bindEvents() {
    $("#refreshBtn").addEventListener("click", refreshAll);
    $("#themeSelect")?.addEventListener("change", (event) => setTheme(event.target.value));
    $("#motionSelect")?.addEventListener("change", (event) => setMotion(event.target.value));
    $("#loadLogBtn").addEventListener("click", loadLog);
    $("#logAutoBtn").addEventListener("click", toggleLogAutoRefresh);
    $("#logScrollBtn")?.addEventListener("click", toggleLogAutoScroll);
    $("#logSearchInput")?.addEventListener("input", (event) => {
        state.logSearch = event.target.value;
        renderLogLines();
    });
    $$(".terminal-filter").forEach((button) => {
        button.addEventListener("click", () => setLogLevel(button.dataset.logLevel));
    });
    $("#refreshSavesBtn").addEventListener("click", () => loadSaves(true));
    $("#backupCurrentSaveBtn").addEventListener("click", backupCurrentSave);
    $("#createSaveSlotBtn").addEventListener("click", createSaveSlot);
    $("#importSaveSlotBtn").addEventListener("click", importSaveSlot);
    $("#uploadSaveSlotBtn").addEventListener("click", () => {
        if (!state.saveBusy) $("#saveUploadInput").click();
    });
    $("#saveUploadInput").addEventListener("change", uploadSaveSlot);
    $("#refreshModsBtn").addEventListener("click", () => loadMods(true));
    $("#uploadModBtn").addEventListener("click", () => {
        if (!state.modBusy) $("#modUploadInput").click();
    });
    $("#modUploadInput").addEventListener("change", uploadMod);
    $("#applyModsRestartBtn").addEventListener("click", applyModsRestart);
    $("#emptyModTrashBtn").addEventListener("click", emptyModTrash);
    $("#saveConfigBtn").addEventListener("click", () => saveConfig(false));
    $("#saveRestartBtn").addEventListener("click", () => saveConfig(true));
    $("#checkUpdateBtn").addEventListener("click", checkUpdateNow);
    $("#applyUpdateBtn").addEventListener("click", applyUpdateNow);
    $("#checkInstallBtn").addEventListener("click", checkInstallNow);
    $("#installPalworldBtn").addEventListener("click", () => startInstallAction("install-palworld"));
    $("#repairInstallBtn").addEventListener("click", () => startInstallAction("repair"));
    $("#refreshAuditBtn").addEventListener("click", () => loadAudit(true));
    $$(".audit-filter").forEach((button) => {
        button.addEventListener("click", () => setAuditFilter(button.dataset.auditFilter));
    });
    $("#configConfirmCancel").addEventListener("click", () => closeConfigDiffConfirm(false));
    $("#configConfirmClose").addEventListener("click", () => closeConfigDiffConfirm(false));
    $("#configConfirmSubmit").addEventListener("click", () => closeConfigDiffConfirm(true));
    $("#configConfirmModal").addEventListener("click", (event) => {
        if (event.target.id === "configConfirmModal") closeConfigDiffConfirm(false);
    });
    $("#interactionModal").addEventListener("click", (event) => {
        if (event.target.id === "interactionModal" && !event.currentTarget.classList.contains("is-progress")) closeDialog(null);
    });
    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        if ($("#interactionModal")?.classList.contains("is-open") && !$("#interactionModal")?.classList.contains("is-progress")) {
            closeDialog(null);
        }
    });
    $("#rconForm").addEventListener("submit", sendRcon);
    $$(".quick-command").forEach((button) => {
        button.addEventListener("click", () => quickRconCommand(button.dataset.rconCommand));
    });
    $$(".tab-button").forEach((button) => {
        button.addEventListener("click", () => switchTab(button.dataset.tab));
    });
    $$("[data-action]").forEach((button) => {
        button.addEventListener("click", () => serverAction(button.dataset.action));
    });
    $(".tabs")?.addEventListener("scroll", updateTabIndicator, { passive: true });
    window.addEventListener("resize", () => {
        renderSystemCharts();
        updateTabIndicator();
    });
    window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", applyPreferences);
}

renderConfigForm();
applyPreferences();
initParticles();
initCursorGlow();
bindEvents();
updateTabIndicator();
refreshAll();
setInterval(refreshAll, 10000);
