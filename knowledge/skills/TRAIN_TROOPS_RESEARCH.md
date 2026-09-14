# TRAIN_TROOPS — Just-in-Time Skill Research

Status: `VERIFIED` for one live Infantry T10 batch; not stable.

## Whiteout Survival prior

- The three camp types are Infantry/盾兵营, Lancer/矛兵营, and Marksman/射手营.
- Whiteout Survival Wiki states that camps train and upgrade their troop type, camp/research bonuses affect capacity and duration, and promotion becomes available after higher tiers are unlocked.
- TapTap's game FAQ reports promotion after camp level 13 and describes promotion cost/time as the difference between the source and target tiers. This remains community guidance until a live promotion dialog is observed.
- Public WOS projects `AminulIslamSifat/wos` and Frostguard advertise automatic training/promotion for all three types. V2 retains the capability decomposition only: identify camp → inspect queue → select train/promote → verify timer and expected troop type.

## Live-client evidence

- Verified navigation: top power → `实力详情` → `部队实力` → `提升` focuses 30级盾兵营.
- The training page provides bottom tabs for all three camps and tier choices VI–X.
- All three live queues were inspected and are independently busy:
  - Infantry: 806 `王牌盾兵` (T10), 1:38:49 remaining.
  - Lancer: 806 `王牌矛兵` (T10), 1:37:40 remaining.
  - Marksman: 806 `王牌射手` (T10), 1:35:19 remaining.
- Gem instant-finish and acceleration controls were visible and were not used.
- On the next live pass, the previous Infantry batch completed and collection increased power by `+53,196`.
- The freed Infantry queue started 806 T10 `王牌盾兵` with displayed duration `10:03:12`.
- Exact displayed costs were Meat 2,247,000; Wood 1,685,000; Coal 393,000; Iron 82,212. No gems or speedups were used.

## Result and verifier

`verify_training_started` requires an AVAILABLE queue before the action and the expected troop type, IN_PROGRESS state, and timer afterwards. The Infantry variant passed live 1/1. Lancer and Marksman start variants remain unverified; the Skill is not stable.
