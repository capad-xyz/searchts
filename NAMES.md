# Names

When in doubt, this file wins over chat. Roles, not vendors.

| Call it | Is | Is not |
|---|---|---|
| **Orchestrator** | Whoever is running the loop this turn (dispatch, leftover finish, merge) | A model vendor. Grok / Claude / Codex can *be* it |
| **Remote orchestrator** | This chat / Grok Build opening PRs from the cloud | Laptop OpenCode. Cannot start ocx. A *sub-agent in this chat* is still remote. |
| **Local orchestrator** | Grok (or whoever) on the laptop, with OpenCode (ocx) | Hare. After workers, it **spawns** Hare |
| **Worker / cheap-scout** | Free-catalog agent that *writes* the diff | The merge bar |
| **Hare** (🐇‍❄) | Cheap-scout that *reviews* (`searchts-r1-review`) | The orchestrator. Writer model ≠ Hare model |
| **searchts-r1-needed** | Nag: Hare has not run on this SHA | A review |
| **searchts-r1-review** | The review token (hourly matcher + merge bar) | A skill |

**PLAN ids** live in [`PLAN.md`](PLAN.md): `P*` work, `F*` later, `U*` unverified, `N*` never, `R*` review (Hare).

| Id | One line |
|---|---|
| **R1** | Writer ≠ Hare. Two GitHub surfaces. Spec in [`AGENTS.md`](AGENTS.md) |
| **R1b** | `hare[bot]` badge. After R1c is boring |
| **R1c** | Action doorbell on push. Zen/Nous free. 429 → needed. *Boring first* |
| **F15** | Hare as a product for other repos. Not R1c. Own thread |

**Local extra step:** after workers, local orchestrator still spawns Hare by hand (in-session). That is the layer. **R1c** only removes it for **remote** pushes (laptop closed). Do not make local Grok pretend it is CI.
