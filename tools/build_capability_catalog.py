"""Build knowledge/game/capability_catalog.json from the operator's capability tree.

The operator's CAPABILITY-FIRST directive (2026-09-16) defines the full-game
capability tree and asks for it as machine-readable coverage.  Three rules shape
this builder:

* It is a COVERAGE TABLE, not a registry.  The directive is explicit that a second
  Skill Registry must not appear: ``winter_agent_v2.skills.v2_registry()`` stays the
  only table of executable skills, and this catalog only *points at* it.
* The capability codes are the operator's, transcribed verbatim.  IDs are
  ``CAP-<category><nn>`` (unique by construction); the operator's token (e.g.
  ``LAUNCH_GAME``) is kept as ``code`` because several categories legitimately reuse
  the same token (READ_SCORE appears in Z, AA and AI; CLAIM_REWARD in X, AE, AR, AV).
* Nothing here invents a status.  ``lifecycle`` is derived from real evidence --
  registry membership, ``LiveRuntime.VERIFIED_ATOMIC`` membership, and production
  episodes -- and stays UNKNOWN/MISSING when there is none.

Usage:  python tools/build_capability_catalog.py [--rank]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"E:\无尽冬日智能体")
sys.path.insert(0, str(ROOT))

OUT = ROOT / "knowledge/game/capability_catalog.json"

# ---------------------------------------------------------------------------
# The operator's tree, verbatim.  One line per category:
#   code | name | comma-separated capability tokens (in the order given)
# Categories the directive describes as a *mechanism* rather than a list of
# capabilities carry no tokens and are recorded in MECHANISM_CATEGORIES instead.
# ---------------------------------------------------------------------------
SPEC = """\
A|基础客户端 / Navigation / Recovery|LAUNCH_GAME,DETECT_HOME,DETECT_WORLD_MAP,HOME_TO_MAP,MAP_TO_HOME,BACK,CLOSE_POPUP,HANDLE_LOADING,HANDLE_NETWORK_ERROR,HANDLE_RECONNECT,HANDLE_UNKNOWN_PAGE,RECOVER_TO_SAFE_PAGE,DETECT_CURRENT_ROLE,DETECT_SERVER,DETECT_FURNACE_LEVEL,DETECT_FEATURE_UNLOCK,DETECT_RED_DOT,DETECT_FREE_CLAIM,DETECT_TIMER,DETECT_LOCKED_FEATURE
B|每日免费收益 / 奖励领取|CLAIM_DAILY_MISSION,CLAIM_GROWTH_MISSION,CLAIM_EVENT_MILESTONE,CLAIM_FREE_REWARD,CLAIM_ALL,CLAIM_MAIL,MAIL_READ,MAIL_COLLECT_ALL,CLAIM_VIP_DAILY,VIP_FREE_CHEST,CLAIM_LOGIN_REWARD,CLAIM_ONLINE_REWARD,CLAIM_CITY_BUBBLE,CLAIM_BUILDING_OUTPUT,CLAIM_IDLE_REWARD,CLAIM_EXPLORATION_CHEST,CLAIM_ALLIANCE_REWARD,CLAIM_EVENT_REWARD,GIFT_CODE,FREE_SHOP_ITEM
C|城市资源生产|COLLECT_MEAT,COLLECT_WOOD,COLLECT_COAL,COLLECT_IRON,COLLECT_CITY_RESOURCES,READ_RESOURCE_BALANCE,READ_PROTECTED_RESOURCE,RESOURCE_SHORTAGE_DETECT,RESOURCE_CONVERSION,MANAGE_RESOURCE_RESERVE
D|建筑 / 城市发展|DETECT_BUILDABLE,OPEN_BUILDING,READ_BUILDING_LEVEL,READ_BUILD_REQUIREMENT,START_BUILD,UPGRADE_BUILDING,BUILD_QUEUE_STATUS,CLAIM_BUILD_COMPLETE,USE_BUILD_SPEEDUP,REQUEST_ALLIANCE_HELP,FURNACE_UPGRADE,RESOURCE_BUILDING_UPGRADE,TROOP_CAMP_UPGRADE,EMBASSY_UPGRADE,INFIRMARY_UPGRADE,COMMAND_CENTER_UPGRADE,RESEARCH_CENTER_UPGRADE,BARRICADE_UPGRADE,OTHER_BUILDING_UPGRADE,FIRE_CRYSTAL_BUILDING,FC_BUILDING_SUBLEVEL,CRYSTAL_LAB
E|科技研究|OPEN_RESEARCH,READ_RESEARCH_TREE,FIND_AVAILABLE_RESEARCH,START_RESEARCH,CLAIM_RESEARCH_COMPLETE,USE_RESEARCH_SPEEDUP,ECONOMY_RESEARCH,GROWTH_RESEARCH,BATTLE_RESEARCH,OPEN_WAR_ACADEMY,FIRE_CRYSTAL_RESEARCH,HELIOS_T11_RESEARCH,EXALTED_T12_RESEARCH,EXCHANGE_FIRE_CRYSTAL_SHARDS
F|军队 / 训练 / 治疗|TRAIN_INFANTRY,TRAIN_LANCER,TRAIN_MARKSMAN,READ_TRAIN_QUEUE,CLAIM_TRAIN_COMPLETE,PROMOTE_INFANTRY,PROMOTE_LANCER,PROMOTE_MARKSMAN,TRAIN_HIGHEST_AVAILABLE_TIER,TROOP_COUNT_READ,WOUNDED_READ,HEAL,CLAIM_HEAL_COMPLETE,ENLIST_RESERVES,READ_INFIRMARY_CAPACITY
G|行军系统|READ_MARCH_CAPACITY,READ_MARCH_OCCUPANCY,OPEN_MARCH_PAGE,READ_MARCH_ENTRIES,SELECT_MARCH,FORMATION_SELECT,AUTO_FORMATION,HERO_SELECT,TROOP_SELECT,DISPATCH_MARCH,VERIFY_MARCH_STARTED,RECALL_MARCH,VERIFY_RETURNING,VERIFY_IDLE,MARCH_SPEEDUP,REINFORCE_ALLY,WITHDRAW_REINFORCEMENT
H|世界资源采集|OPEN_WORLD_SEARCH,SELECT_RESOURCE_MEAT,SELECT_RESOURCE_WOOD,SELECT_RESOURCE_COAL,SELECT_RESOURCE_IRON,SELECT_RESOURCE_LEVEL,SEARCH_RESOURCE,RESOURCE_NODE_AVAILABLE,START_GATHER,DISPATCH_GATHER,VERIFY_GATHERING,RECALL_GATHER,RESOURCE_NODE_DEPLETED,SEARCH_NEXT_RESOURCE,MULTI_MARCH_GATHER,GATHER_PRIORITY,GATHER_EVENT_AWARE
I|野兽 / 世界 PvE|SEARCH_BEAST,SELECT_BEAST_LEVEL,ATTACK_BEAST,VERIFY_BEAST_WIN,READ_STAMINA,STAMINA_POLICY,STAMINA_ITEM_USE,SEARCH_POLAR_TERROR,START_POLAR_TERROR_RALLY,JOIN_POLAR_TERROR_RALLY,VERIFY_RALLY,CLAIM_BEAST_REWARD
J|情报 / 灯塔|OPEN_LIGHTHOUSE,READ_INTEL_LIST,CLASSIFY_INTEL,SELECT_INTEL,EXECUTE_INTEL,CLAIM_INTEL,INTEL_REFRESH_STATE,INTEL_NOT_REFRESHED,SEARCHLIGHT_STATE,INTEL_COMPLETE_ALL
K|英雄系统|OPEN_HERO,HERO_ROSTER_READ,HERO_RECRUIT,FREE_RECRUIT,USE_RECRUIT_KEY,HERO_LEVEL_UP,HERO_STAR_UP,HERO_SKILL_UP,HERO_SHARD_USE,HERO_GEAR_EQUIP,HERO_GEAR_UPGRADE,HERO_GEAR_FORGE,HERO_EXCLUSIVE_GEAR_WIDGET,AUTO_HERO_FORMATION,HERO_GENERATION_DISCOVERY
L|Chief / 领主成长|READ_CHIEF_POWER,VIP_LEVEL,VIP_ACTIVATE,CHIEF_ORDER,CHIEF_GEAR,CHIEF_GEAR_UPGRADE,CHIEF_CHARM,CHIEF_CHARM_UPGRADE,SKIN_MANAGEMENT,CITY_SKIN,MARCH_SKIN,AVATAR_FRAME,TITLE_READ
M|探索 / PvE 关卡|OPEN_EXPLORATION,CLAIM_EXPLORATION_IDLE,CONTINUE_EXPLORING,SELECT_EXPLORATION_STAGE,AUTO_FORMATION_EXPLORATION,START_EXPLORATION,VERIFY_EXPLORATION_WIN,CLAIM_EXPLORATION_CHEST,STOP_ON_POWER_WALL
N|Arena 竞技场|OPEN_ARENA,READ_FREE_ATTEMPTS,READ_OPPONENTS,SELECT_ARENA_TARGET,START_ARENA,VERIFY_ARENA_RESULT,ARENA_REFRESH,CLAIM_ARENA_REWARD,USE_FREE_ARENA_ATTEMPTS
O|Labyrinth / 迷宫|OPEN_LABYRINTH,READ_STAGE,ENTER_LABYRINTH,SELECT_FORMATION,BATTLE_LABYRINTH,CLAIM_LABYRINTH_REWARD,STOP_AT_BLOCKED_STAGE
P|Daybreak Island / 黎明岛|OPEN_DAYBREAK_ISLAND,COLLECT_LIFE_ESSENCE,CLEAR_ISLAND_TREE,TREE_OF_LIFE_UPGRADE,ISLAND_BUILD,ISLAND_DECORATION,CLAIM_ISLAND_REWARD
Q|Pet / 宠物|OPEN_BEAST_CAGE,PET_DISCOVERY,PET_CAPTURE,PET_TAME,PET_LEVEL_UP,PET_ADVANCE,PET_REFINE,PET_SKILL,PET_TALENT_SKILL,PET_TREASURE_HUNT,CLAIM_PERSONAL_TREASURE,CLAIM_ALLY_TREASURE,PET_ADVENTURE,PET_FOOD,PET_STAMINA
R|Expert / Dawn Academy|OPEN_DAWN_ACADEMY,EXPERT_DISCOVERY,EXPERT_AFFINITY,EXPERT_SKILL,EXPERT_SIGIL,TUNDRA_TREK,FRONTIER_TREK,CLAIM_TUNDRA_SUPPLY,CLAIM_FRONTIER_SUPPLY,EXPERT_RESEARCH
S|Alliance 基础功能|OPEN_ALLIANCE,ALLIANCE_HELP,REQUEST_HELP,ALLIANCE_TECH,ALLIANCE_TECH_DONATE,ALLIANCE_GIFT,ALLIANCE_CHEST,ALLIANCE_TRIUMPH,ALLIANCE_SHOP,ALLIANCE_FREE_ITEM,ALLIANCE_RALLY_LIST,AUTO_JOIN_RALLY,JOIN_RALLY,START_RALLY,REINFORCE_MEMBER,ALLIANCE_NOTICE_READ
T|Alliance Territory|READ_ALLIANCE_TERRITORY,READ_HQ,READ_BANNER,READ_FACILITY,TERRITORY_RESOURCE,TERRITORY_TELEPORT,FACILITY_STATE,BUILD_HQ,BUILD_BANNER,REMOVE_BANNER
U|Bear Hunt / 巨熊|DISCOVER_BEAR_SCHEDULE,BEAR_COUNTDOWN,PREPARE_BEAR,FREE_MARCH_FOR_BEAR,OPEN_BEAR,JOIN_BEAR_RALLY,START_BEAR_RALLY,REPEAT_BEAR_ATTACK,READ_BEAR_ACTIVE,BEAR_FINISHED,CLAIM_BEAR_REWARD
V|Alliance Mobilization|OPEN_ALLIANCE_MOBILIZATION,READ_MOBILIZATION_TASK,SELECT_TASK,ACCEPT_TASK,EXECUTE_BY_EXISTING_SKILL,VERIFY_TASK_PROGRESS,CLAIM_MILESTONE
W|Alliance Showdown|OPEN_ALLIANCE_SHOWDOWN,READ_DAILY_SCORE_RULE,SELECT_SCORE_ACTION,EXECUTE_SCORE_ACTION,CLAIM_SHOWDOWN_REWARD
X|Alliance Championship|OPEN_ALLIANCE_CHAMPIONSHIP,READ_REGISTRATION,REGISTER_FORMATION,UPDATE_FORMATION,READ_RESULT,CLAIM_REWARD
Y|Crazy Joe|DISCOVER_CRAZY_JOE,READ_START_TIME,PREPARE_DEFENSE,REINFORCE_ALLY,REINFORCE_HQ,HANDLE_WAVES,CLAIM_CRAZY_JOE_REWARD
Z|Foundry Battle|REGISTER_FOUNDRY,ENTER_FOUNDRY,READ_BATTLEFIELD,CAPTURE_BUILDING,GARRISON_BUILDING,MOVE_TROOPS,RECALL_TROOPS,HEAL_FOUNDRY,READ_SCORE,EXIT_FOUNDRY
AA|Canyon Clash|REGISTER_CANYON,ENTER_CANYON,READ_OBJECTIVES,MARCH_OBJECTIVE,CAPTURE_OBJECTIVE,DEFEND_OBJECTIVE,READ_SCORE,EXIT_CANYON
AB|Sunfire Castle|DISCOVER_SUNFIRE,READ_CASTLE_STATE,READ_TURRETS,JOIN_CASTLE_RALLY,JOIN_TURRET_RALLY,REINFORCE,RECALL,READ_BATTLE_STATUS
AC|Fortress / Stronghold|DISCOVER_FORTRESS,READ_REGISTRATION,READ_OWNER,JOIN_FORTRESS_RALLY,DEFEND_FORTRESS,CLAIM_FORTRESS_REWARD
AD|State vs State / SVS|DISCOVER_SVS,READ_SVS_PHASE,READ_SCORE_RULE,READ_PROGRESS,SELECT_BEST_SCORE_ACTION,VERIFY_POINTS,CLAIM_SVS_MILESTONE,SVS_TELEPORT,SVS_DEFENSE,SVS_RALLY,SVS_REINFORCE,SVS_SHIELD
AE|Hall of Chiefs / King of Icefield|DISCOVER_HOC_OR_KOI,READ_CURRENT_DAY,READ_SCORE_RULE,SELECT_EXISTING_SKILL,VERIFY_SCORE,CLAIM_REWARD
AF|Lucky Wheel|OPEN_LUCKY_WHEEL,READ_FREE_SPIN,FREE_SPIN,READ_SPIN_COST,STRATEGY_SPIN,CLAIM_WHEEL_MILESTONE
AG|Hero Rally / Hall of Heroes|DISCOVER_HERO_EVENT,READ_HERO_GENERATION,READ_FREE_REWARD,HERO_SHARD_EXCHANGE,CLAIM_HERO_EVENT_REWARD
AI|Frostfire Mine|REGISTER_FROSTFIRE,ENTER_FROSTFIRE,READ_MAP,SEARCH_ORICHALCUM,OCCUPY_MINE,USE_SKILL,READ_SCORE,CLAIM_REWARD
AJ|Frostdragon Tyrant|DISCOVER_FROSTDRAGON,REGISTER,ENTER_BATTLEFIELD,READ_OBJECTIVE,CAPTURE_OBJECTIVE,RALLY,REINFORCE,READ_SCORE
AK|Tundra Trade Route / Truck|OPEN_TUNDRA_TRUCK,READ_TRUCK_ATTEMPTS,READ_TRUCK_RARITY,REFRESH_TRUCK,SELECT_TRUCK,SELECT_ESCORT_HERO,DISPATCH_TRUCK,CLAIM_TRUCK,PLUNDER_TRUCK,READ_DAILY_LIMIT
AL|Tundra Trading Station|OPEN_TRADING_STATION,READ_TRADEABLE_ITEM,VALUE_ITEM,TRADE_SURPLUS,READ_SHOP,BUY_PRIORITY_ITEM
AM|Nomadic Merchant|OPEN_NOMADIC_MERCHANT,READ_OFFERS,FREE_REFRESH,VALUE_OFFER,BUY_GOOD_OFFER
AN|Fishing Tournament|DISCOVER_FISHING,CLAIM_FREE_BAIT,CLAIM_FREE_CHART,START_FISHING,CONTROL_HOOK,AVOID_OBSTACLE,CATCH_TARGET,UPGRADE_LINE,UPGRADE_HOOK,UPGRADE_SINKER,CLAIM_FISHING_MISSION,FROSTY_PROSPECTOR,SUNKEN_TREASURE
AO|Mia's Fortune Hut|DISCOVER_MIA,READ_TOKENS,OPEN_BOARD,SELECT_TILE,CLAIM_REWARD,STOP_POLICY
AP|Frosty Fortune / Vault / Enigma|DISCOVER_ENIGMA_EVENT,COMPLETE_DAILY_TASK,CLAIM_CHEST,READ_EVENT_CURRENCY,EVENT_SHOP,EVENT_EXCHANGE
AQ|Tundra Albums|OPEN_ALBUM,READ_FRAGMENT,CLAIM_ALBUM_REWARD,SHARE_FRAGMENT,TRADE_FRAGMENT
AR|Mercenary Prestige|DISCOVER_MERCENARY,SELECT_DIFFICULTY,FIND_TARGET,ATTACK_TARGET,CONTINUE_SEQUENCE,CLAIM_REWARD
AS|Gina's Revenge / Hero's Mission|DISCOVER_CURRENT_VARIANT,FIND_EVENT_BEAST,ATTACK_EVENT_TARGET,USE_EVENT_ITEM,CLAIM_EVENT_REWARD
AT|Beast Whisperer|DISCOVER_BEAST_WHISPERER,READ_TASK,VERIFY_PROGRESS,CLAIM_REWARD
AU|Vision of Dawn / Symphony of Changes|DISCOVER_EVENT,READ_TASK,MAP_TO_EXISTING_SKILL,VERIFY_PROGRESS,CLAIM
AV|Snowbuster|ENTER_SNOWBUSTER,READ_MAP,MOVE,COLLECT_COAL,UPGRADE_FURNACE,CLAIM_REWARD
AW|Wander Theater|ENTER_WANDER_THEATER,READ_FLOOR,DRAW,VALUE_REWARD,CONTINUE_OR_STOP,CLAIM
AX|Journey of Light / Tundra Trek / Adventure|DISCOVER_JOURNEY,READ_STAGE,START_STAGE,AUTO_BATTLE,CLAIM_STAGE,CLAIM_MILESTONE
AY|Shops / 商店系统|OPEN_SHOP,READ_SHOP_TYPE,READ_ITEM,READ_PRICE,FREE_ITEM,VALUE_ITEM,BUY_ITEM,REFRESH_SHOP,READ_DAILY_LIMIT
AZ|背包 / 道具|OPEN_BAG,READ_ITEM,USE_RESOURCE_ITEM,USE_SPEEDUP,USE_STAMINA,OPEN_CHEST,USE_SELECTION_CHEST,RESOURCE_BOX_SELECT,ITEM_EXPIRY
BA|城市增益 / Buff|READ_CITY_BUFF,ACTIVATE_GATHER_BUFF,ACTIVATE_BUILD_BUFF,ACTIVATE_RESEARCH_BUFF,ACTIVATE_TRAIN_BUFF,ACTIVATE_SHIELD,READ_SHIELD_TIMER
BB|Teleport|READ_CURRENT_COORD,ADVANCED_TELEPORT,ALLIANCE_TELEPORT,TERRITORY_TELEPORT,RANDOM_TELEPORT,VERIFY_NEW_COORD
BC|玩家 / 城市战斗|SCOUT_CITY,READ_SCOUT_REPORT,ATTACK_CITY,ATTACK_GATHERER,DEFEND_CITY,GARRISON,REINFORCE,SHIELD,BURNING_STATE,DEFENSE_RECOVERY
BD|State Transfer|DISCOVER_TRANSFER,READ_ELIGIBILITY,READ_TARGET_STATE,READ_TRANSFER_COST,READ_TRANSFER_PHASE
BE|State Merge|DETECT_STATE_CHANGED,INVALIDATE_STATE_CACHE,REFRESH_SERVER_KNOWLEDGE,REFRESH_ALLIANCE,REFRESH_EVENTS
BF|新功能自动发现|FEATURE_UNLOCK_CANDIDATE
"""

# Categories the directive defines as a MECHANISM (an adapter over existing skills)
# rather than as a list of capabilities.  Recorded so the catalog is complete, and
# deliberately given no CAP entries: inventing IDs for them would put a number on
# something the operator did not enumerate.
MECHANISM_CATEGORIES = {
    "AH": "两日 / 周期成长活动 — 统一 EVENT_DISCOVER → READ_RULES → READ_PROGRESS → "
          "MAP_SCORE_ACTION_TO_EXISTING_SKILL → EXECUTE → VERIFY_POINTS → CLAIM；"
          "不每个活动造独立脚本（Armament Competition / Officer Project / "
          "Defeat Nearby Beasts / Brothers in Arms 等轮换活动）",
    "BF": "UNKNOWN → FEATURE_UNLOCK_CANDIDATE → Screenshot/Evidence → Local Knowledge Check → "
          "External Knowledge Check → Safe Exploration → Identify → Capability Candidate → "
          "Live Verify → Register（角色成长后自动认识新玩法）",
}

# CAP code -> the skill in v2_registry() that actually performs it.  Only mappings
# that are real are listed; an absent entry means "no existing skill does this",
# which is the finding, not an omission.
ALIASES: dict[str, str] = {
    # --- navigation / client (skills that really exist in v2_registry) ---------
    "HOME_TO_MAP": "OPEN_MAP",
    "MAP_TO_HOME": "BACK",
    "BACK": "BACK",
    "CLOSE_POPUP": "CLOSE_POPUP",
    "HANDLE_LOADING": "WAIT",
    "RECOVER_TO_SAFE_PAGE": "RECOVER_HOME",
    "DETECT_FREE_CLAIM": "OPEN_STAMINA_SOURCES",
    # --- free rewards / daily / mail ------------------------------------------
    "CLAIM_FREE_REWARD": "CLAIM_FREE_STAMINA",
    "CLAIM_ALL": "CLAIM_REWARD",
    "CLAIM_EVENT_MILESTONE": "CLAIM_REWARD",
    "CLAIM_DAILY_MISSION": "DAILY_CLAIM_REWARDS",
    "CLAIM_LOGIN_REWARD": "DAILY_CLAIM_REWARDS",
    "MAIL_READ": "OPEN_MAIL",
    "CLAIM_MAIL": "MAIL_CLAIM_REWARDS",
    "MAIL_COLLECT_ALL": "MAIL_CLAIM_REWARDS",
    "FREE_RECRUIT": "DAILY_HERO_RECRUIT",
    "HERO_RECRUIT": "DAILY_HERO_RECRUIT",
    # --- gathering / march ----------------------------------------------------
    "OPEN_WORLD_SEARCH": "SEARCH_RESOURCE",
    "SELECT_RESOURCE_MEAT": "SELECT_RESOURCE",
    "SELECT_RESOURCE_WOOD": "SELECT_RESOURCE",
    "SELECT_RESOURCE_COAL": "SELECT_RESOURCE",
    "SELECT_RESOURCE_IRON": "SELECT_RESOURCE",
    "SELECT_RESOURCE_LEVEL": "RELAX_RESOURCE_LEVEL",
    "SEARCH_RESOURCE": "SUBMIT_RESOURCE_SEARCH",
    "RESOURCE_NODE_AVAILABLE": "SUBMIT_RESOURCE_SEARCH",
    "START_GATHER": "START_GATHER",
    "DISPATCH_GATHER": "DISPATCH_MARCH",
    "VERIFY_GATHERING": "VERIFY_GATHERING",
    "RECALL_GATHER": "RECALL_MARCH",
    "READ_MARCH_CAPACITY": "CHECK_MARCH",
    "READ_MARCH_OCCUPANCY": "CHECK_MARCH",
    "OPEN_MARCH_PAGE": "CHECK_MARCH",
    "SELECT_MARCH": "SELECT_MARCH_TO_RECALL",
    "DISPATCH_MARCH": "DISPATCH_MARCH",
    "RECALL_MARCH": "RECALL_MARCH",
    "VERIFY_RETURNING": "RECALL_MARCH",
    # --- beasts / intel -------------------------------------------------------
    # 2026-09-17: SEARCH_BEAST used to point at SELECT_BEAST_TARGET, which only
    # *taps* a target that already sits in the viewport.  The live escalation
    # SPEND_STAMINA_ON_BEAST|VERIFIED_BEAST_TARGET_NOT_VISIBLE proved the search
    # itself was the missing half: the goal dead-ended whenever no verified
    # beast was on screen.  SCAN_MAP_FOR_BEAST is the real search hop now.
    "SEARCH_BEAST": "SCAN_MAP_FOR_BEAST",
    "ATTACK_BEAST": "BEAST_HUNT",
    "READ_STAMINA": "OPEN_STAMINA_SOURCES",
    "OPEN_LIGHTHOUSE": "OPEN_INTEL",
    "READ_INTEL_LIST": "READ_INTEL_LIST",
    "SELECT_INTEL": "SELECT_INTEL_PIN",
    "EXECUTE_INTEL": "EXECUTE_INTEL_RESCUE_SURVIVORS",
    "CLAIM_INTEL": "INTEL_CLAIM_REWARDS",
    # --- buildings / research / troops ---------------------------------------
    "OPEN_BUILDING": "BUILDING_UPGRADE",
    "START_BUILD": "BUILDING_UPGRADE",
    "UPGRADE_BUILDING": "BUILDING_UPGRADE",
    "FURNACE_UPGRADE": "BUILDING_UPGRADE",
    "OPEN_RESEARCH": "RESEARCH",
    "START_RESEARCH": "RESEARCH",
    "TRAIN_INFANTRY": "TRAIN_TROOPS",
    "TRAIN_LANCER": "TRAIN_TROOPS",
    "TRAIN_MARKSMAN": "TRAIN_TROOPS",
    "TRAIN_HIGHEST_AVAILABLE_TIER": "TRAIN_TROOPS",
    "REQUEST_ALLIANCE_HELP": "ALLIANCE_HELP",
    # --- alliance -------------------------------------------------------------
    "OPEN_ALLIANCE": "OPEN_ALLIANCE",
    "ALLIANCE_HELP": "ALLIANCE_HELP",
    "ALLIANCE_TECH_DONATE": "ALLIANCE_TECH_CONTRIBUTE",
    "ALLIANCE_GIFT": "ALLIANCE_GIFTS",
    "ALLIANCE_CHEST": "ALLIANCE_GIFTS",
    "ALLIANCE_FREE_ITEM": "ALLIANCE_ALLY_GIFT_CLAIM",
    "CLAIM_ALLIANCE_REWARD": "ALLIANCE_ALLY_GIFT_CLAIM",
    "JOIN_RALLY": "JOIN_RALLY",
    "START_RALLY": "START_RALLY",
    "REINFORCE_ALLY": "REINFORCE_TARGET",
    # --- exploration ----------------------------------------------------------
    "OPEN_EXPLORATION": "OPEN_EXPLORATION",
    "CLAIM_EXPLORATION_IDLE": "EXPLORATION_IDLE_CLAIM",
    "CLAIM_EXPLORATION_CHEST": "CONFIRM_EXPLORATION_IDLE_CLAIM",
}

# §14 risk tiers.  T0 observe/read/free-claim, T1 normal daily, T2 resource spend,
# T3 strategic spend / PvP / teleport, T4 never unattended.
RISK_T4 = {
    "GIFT_CODE", "SVS_TELEPORT", "TRANSFER_EXECUTE", "ADVANCED_TELEPORT", "RANDOM_TELEPORT",
}
RISK_T4_PREFIX_CODES = {"BUY_ITEM", "STRATEGY_SPIN", "REFRESH_TRUCK", "TRADE_SURPLUS"}
RISK_T3 = {
    "RECALL_MARCH", "RECALL_GATHER", "RECALL", "WITHDRAW_REINFORCEMENT", "MARCH_SPEEDUP",
    "USE_SPEEDUP", "USE_SELECTION_CHEST", "RESOURCE_BOX_SELECT", "ACTIVATE_SHIELD",
    "REINFORCE_ALLY", "REINFORCE_HQ", "REINFORCE_MEMBER", "REINFORCE", "SHIELD",
    "ATTACK_CITY", "ATTACK_GATHERER", "SCOUT_CITY", "GARRISON", "MOVE_TROOPS",
    "CAPTURE_BUILDING", "CAPTURE_OBJECTIVE", "DEFEND_OBJECTIVE", "OCCUPY_MINE",
    "BUILD_HQ", "BUILD_BANNER", "REMOVE_BANNER", "TERRITORY_TELEPORT",
    "ALLIANCE_TELEPORT", "VIP_ACTIVATE", "START_RALLY", "JOIN_RALLY", "RALLY",
}
RISK_T2 = {
    "USE_RESOURCE_ITEM", "USE_STAMINA", "OPEN_CHEST", "EXCHANGE_FIRE_CRYSTAL_SHARDS",
    "HERO_SHARD_EXCHANGE", "CLAIM_ALL", "BUY_PRIORITY_ITEM", "BUY_GOOD_OFFER",
    "ALLIANCE_TECH_DONATE", "START_BUILD", "UPGRADE_BUILDING", "START_RESEARCH",
    "FURNACE_UPGRADE", "RESOURCE_BUILDING_UPGRADE", "TROOP_CAMP_UPGRADE",
    "EMBASSY_UPGRADE", "INFIRMARY_UPGRADE", "COMMAND_CENTER_UPGRADE",
    "RESEARCH_CENTER_UPGRADE", "BARRICADE_UPGRADE", "OTHER_BUILDING_UPGRADE",
    "START_TRAINING", "TRAIN_INFANTRY", "TRAIN_LANCER", "TRAIN_MARKSMAN",
    "TRAIN_HIGHEST_AVAILABLE_TIER", "PROMOTE_INFANTRY", "PROMOTE_LANCER",
    "PROMOTE_MARKSMAN", "HEAL", "ENLIST_RESERVES", "SEARCH_BEAST", "ATTACK_BEAST",
    "START_POLAR_TERROR_RALLY", "JOIN_POLAR_TERROR_RALLY", "FREE_SPIN",
}
RISK_T0_MARKERS = ("DETECT_", "READ_", "OPEN_", "SEARCH_", "SEARCHLIGHT", "DISCOVER_", "CLASSIFY_", "FIND_", "STOP_")
RISK_T0_CODES = {
    "LAUNCH_GAME", "BACK", "CLOSE_POPUP", "HANDLE_LOADING", "HANDLE_NETWORK_ERROR",
    "HANDLE_RECONNECT", "HANDLE_UNKNOWN_PAGE", "RECOVER_TO_SAFE_PAGE", "MOVE",
    "CONTINUE_OR_STOP", "STOP_POLICY", "STOP_AT_BLOCKED_STAGE", "STOP_ON_POWER_WALL",
}
FREE_CLAIM_CODES = {
    "CLAIM_FREE_REWARD", "CLAIM_MAIL", "MAIL_COLLECT_ALL", "CLAIM_VIP_DAILY",
    "VIP_FREE_CHEST", "CLAIM_LOGIN_REWARD", "CLAIM_ONLINE_REWARD", "CLAIM_CITY_BUBBLE",
    "CLAIM_BUILDING_OUTPUT", "CLAIM_IDLE_REWARD", "CLAIM_EXPLORATION_CHEST",
    "CLAIM_ALLIANCE_REWARD", "CLAIM_EVENT_REWARD", "FREE_SHOP_ITEM", "FREE_ITEM",
    "CLAIM_DAILY_MISSION", "CLAIM_GROWTH_MISSION", "CLAIM_EVENT_MILESTONE",
    "ALLIANCE_FREE_ITEM", "FREE_RECRUIT", "CLAIM_FREE_BAIT", "CLAIM_FREE_CHART",
    "CLAIM_FREE_SPIN", "FREE_REFRESH", "USE_FREE_ARENA_ATTEMPTS",
}

# The operator's §5 development order, reduced to the capability codes it names.
# The catalog is ordered by CATEGORY (its tree); this is the order to WORK in, and
# the directive is explicit that it is not alphabetical.
PHASE1_CODES = (
    "START_GATHER", "DISPATCH_GATHER", "VERIFY_GATHERING", "RECALL_GATHER", "RECALL_MARCH",
    "CLAIM_FREE_REWARD", "CLAIM_ALL", "CLAIM_EVENT_MILESTONE", "CLAIM_MAIL", "MAIL_READ",
    "MAIL_COLLECT_ALL", "CLAIM_VIP_DAILY", "VIP_FREE_CHEST", "CLAIM_DAILY_MISSION",
    "CLAIM_GROWTH_MISSION", "FREE_SHOP_ITEM", "FREE_ITEM",
    "TRAIN_INFANTRY", "TRAIN_LANCER", "TRAIN_MARKSMAN", "TRAIN_HIGHEST_AVAILABLE_TIER",
    "PROMOTE_INFANTRY", "PROMOTE_LANCER", "PROMOTE_MARKSMAN", "HEAL",
    "OPEN_RESEARCH", "START_RESEARCH", "START_BUILD", "UPGRADE_BUILDING",
    "ALLIANCE_HELP", "ALLIANCE_GIFT", "ALLIANCE_CHEST", "ALLIANCE_TECH_DONATE",
    "SELECT_INTEL", "EXECUTE_INTEL", "CLAIM_INTEL", "SEARCH_BEAST", "ATTACK_BEAST",
)
PHASE2_CODES = (
    "OPEN_ARENA", "START_ARENA", "USE_FREE_ARENA_ATTEMPTS", "OPEN_EXPLORATION",
    "START_EXPLORATION", "CLAIM_EXPLORATION_IDLE", "OPEN_LABYRINTH", "BATTLE_LABYRINTH",
    "HERO_RECRUIT", "FREE_RECRUIT", "PET_LEVEL_UP", "PET_TREASURE_HUNT",
    "OPEN_DAYBREAK_ISLAND", "COLLECT_LIFE_ESSENCE", "AUTO_JOIN_RALLY",
    "ALLIANCE_TRIUMPH", "OPEN_NOMADIC_MERCHANT", "FREE_REFRESH",
)
NEEDS_WORK = {"MISSING", "CANDIDATE", "LIVE_TRIED", "BLOCKED", "DEGRADED"}


def _risk(code: str) -> str:
    if code in RISK_T4 or code in RISK_T4_PREFIX_CODES:
        return "T4"
    if code in RISK_T3:
        return "T3"
    if code in RISK_T2:
        return "T2"
    if code in FREE_CLAIM_CODES or code in RISK_T0_CODES or code.startswith(RISK_T0_MARKERS):
        return "T0"
    return "T1"


def main() -> int:
    from winter_agent_v2.runtime import LiveRuntime
    from winter_agent_v2.skills import v2_registry

    registry = v2_registry()
    judges = set(LiveRuntime.VERIFIED_ATOMIC)

    episodes: dict[str, dict[str, int]] = {}
    last_success: dict[str, str] = {}
    excluded_rows = 0
    excluded_skills: dict[str, int] = {}
    for line in (ROOT / "learning/episodes.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        skill = str(row.get("skill") or "")
        # A row may only support a LIVE_VERIFIED claim when it is a traced production
        # episode.  The live-verification gate is explicit: rows without
        # ``recorded_at`` / ``episode_id`` / screenshots must never be cited for it.
        # Measured 2026-09-16: ALLIANCE_TECH_CONTRIBUTE carries four SUCCESS rows with
        # no ``recorded_at`` at all, and counting them lifted this catalog's
        # LIVE_VERIFIED by a number the project cannot defend.
        if not row.get("recorded_at"):
            excluded_rows += 1
            excluded_skills[skill] = excluded_skills.get(skill, 0) + 1
            continue
        bucket = episodes.setdefault(skill, {})
        result = str(row.get("result") or "?").upper()
        bucket[result] = bucket.get(result, 0) + 1
        if result == "SUCCESS":
            stamp = str(row.get("recorded_at") or "")
            if stamp > last_success.get(skill, ""):
                last_success[skill] = stamp

    entries: list[dict] = []
    unknown_alias: list[str] = []
    for block in SPEC.strip().splitlines():
        category_code, category_name, tokens = block.split("|", 2)
        for index, code in enumerate(tokens.split(","), start=1):
            code = code.strip()
            if not code:
                continue
            skill_id = ALIASES.get(code)
            existing = skill_id if skill_id and registry.get(skill_id) else None
            if skill_id and not existing:
                unknown_alias.append("%s -> %s" % (code, skill_id))
            counts = episodes.get(skill_id or "", {})
            attempts = sum(counts.values())
            successes = counts.get("SUCCESS", 0)
            failures = attempts - successes
            if existing and skill_id in judges and successes:
                lifecycle = "LIVE_VERIFIED"
            elif existing and skill_id in judges:
                lifecycle = "LIVE_TRIED" if attempts else "CANDIDATE"
            elif existing:
                lifecycle = "CANDIDATE"
            else:
                lifecycle = "MISSING"
            entries.append({
                "capability_id": "CAP-%s%02d" % (category_code, index),
                "code": code,
                "name_cn": category_name,
                "category": category_code,
                "description": "%s / %s" % (category_name, code),
                "unlock_status": "UNKNOWN",
                "current_role_available": "UNKNOWN",
                "implementation_status": "EXISTING" if existing else "MISSING",
                "lifecycle": lifecycle,
                "risk": _risk(code),
                "requires_march": code in {
                    "START_GATHER", "DISPATCH_GATHER", "DISPATCH_MARCH", "RECALL_MARCH",
                    "RECALL_GATHER", "ATTACK_BEAST", "JOIN_RALLY", "START_RALLY",
                    "REINFORCE_ALLY", "REINFORCE_MEMBER", "REINFORCE", "SCOUT_CITY",
                    "ATTACK_CITY", "ATTACK_GATHERER", "MOVE_TROOPS", "REPEAT_BEAR_ATTACK",
                    "PREPARE_BEAR", "FREE_MARCH_FOR_BEAR", "MARCH_OBJECTIVE",
                },
                "requires_stamina": code in {
                    "SEARCH_BEAST", "ATTACK_BEAST", "ATTACK_EVENT_TARGET",
                    "FIND_EVENT_BEAST", "START_POLAR_TERROR_RALLY",
                    "JOIN_POLAR_TERROR_RALLY", "FREE_SPIN", "START_EXPLORATION",
                    "START_ARENA", "BATTLE_LABYRINTH",
                },
                "resource_cost": "UNKNOWN",
                "real_money_cost": "FORBIDDEN" if code in RISK_T4_PREFIX_CODES else "NONE_ALLOWED",
                "preferred_backend": "MAA",
                "existing_skill": existing,
                "external_reference": "REFERENCE_ONLY",
                "live_attempts": attempts,
                "live_success": successes,
                "live_failure": failures,
                "success_rate": (round(successes / attempts, 4) if attempts else None),
                "last_live_verified": last_success.get(skill_id or "") or None,
                "blocked_reason": None,
            })

    # The two blockers this project has actually measured, recorded on the entry
    # they belong to rather than in prose.
    for entry in entries:
        if entry["code"] == "RECALL_MARCH":
            entry["blocked_reason"] = (
                "trigger needs idle_marches == 0 with a GATHERING march out; this role "
                "cannot put a second march on the map -- the client refuses with "
                "'您的城镇中现在暂无可出征士兵，请前往训练' -- so the slot never fills. "
                "Manufacturing the state is prohibited. Live 2026-09-16T11:22.")
            entry["current_role_available"] = "OBSERVED_AVAILABLE"
        if entry["code"] == "DETECT_CURRENT_ROLE":
            entry["blocked_reason"] = (
                "the role IS observable (领主档案 panel behind one tap on the avatar) and "
                "the reader exists, but no skill calls it yet.")
        if entry["code"] == "SEARCH_BEAST":
            # The counts are deliberately not restated here: the entry carries
            # live_attempts / live_success / last_live_verified next to this string
            # and they move with every run, so a number written into prose goes
            # stale and contradicts its own row.  Only the settled facts are prose.
            entry["blocked_reason"] = (
                "the scan hop is live (see live_attempts / last_live_verified) but only "
                "finds the level-9 Musk Ox the target template was cropped from; the "
                "current role's map holds a level-24/25 moose instead, whose victory "
                "assessment is not safely attackable, so no stamina spend has been "
                "verified on this role.  The hop itself is not perfectly reliable and "
                "the measurement says so: as of 2026-09-17T16:05, 2 of 204 recorded pans "
                "were not consumed as pans -- the client left the world map (one to the "
                "city, one to an event page) -- both times the fail-closed verifier "
                "refused to call the step proven, which is the correct answer, and the "
                "mechanism is not reproduced.  Evidence, including both negative frames: "
                "dataset/truth_audit/beast_map_scan_20260917/key/.")
            entry["current_role_available"] = "OBSERVED_AVAILABLE"

    summary = {
        "total": len(entries),
        "by_lifecycle": {},
        "by_implementation": {},
        "by_risk": {},
        "existing_skill_ids": sorted({e["existing_skill"] for e in entries if e["existing_skill"]}),
    }
    for entry in entries:
        summary["by_lifecycle"][entry["lifecycle"]] = summary["by_lifecycle"].get(entry["lifecycle"], 0) + 1
        summary["by_implementation"][entry["implementation_status"]] = summary["by_implementation"].get(entry["implementation_status"], 0) + 1
        summary["by_risk"][entry["risk"]] = summary["by_risk"].get(entry["risk"], 0) + 1

    payload = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "operator CAPABILITY-FIRST directive 2026-09-16 §4 (capability tree), "
                  "joined with winter_agent_v2.skills.v2_registry(), "
                  "LiveRuntime.VERIFIED_ATOMIC and learning/episodes.jsonl",
        "evidence_policy": ("only episodes carrying ``recorded_at`` count as live evidence; "
                            "rows without it cannot support LIVE_VERIFIED (live-verification gate). "
                            "excluded rows: %d across %d skills" % (excluded_rows, len(excluded_skills))),
        "definition": ("Coverage table for the game's capabilities. NOT a skill registry: "
                       "v2_registry() remains the only table of executable skills. "
                       "lifecycle is derived from real evidence; nothing here invents a status."),
        "summary": summary,
        "mechanism_categories": MECHANISM_CATEGORIES,
        "capabilities": entries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT, "entries:", len(entries))
    print("lifecycle:", json.dumps(summary["by_lifecycle"], ensure_ascii=False))
    print("implementation:", json.dumps(summary["by_implementation"], ensure_ascii=False))
    print("risk:", json.dumps(summary["by_risk"], ensure_ascii=False))
    print("distinct existing skills mapped:", len(summary["existing_skill_ids"]))
    print("episodes excluded for having no recorded_at:", excluded_rows,
          "across", len(excluded_skills), "skills")
    if excluded_skills:
        worst = sorted(excluded_skills.items(), key=lambda kv: -kv[1])[:8]
        print("  worst offenders:", ", ".join("%s=%d" % (k, v) for k, v in worst))
    if unknown_alias:
        print("ALIAS TARGETS THAT DO NOT EXIST (must be fixed):", unknown_alias)

    if "--rank" in sys.argv:
        by_code: dict[str, list[dict]] = {}
        for entry in entries:
            by_code.setdefault(entry["code"], []).append(entry)
        print()
        print("=== work order (operator's §5, not alphabetical) ===")
        for label, codes in (("PHASE 1", PHASE1_CODES), ("PHASE 2", PHASE2_CODES)):
            print()
            print("-- %s --" % label)
            rows = []
            for code in codes:
                for entry in by_code.get(code, []):
                    rows.append(entry)
            rows.sort(key=lambda e: (e["lifecycle"] not in NEEDS_WORK, e["risk"], e["capability_id"]))
            for entry in rows:
                flag = "DO  " if entry["lifecycle"] in NEEDS_WORK else "ok  "
                print("  %s%-12s %-30s lifecycle=%-13s risk=%-3s skill=%-30s live=%s/%s" % (
                    flag, entry["capability_id"], entry["code"], entry["lifecycle"], entry["risk"],
                    entry["existing_skill"] or "-", entry["live_success"], entry["live_attempts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
