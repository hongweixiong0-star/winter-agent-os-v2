# BEAST_HUNT — Just-in-Time Skill Research

Status: `VERIFIED` (1 complete live normal-Beast/Intel cycle; not `STABLE`).

## External prior

- Google Play's Whiteout Survival beast guide confirms that normal Beast attacks use Chief Stamina and require sufficient stamina before deployment.
- Whiteout Survival community references distinguish solo normal Beasts from Polar Terrors/Giant Beasts and Bear Hunt. V2 therefore keeps these as separate skills.
- Public WOS automation projects advertise Beast/Intel hunts. V2 only borrows the flow decomposition: identify exact target → check stamina/march → dispatch → observe return → verify battle/mission result.

## Live verified flow

`INTEL level-10 beast mission → View Target → level-22 大角鹿 → displayed stamina 10 → victory assured → dispatch → march 1/6→2/6 → RETURNING 14s → natural return 1/6 → Intel green claimable badge → reward feedback → marker removed`.

The live stamina value changed from 92 to 85. The actual cost was therefore 7, not the displayed 10; the likely explanation is a live hero/account stamina reduction. V2 records the discrepancy as observed behavior and never assumes displayed base cost equals final cost.

## Verification gate

`verify_beast_hunt` requires target identity/availability, explicit victory-assured march, queue increase and RETURNING, natural queue restoration, bounded positive stamina delta, and the matching Intel mission becoming CLAIMABLE. A click or outbound march alone is insufficient.

## 2026-09-06 stamina-priority calibration

The live client had all six marches gathering while the player reported full Chief Stamina. One gathering march was explicitly recalled and observed through `GATHERING -> RETURNING -> IDLE`. A level-29 Snow Leopard was rejected because the march page showed red low win probability. Two level-9 Musk Ox runs and one level-6 Arctic Wolf run showed green victory assurance, displayed 10 stamina each, dispatched `5/6 -> 6/6`, and naturally returned `6/6 -> 5/6`.

The exact numeric stamina balance was not visible, so this evidence records 30 displayed/committed cost but does not invent a numeric before/after delta. Gather now preserves one march through the existing RuleBrain while stamina priority is active.
