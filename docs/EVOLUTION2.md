# Evolution 2.0 and unified distributed training (0.5.3)

Evolution 2.0 keeps improving **the same** MOTH model. Details of the original engine (cycles, gates,
monitoring, rollback) are in [EVOLUTION.md](EVOLUTION.md); this page describes what 0.5.3 adds.

## Continuous improvement from the development checkpoint

* Each candidate keeps its full training checkpoint (weights + AdamW moments) as its *development
  checkpoint*. When it is promoted, the next cycle continues exactly from there — never from random
  weights. A model imported as a release (e.g. MOTH 0.1) starts its first cycle from its weights.
* Lineage totals (tokens, steps, cycles) accumulate across versions; every version records its parent,
  method (`foundation`, `continued`, `expansion`) and the data builds it was trained on.
* Training only happens on the development branch; the stable model keeps serving until a candidate has
  passed every gate and its staged rollout.

## Research laboratory

* Experiments train on the dataset library's **curriculum mixture** (all capability domains at once),
  with variants per cycle: a weakness-tilted mixture, a balanced mixture, and learning rates ranked by
  earlier results on the same architecture.
* A configuration that was already tried on the same base, data and settings is never repeated.
* **Early stopping:** a run whose held-out loss rises by 5% or does not improve for three evaluations is
  stopped and rejected, saving compute.
* The gate measures the weighted held-out improvement over the trained domains, plus every capability
  benchmark (a drop beyond two standard errors is a regression — memory protection), retention on earlier
  data, speed and memory.

## Distributed CPU/GPU training (unified with MOTH Code)

* When at least two compatible participants are online, an experiment trains in **rounds**: every
  participant receives the round's verified weights and its own slice of the curriculum data, trains
  locally and returns its weight delta. The server checks each delta (base hash, round, shapes, finite
  values, size bound), averages them weighted by tokens, and applies the result only if its own probe
  loss on held-out data does not get worse — otherwise the round is discarded.
* A repeated or late submission is refused, so no step is counted twice; an expired lease returns the
  shard to the queue for another participant (disconnections recover automatically).
* Participants' work follows their measured speed (local steps 0.25–4× the base), so CPUs do not hold
  up GPUs; GPU workers are preferred for training.
* **Evaluation on CPU workers:** held-out capability losses of candidates are measured by two different
  CPU workers (MOTH Worker 0.5.3+); the result counts only if they agree, otherwise the server measures.
* **MOTH Code contributes its computer** with the same worker loop (Model training → *Contribute this
  computer*, or Network): one lineage, one experiment, the desktop and the workers side by side. *Use
  cloud workers* (on by default) lets experiments spread across the network. The Owner sees each
  participant's verified contribution per round.

## Adaptive Parameter Growth

* The growth planner looks at the improvements of the last cycles, the gap between training and held-out
  loss and the compute budget. It proposes nothing while the model still improves (≥ 1% per cycle) or
  overfits (held-out loss more than 0.3 above training loss).
* Increments are flexible: 5–40% more parameters, larger after longer plateaus, within the budget
  (`growth.max_params`, `growth.max_ratio`) and architectural constraints (whole layers, FFN widths in
  multiples of 64).
* Growth is **function-preserving**: inserted layers start with zero output projections and new FFN
  units with zero output weights, so the grown model computes exactly what the old one did (tested to
  1e-5); AdamW moments of existing weights move with them.
* The expansion is a separate candidate: trained further, evaluated like any other, deployed only if it
  is better; otherwise it is discarded and the stable model is untouched. Above `growth.approval_ratio`
  (default +25%) it waits for the Owner's approval.

## Promotion, versions and serving

* A promoted candidate first serves **20%** of users (stable hash of the user id) while monitored; the
  stable model serves the rest. It then becomes stable for everyone, or is dropped — the stable model
  never stops serving.
* Newly stable models get the next model version of their lineage (MOTH 0.1 → 0.2 → 0.3), recorded once.
* MOTH Cloud signs a manifest for every promoted model with its own ed25519 model key; MOTH Code pins
  that key on first use.
* Users can pin a served model version.
