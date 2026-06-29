# SOL Auto-Remediation Lane (DEFAULT-OFF)

Surge autonomously resolves a **tiny, hand-curated** set of light, deterministic,
reversible, idempotent issues, and **escalates everything else** to a human.
"It's not broke until I can't fix it" — but the bar to enter the curated set is
deliberately high. This lane is **fail-closed** and **off by default**.

## Flag
- `SOL_AUTO_REMEDIATION` (env) → `Settings.auto_remediation`, **default `false`**.
- OFF ⇒ Surge may only **recommend** a remediation; SOL keeps the action
  human-gated exactly as today. There is **no autonomy** until an operator
  explicitly sets the flag.
- This is a **separate** flag from `auto_readonly` — it gates a curated
  allow-list of pre-vetted SAFE-WRITE remediations, not read-only host ops.

## How it works
`sol.policy.remediation` holds a curated registry. On `/dispatch`, when a request
would otherwise need a human **and** the flag is on, `classify_remediation(args)`
checks whether the request matches a registered playbook **exactly**. Only on an
exact match is `needs_human` flipped to auto-approved, with audit
`decision_path="auto-remediation"`, `reason="remediation:<name>"`.

The classifier is an **allow-list** and fails closed on any ambiguity. Anything
not matched — or any cross-rule denial — stays human-gated.

## Curated playbooks
### `disk-pressure-qdrant-retention`
- **Trigger** (evaluated by the orchestrator/broker *before* dispatch, not by
  SOL): a **backup** mount ≥ 85% full **and** family `qdrant-snapshots` has
  more than `KEEP` dated files under `/srv/backups/surge`.
- **Action**: the vetted `surge-qdrant-snapshot-retention.sh` (anchored ROOT,
  strict dated-file regex, per-delete path-guard, keep newest `KEEP`, dry-run
  unless `--apply`).
- **Allow-list shape** (what the classifier accepts): the exact script path,
  optional leading `KEEP=`/`FAMILY=qdrant-snapshots`/`ROOT=/srv/backups/...`/
  `LOG=` assignments, optional `--apply`, **nothing else**. Rejects: `KEEP<2`,
  `FAMILY=all`/any other family, `ROOT` outside `/srv/backups/`, any extra
  positional arg, and any shell metacharacter.
- **Orchestrator discipline**: always **dry-run → parse `est_freed` → verify it
  would drop usage < 85 → `--apply` → re-verify usage dropped and newest `KEEP`
  still present**. Never blind-apply.

## Escalate (never self-act) when
- The flag is off.
- Pressure is on a **data or root** mount (only backup mounts qualify).
- Dry-run shows `est_freed == 0` (problem is elsewhere).
- Post-verify shows usage still ≥ 85% (deeper issue).
- Any non-curated request, or any cross-rule denial.

## Audit & report
Every dispatch — remediation or not — writes a `Dispatch` audit row. Auto-applied
remediations are tagged `decision_path="auto-remediation"`,
`reason="remediation:<playbook>"`, so an operator query over the audit table
shows exactly "Surge fixed X". Escalations appear as ordinary `queued`/
`human-approval` rows (Surge proposed; a human must approve).

## Rollback / disable
- **Disable instantly**: unset `SOL_AUTO_REMEDIATION` (or set `false`) and reload
  SOL. The lane goes fully dormant — every remediation reverts to human-gated.
- The code path is additive; reverting this feature is removing the
  `remediation_name` block in `api/dispatch.py`, the `auto_remediation` setting,
  and `policy/remediation.py`. No schema change, no migration.

## Risks
- **R1 (data loss)**: purged snapshots are gone. Mitigated by `KEEP≥2`, backup
  mounts only, and the bkup-002/003 secondary mirrors with their own retention.
  Deleting a backup is one-way → this stays default-OFF + single-purpose.
- **R3 (gate erosion)**: any auto-mutation lane is a precedent. Mitigated by a
  separate flag, one script, one family, escalate-by-default, exact allow-list.

**Recommended rollout**: enable in **report-only** spirit first (operator runs the
matched action by hand while watching the proposals), review the audit log for a
week, then flip `SOL_AUTO_REMEDIATION=true` to grant `--apply` autonomy.
