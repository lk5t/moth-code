# Protocols: MOTH Cloud and community learning

Neither MOTH Cloud nor a public community coordinator is operated yet. Both protocols are implemented and tested
end to end with reference servers that anyone can run. The app ships with **no endpoints configured** and says so.

## MOTH Cloud — `moth-cloud/1`

Reference server, which serves one exported MOTH model:

```bash
moth cloud-serve --model ~/.moth/models/my-model --port 8800 --api-key KEY
```

| Endpoint | Description |
| --- | --- |
| `GET /v1/health` | `{"service": "moth-cloud", "protocol": 1, "models": [{name, architecture, params, context_length, sha256}]}` |
| `POST /v1/chat` | Body `{"model", "messages": [{role, content, trusted}], "params"}`. Returns NDJSON: `{"text": …}`… then `{"done": true, "stats": {…}}`, or `{"error": …}`. |

The client (`moth/inference/cloud.py`) refuses servers that don't identify as `moth-cloud/1` or that offer any model
whose `architecture` isn't a MOTH architecture (`moth-decoder-v1`). Clients can't mark user content as trusted; only
assistant turns may carry special tokens.

Routing (`moth/inference/router.py`): **Local** always runs on the PC. **MOTH Cloud** requires consent for chat, and
separate consent for project data (agent tasks). **Automatic** uses local when a model is loaded, otherwise MOTH
Cloud with the same consents. Messages are credential-redacted before sending.

## Community learning — `moth-community/1`

```mermaid
sequenceDiagram
  participant C as Participant (opt-in)
  participant K as Coordinator
  C->>K: GET /v1/jobs/next?client_id=random-id
  K-->>C: JobSpec(round, model_version, base_sha256, model_config, tokenizer_fingerprint, shard, train spec)
  C->>K: GET /v1/models/{version}/weights   (verify sha256)
  C->>K: GET /v1/shards/{id}                (public data, verify sha256)
  Note over C: train locally within GPU memory cap / duty cycle / schedule
  C->>K: POST /v1/contributions  body = Δweights, header X-Moth-Contribution = metadata
  K-->>C: accepted / rejected (+ reasons); aggregation when enough contributions
```

**What a participant shares.** Only the weight delta and statistics (steps, tokens, loss before and after on a
held-out slice of the shard). The `client_id` is random and not derived from the user or the machine. Nothing from
local projects is read.

**Controls** (`moth/community/resources.py`):

- opt-in (off by default)
- pause
- GPU memory fraction cap
- duty cycle (fraction of time spent computing)
- weekly schedule with overnight windows
- daily round limit

**Coordinator validation** (`coordinator.py`, `validation.py`). A contribution is accepted only if:

- the protocol version matches
- the job is known and current
- the base checkpoint SHA matches the current version
- the payload checksum matches
- tensor keys and shapes match exactly
- all values are finite
- each tensor's relative update norm is ≤ 0.5
- the update is non-empty
- applying it does not worsen the coordinator's held-out **probe loss** beyond a small tolerance

**Aggregation and versioning.** Accepted deltas are averaged, weighted by the number of tokens trained. Each new
checkpoint version is stored with its parent SHA, round, contributor IDs and probe loss.

Running a private coordinator:

```bash
moth coordinator init --dir coord --model ~/.moth/models/base --dataset ~/.moth/datasets/public --shards 16 --min-contributions 4
```

```bash
moth coordinator serve --dir coord --port 8900 --admin-token SECRET
```

**Future work.** Secure aggregation, robust aggregation (e.g. trimmed mean) against coordinated poisoning,
contributor reputation, differential-privacy noise, and distributing larger models (sharded or partial updates).
