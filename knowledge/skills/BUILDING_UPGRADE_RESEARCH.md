# BUILDING_UPGRADE Research

Status: `VERIFIED / LIVE_CLIENT`  
Retrieved and live-verified: 2026-09-03  
Mode: just-in-time research for the first P1 capability.

## Evidence-fused flow

1. Enter HOME and identify an upgrade target from current state/player goals; external priority advice remains strategy-only.
2. Select the building and open its upgrade dialog.
3. Read building identity, current/target level, prerequisites, costs, queue availability and effective duration.
4. Reject real-money actions and keep gem instant-finish separate from the normal upgrade action.
5. Start the normal upgrade only when prerequisites/resources are verified.
6. Verify the target building has construction scaffolding and a non-empty queue timer.

## External priors

- The Furnace controls other-building level limits and unlocks; upgrade tables vary by level and speed bonuses alter displayed duration.
- Player recommendations about always prioritizing the Furnace are `STRATEGY_CANDIDATE`, not hard-coded facts.
- `AminulIslamSifat/wos` does not advertise a general building-upgrade use case, so BUILD was treated as an external capability gap and learned from the live client.

## Current CN-client facts

- The active quest selected `仓库` level 26 for level 27.
- Required `大熔炉 等级 27` was satisfied.
- Costs: 29.12m Meat, 29.12m Wood, 5.915m Coal, 1.456m Iron.
- Normal effective duration: 2d04:50:26; original duration shown: 3d19:09:00.
- The left orange control was a 42,273-gem instant finish and was not used.
- The blue `升级` action started the queue; scaffolding, alliance help and a 2d04:50:10 timer verified success.

## Sources

- https://www.whiteoutsurvival.wiki/buildings/furnace/
- https://play.google.com/store/apps/editorial?hl=zh&id=mc_games_editorialevergreen_postinstall_starter_tips_now_whiteout_survival_fcp
- https://www.taptap.cn/moment/540206174411163246
- https://github.com/AminulIslamSifat/wos
- Current CN client screenshots in `dataset/raw/live_build_*`.
