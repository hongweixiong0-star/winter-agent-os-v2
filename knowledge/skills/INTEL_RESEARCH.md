# INTEL — Just-in-Time Skill Research

Status: `VERIFIED` for the Beast mission variant across six live completions. Hero Journey and Master Bounty are type-identified and safely `BLOCKED`; rescue remains `CANDIDATE`. Not `STABLE`.

## External prior

- Whiteout Survival Wiki identifies the Lighthouse as the Intel building and lists survivor rescue, beast hunting, and hero investigation mission types. Completing missions advances the Searchlight and more/better missions become available after upgrades.
- Whiteout Survival Data independently lists Beast Hunting, Advanced Bounty, A Hero's Journey, and Rescue Survivors. This supports separate mission classes rather than one generic Intel click flow.
- Google Play's Whiteout Survival editorial describes hero strengthening as preparation for Exploration and Intel work. It is a strategy prior only; current-client battle outcome remains authoritative.
- The official July 2026 update notes countdown reminders for expiring Intel in both the Lighthouse and World Map. This confirms that `EXPIRED`/expiry-soon must be modeled distinctly.
- Public WOS projects advertise Intel automation across beast, survivor, and exploration variants. V2 converts that only into separate candidate flows; it does not merge every Intel marker into one generic click task.

## Live-client facts

- The Lighthouse is the searchlight building with the yellow-beam icon in the current CN city.
- The live page title is `情报`. Captures show Searchlight level 20, dynamic stamina/countdown values, and multiple mission markers.
- Two markers had green completed/claimable badges and the bottom displayed `一键领取`.
- After tapping the verified claim control, `获得奖励` displayed eight item groups. After dismissal, both green badges and the claim button were absent.
- Blue, purple, and orange paw pins all opened the same `击败野兽 等级10` family. Six missions completed, naturally returned, and were claimed through verifier-gated Production chains.
- Purple crossed axes opened `英雄之旅 等级10`, with a displayed 10 stamina cost. One real dispatch ended with the live map label `失败`; the mission is blocked pending formation research.
- The orange rabbit opened `大师悬赏：20号`. Its live target recommended 189,295,920 power while observed chief power was 56,089,968, so V2 correctly did not dispatch.

## State and verification

The required state enum is `AVAILABLE`, `IN_PROGRESS`, `COMPLETED`, `CLAIMABLE`, `NOT_AVAILABLE`, `EXPIRED`, `UNKNOWN`, `BLOCKED`. `verify_intel_claim` requires all three live phases: claimable before, reward feedback, and zero claimable afterward.

The Beast variant is verified by six complete level-22 Great Horned Deer mission/claim cycles. Specific title semantics are evaluated before the shared `前往查看` control, preventing Hero Journey or Master Bounty from entering the ordinary Beast chain. Rescue still needs its own type-specific navigation and verifier evidence.
