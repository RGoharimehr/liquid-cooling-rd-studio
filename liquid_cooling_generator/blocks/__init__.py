"""Building blocks: size and check one section at a time, then connect sections.

Each block (a rack branch, a rack row) is sized on its own from a heat load and
a maximum temperature rise, and reports the same small set of results:

    heat, mass flow, volume flow, supply/return temperature, temperature rise,
    pressure drop on its critical path, required head, parts list.

The pressure drop a block needs between its supply and return connections is
its interface to whatever feeds it (see `BlockResult.connection`). A larger
block only needs that requirement, not the internals of the smaller block.

Scope and honesty rules (same as SIZING_BASIS.md):
  * Flows are PRESCRIBED from heat and temperature rise. Nothing here solves a
    flow network. Balancing valves are allocated so every parallel path needs
    the same pressure difference at its design flow.
  * An equipment pressure drop that has not been supplied is UNKNOWN, never
    zero. A block with an unknown part reports `dp_complete = False`.
  * Generic fitting K values, branch lengths and valve allocations are declared
    assumptions and are labelled as such in every result.

This package reuses the engine's pipe catalogues (`hydraulics`), pipe
categories and velocity caps (`standards`), and the friction-factor and valve
capacity functions (`preliminary_sizing`). It does not copy them.
"""
from blocks.fluid import Fluid
from blocks.sizing import FlowDemand, flow_from_heat, size_pipe, head_m
from blocks.base import BlockResult, ElementResult
from blocks.rack_branch import RackBranchSpec, build_rack_branch
from blocks.row import RowSpec, build_row

__all__ = ['Fluid', 'FlowDemand', 'flow_from_heat', 'size_pipe', 'head_m',
           'BlockResult', 'ElementResult', 'RackBranchSpec', 'build_rack_branch',
           'RowSpec', 'build_row']
