# Adding a reference design

A preset is a claim: *this is what that published design looks like in this
generator*. The claim has to be checkable, or the preset is decoration. Five
artifacts make it checkable, and they are the whole procedure.

## 1. The extraction — what the documents say

`references/<design>/<design>_findings.json`

Record what you read, with a SHA-256 per source document and the page each
figure came from. **Do not bundle the PDFs.** A figure with no traceable source
is not evidence, and the extraction must say so rather than looking confident:
`references/motivair/mcdu_selection_table.json` records `"sha256": null` and
why, because it arrived as a screenshot.

Three things belong here that authors usually skip:

- **`not_published`** — what the documents do *not* state. RD113 lists pipe
  diameters under project or OEM inputs, so nothing downstream of pipe sizing
  can be checked against it. An unchecked quantity must be visible.
- **Conflicts between sources**, unresolved. RD113 R0 gave 640, 800 and 880 kW
  for the same networking load in different places; R1 settled it at 880. That
  history is worth keeping.
- **Revision deltas**, when a newer revision supersedes an older one.

## 2. The design profile — which body governs what

`standards.PROFILES[<name>]`

A profile names the parameters its body genuinely mandates and supplies their
values. Everything else it does not govern is demoted to a project assumption,
whatever document it was sourced from.

Be strict about `governs`. RD113 publishes its rack and its AI hot aisle and
explicitly defers dimensions, clearances and pipe sizes to the project, so it
governs exactly three parameters. Claiming more would attribute a mandate to a
document that does not make one — which is the failure this registry exists to
prevent. `validate_design.py` fails any design whose critical parameters fall
outside its profile's `governs` set.

Set `document` only when the source is in `references/corpus/`, since that is
what gates the decision register.

## 3. The preset — the configuration

`parameters.PRESETS[<name>]`

Every value that came from a document carries a comment naming the document and
what it says. Values the documents do not give are inherited from `DEFAULT` and
are project assumptions by construction.

Where the generator cannot represent something, say so in the comment rather
than approximating silently. RD113 has a three-way networking split (15 / 35 /
45 kW) and the generator supports one base power plus one high band, so the
preset notes that the 16 high racks carry their exact 40 kW average.

Then regenerate the CLI files — `presets/*.json` and `parameters.PRESETS` are
one definition with two entry points, and a test fails if they drift.

## 4. The benchmark — the claim, checked

`references/benchmarks/<design>.json`

One row per published value, each with a unit, a tolerance and its page. Use
`comparison: "at_most"` or `"at_least"` for a published *limit*, which is
satisfied by being on the right side of it rather than by matching.

A difference is adjudicated or it fails. `adjudication` records a difference
someone has examined and explained — it stays visible and does not fail the run.
Anything else is a failure, and `benchmark.py` exits non-zero. Three kinds of
adjudication have come up so far:

- **a different operating state** — RD113 sizes CDUs on Max-P, the preset carries Max-Q;
- **a different declared assumption** — RD113 allocates across six of eight
  CDUs on one loop, the generator treats pods as independent;
- **a generator limitation** — a pump bank of more than two units clashes with
  the chiller collectors, so the preset carries two.

The third kind is the one to be honest about. Recording it is not the same as
accepting it.

## 5. The equipment ratings — enough, or not

Selecting a unit is a capacity question with no partial credit:
`cdu_available_head_kPa`, `cdu_nominal_flow_L_min` and `cdu_rated_capacity_kW`
carry the published rating, and the screen reports whether required head, flow
and capacity all fit. Any one short raises `CDU_RATING_EXCEEDED` and flags the
unit in the 3D view.

Take the rating at the condition that matches the design. The MCDU-70's 2500 kW
row is rated at primary 105.8 °F and secondary PG25 at 113 °F, which is RD113's
own 40 °C and 45 °C — so that is the number, not the 5040 kW headline.

## Checking the result

```sh
python3 benchmark.py --all                 # the claim against the documents
python3 validate_design.py --all-presets   # the engine against first principles
python3 -m pytest tests -q                 # the engine against itself
```

All three, green, before the preset is real.
