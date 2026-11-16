# Preman assignment

An evaluator for the PreMan agent evaluation exercise, together with the
unchanged starter kit it runs against.

## Layout

| Folder | Contents |
|---|---|
| `preman-agent-evaluation/` | The starter kit exactly as supplied: target server, scenarios, audio fixtures, and its own tests. Nothing in it has been modified. |
| `preman-evaluator/` | The evaluator: source (`preman_eval/`), tests, configuration, added scenarios, saved runs and replays, and evidence notes. |

The evaluator finds the starter kit by the relative path
`../preman-agent-evaluation`, so the two folders must stay side by side.

## Requirements

Python 3.10 or later. Standard library only; there is nothing to install.

## Usage

See [preman-evaluator/README.md](preman-evaluator/README.md) for the commands
to validate, run, compare, replay, and test, and for the design, results,
and limitations.
