# Names

When in doubt, this file wins over chat. Roles, not vendors.

| Call it | Is | Is not |
|---|---|---|
| **Orchestrator** | Whoever is running the loop this turn (dispatch, leftover finish, merge) | A model vendor. Grok / Claude / Codex can *be* it |
| **Remote orchestrator** | This chat / Grok Build opening PRs from the cloud | Laptop Grok. Cannot start **ocx**. A *sub-agent in this chat* is still remote |
| **Local orchestrator** | Grok (or whoever) on the laptop | Hare. After workers, it **spawns** Hare via ocx |
| **ocx** | Local router: Codex, Nous, OpenCode, OpenRouter models into Codex app/CLI, Grok CLI, OMP (oh-my-pi). How cheap-scouts get a free model | OpenCode the product. Not this chat |
| **Worker / cheap-scout** | Free model via ocx that *writes* the diff (local Grok asks for the spawn) | The merge bar |
| **Hare** (🐇‍❄) | Cheap-scout that *reviews* (`searchts-r1-review`) | The orchestrator. Writer model ≠ Hare model |
| **searchts-r1-needed** | Nag: Hare has not run on this SHA | A review |
| **searchts-r1-review** | The review token (hourly matcher + merge bar) | A skill |

**PLAN ids** live in [`PLAN.md`](PLAN.md): `P*` work, `F*` later, `U*` unverified, `N*` never, `R*` review (Hare).

| Id | One line |
|---|---|
| **R1** | Writer ≠ Hare. Two GitHub surfaces. Spec in [`AGENTS.md`](AGENTS.md) |
| **R1b** | `hare[bot]` badge. After R1c is boring |
| **R1c** | Action doorbell on push. Zen/Nous free. 429 → needed. *Boring first* |
| **R1d** | Same run: new summary comment + resolve threads whose finding is gone. #141 hole |
| **F15** | Hare as a product for other repos. Own glossary. Not ocx/cheap-scout |

**Local extra step:** after workers, local orchestrator still spawns Hare by hand (in-session). That is the layer. **R1c** only removes it for **remote** pushes (laptop closed). Do not make local Grok pretend it is CI.
