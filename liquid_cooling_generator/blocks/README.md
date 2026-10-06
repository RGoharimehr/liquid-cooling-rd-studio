# Building blocks

Size and check one section at a time, then connect sections. Started on branch
`refactor/building-blocks`; see the walkthrough in
`notebooks/01_rack_branch_and_row.ipynb`.

## What each block reports

Heat, mass flow, volume flow, supply and return temperature, temperature rise,
pressure drop on the critical path, required head, pipe schedule, valve
schedule, accessories, declared assumptions and checks.

`BlockResult.connection()` is what a block asks of whatever feeds it: flow,
temperatures, required pressure difference and head, and whether that number
is complete. A larger block only needs this, not the internals.

## Sizing chain (`sizing.py`)

    heat + max rise -> m = Q/(cp*dT) -> V = m/rho
    -> minimum bore at the CATEGORY velocity cap -> next catalogue size
    -> velocity, Re, Darcy factor -> pressure loss -> head = dp/(rho*g)

Reuses `hydraulics.select_size`, `standards.CATEGORIES` and
`preliminary_sizing.friction_factor` / `valve_capacity` / `DEFAULT_K`.

## Blocks

| Block | File | Contents |
|---|---|---|
| Rack branch | `rack_branch.py` | isolation valves, strainer, pipes and elbows, quick disconnects, rack, balancing valve, optional control valve |
| Rack row | `row.py` | supply and return headers (direct or reverse return; constant or stepped), header tees and isolation valves, N branches, balancing allocation |

## Rules kept from SIZING_BASIS.md

* Flows are prescribed, not solved. Balancing valves are allocated so every
  parallel path needs the same pressure at its design flow.
* A pressure drop that has not been supplied (the rack's internal loop) is
  UNKNOWN, never zero. The block reports `dp_complete = False` and lists it.
* Generic K values, branch lengths, feed length and the balancing-valve
  minimum allocation are declared assumptions in every result.
* Each loss is counted once: a valve is a generic K or an allocated drop.

## Not yet

CDU / distribution block that feeds several rows; physical fit of branch and
header sizes at the rack pitch; Flownex comparison of one row; connection to
the graph and IFC emitters.
