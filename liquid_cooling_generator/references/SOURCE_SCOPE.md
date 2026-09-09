# Source basis and scope

1. User-supplied **RD113DSR0-VR.pdf**, pages 2, 5, 6, 9. See `rd113_attachment/rd113_r0_findings.md`. The page-5 spatial diagram reconciles to 64 AI + 24 network racks; narrative/table rack counts conflict. Six-foot hot aisles are a reference value; generic cold/service clearances are project assumptions. [Current Schneider download page](https://www.se.com/sg/en/download/document/RD113DS/) now serves a newer revision.
2. [OCP ACF Reference Design Guidance](https://www.opencompute.org/documents/ocp-acf-reference-design-guidance-white-paper-pdf-1), Layout Planning, p.9: consider installation and operational clearances and equipment weight. This does not supply our generic numeric service allowances.
3. [OCP rack manifold requirements and qualification](https://www.opencompute.org/documents/ocp-white-paper-rack-manifold-requirements-and-qualification-v3-pdf), plumbing/serviceability, p.16: serviceable plumbing, local flow-control equipment and quick coupling considerations. The model's selected device counts and envelope dimensions remain project inputs.
4. [OCP Modular TCS final 2025](https://www.opencompute.org/documents/ocp-modular-tcs-rev-1-final-2025-pdf), §3.5: velocity selection tradeoffs; do not interpret the older March partial extract as a universal mandatory 2.7 m/s cap. All three active cap values are labelled project assumptions.
5. OCP Deschutes module, indicative local partial extract, §18: dimensions concern that particular module. The interface does not represent them as universal data-center dimensions.
6. Local ASHRAE chapter excerpts are indicative and support qualitative source context only. The generator does not infer universal numeric installation rules from them.

Accessed September 2026. Source references explain tuning choices; they are not an assertion of certification or compliance with all applicable installation requirements.
