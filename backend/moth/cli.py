"""``moth`` command-line interface.

Long-running work (tokenizer training, dataset preparation, model training,
evaluation) runs through these subcommands — either by hand or as isolated
subprocesses launched by the desktop backend. With ``--json-events`` every
progress update is printed as one JSON object per line, prefixed with
``@moth `` so it can be told apart from ordinary log output.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

EVENT_PREFIX = "@moth "


class Emitter:
    def __init__(self, json_events: bool):
        self.json_events = json_events

    def __call__(self, event: dict[str, Any]) -> None:
        if self.json_events:
            print(EVENT_PREFIX + json.dumps(event, default=str), flush=True)
        else:
            kind = event.get("kind", "")
            rest = {k: v for k, v in event.items() if k not in ("kind", "model_config")}
            print(f"[{kind}] " + " ".join(f"{k}={_fmt(v)}" for k, v in rest.items()), flush=True)


def _fmt(v: Any) -> str:
    return f"{v:.4f}" if isinstance(v, float) else str(v)


def _stop_file_checker(path: str | None):
    if not path:
        return lambda: False
    p = Path(path)
    return lambda: p.exists()


def cmd_tokenizer(args, emit: Emitter) -> None:
    from moth.model.tokenizer import train_bpe
    from moth.training.sources import SourceSpec, iter_source, resolve_license

    specs = [SourceSpec.from_any(json.loads(s) if s.startswith("{") else s) for s in args.source]
    for s in specs:
        resolve_license(s)
    stop = _stop_file_checker(args.stop_file)
    budget = int(args.max_mb * 1024 * 1024)

    def texts():
        used = 0
        for spec in specs:
            for doc in iter_source(spec):
                if stop():
                    raise InterruptedError("cancelled")
                yield doc.text
                used += len(doc.text)
                if used >= budget:
                    return

    emit({"kind": "status", "message": "counting pre-tokens"})
    tok = train_bpe(texts(), args.vocab_size,
                    progress=lambda done, total: emit({"kind": "progress", "done": done, "total": total}))
    tok.save(args.out)
    emit({"kind": "done", "path": str(args.out), "vocab_size": tok.vocab_size, "fingerprint": tok.fingerprint()})


def cmd_prepare(args, emit: Emitter) -> None:
    from moth.model.tokenizer import Tokenizer
    from moth.training.data import prepare_dataset

    tok = Tokenizer.load(args.tokenizer)
    sources = [json.loads(s) if s.startswith("{") else s for s in args.source]
    meta = prepare_dataset(sources, tok, args.tokenizer, args.out, args.val_fraction,
                           progress=lambda p: emit({"kind": "progress", **p}),
                           should_stop=_stop_file_checker(args.stop_file))
    emit({"kind": "done", "path": str(args.out), "tokens": meta["tokens"], "documents": meta["documents"]})


def cmd_train(args, emit: Emitter) -> None:
    from moth.training.trainer import TrainConfig, Trainer

    cfg = TrainConfig.from_dict(json.loads(Path(args.config).read_text()))
    result = Trainer(cfg, on_event=emit).run()
    emit({"kind": "done", **result})


def cmd_eval(args, emit: Emitter) -> None:
    from moth.model.registry import load_model
    from moth.training.evaluate import evaluate_model

    model, tok, _ = load_model(args.model, device=args.device)
    report = evaluate_model(model, tok, args.dataset)
    emit({"kind": "done", "report": report.to_dict()})


def cmd_export(args, emit: Emitter) -> None:
    from moth.model.registry import export_model

    info = export_model(args.checkpoint, args.models_dir, args.name, args.dtype)
    emit({"kind": "done", "model": info})


def cmd_generate(args, emit: Emitter) -> None:
    from moth.model.generation import GenerationParams, generate_stream
    from moth.model.registry import load_model

    model, tok, _ = load_model(args.model, device=args.device)
    params = GenerationParams(max_new_tokens=args.max_new_tokens, temperature=args.temperature)
    for piece in generate_stream(model, tok, [tok.bos_id] + tok.encode(args.prompt), params):
        sys.stdout.write(piece)
        sys.stdout.flush()
    sys.stdout.write("\n")


def cmd_serve(args, emit: Emitter) -> None:
    from moth.server.__main__ import main as serve_main

    serve_main(args.rest)


def cmd_coordinator(args, emit: Emitter) -> None:
    from moth.community.coordinator import main as coord_main

    coord_main(args.rest)


def cmd_community_round(args, emit: Emitter) -> None:
    from moth.community.client import CommunityClient
    from moth.community.resources import ParticipationSettings

    settings = ParticipationSettings.from_dict(json.loads(Path(args.settings).read_text()))
    client = CommunityClient(settings, client_id=args.client_id)
    result = client.run_round(should_stop=_stop_file_checker(args.stop_file), on_event=emit)
    emit({"kind": "done", **result})


def cmd_cloud_serve(args, emit: Emitter) -> None:
    from moth.inference.cloud_server import main as cloud_main

    cloud_main(args.rest)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="moth", description="MOTH Code command-line tools")
    p.add_argument("--json-events", action="store_true", help="emit machine-readable progress events")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("tokenizer", help="train a BPE tokenizer")
    t.add_argument("--source", action="append", required=True, help="source spec (repeatable), e.g. stdlib")
    t.add_argument("--vocab-size", type=int, default=16384)
    t.add_argument("--max-mb", type=float, default=200.0, help="max characters (MiB) of text to learn from")
    t.add_argument("--out", required=True)
    t.add_argument("--stop-file")
    t.set_defaults(fn=cmd_tokenizer)

    d = sub.add_parser("prepare", help="tokenise sources into a training dataset")
    d.add_argument("--source", action="append", required=True)
    d.add_argument("--tokenizer", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--val-fraction", type=float, default=0.02)
    d.add_argument("--stop-file")
    d.set_defaults(fn=cmd_prepare)

    tr = sub.add_parser("train", help="train or resume a model (config JSON = TrainConfig)")
    tr.add_argument("--config", required=True)
    tr.set_defaults(fn=cmd_train)

    e = sub.add_parser("eval", help="evaluate an exported model")
    e.add_argument("--model", required=True)
    e.add_argument("--dataset")
    e.add_argument("--device", default="cpu")
    e.set_defaults(fn=cmd_eval)

    x = sub.add_parser("export", help="export a checkpoint as a local inference model")
    x.add_argument("--checkpoint", required=True)
    x.add_argument("--models-dir", required=True)
    x.add_argument("--name", required=True)
    x.add_argument("--dtype", default="float16", choices=["float16", "bfloat16", "float32"])
    x.set_defaults(fn=cmd_export)

    g = sub.add_parser("generate", help="generate text from an exported model")
    g.add_argument("--model", required=True)
    g.add_argument("--prompt", required=True)
    g.add_argument("--max-new-tokens", type=int, default=128)
    g.add_argument("--temperature", type=float, default=0.8)
    g.add_argument("--device", default="cpu")
    g.set_defaults(fn=cmd_generate)

    s = sub.add_parser("serve", help="run the local API server")
    s.add_argument("rest", nargs=argparse.REMAINDER)
    s.set_defaults(fn=cmd_serve)

    cr = sub.add_parser("community-round", help="contribute one community training round")
    cr.add_argument("--settings", required=True, help="participation settings JSON file")
    cr.add_argument("--client-id", required=True)
    cr.add_argument("--stop-file")
    cr.set_defaults(fn=cmd_community_round)

    cs = sub.add_parser("cloud-serve", help="serve a MOTH model over the moth-cloud/1 protocol")
    cs.add_argument("rest", nargs=argparse.REMAINDER)
    cs.set_defaults(fn=cmd_cloud_serve)

    c = sub.add_parser("coordinator", help="run a community training coordinator")
    c.add_argument("rest", nargs=argparse.REMAINDER)
    c.set_defaults(fn=cmd_coordinator)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    args = build_parser().parse_args(argv)
    emit = Emitter(args.json_events)
    try:
        args.fn(args, emit)
        return 0
    except KeyboardInterrupt:
        emit({"kind": "error", "message": "interrupted"})
        return 130
    except InterruptedError as e:
        emit({"kind": "cancelled", "message": str(e)})
        return 2
    except Exception as e:
        emit({"kind": "error", "message": f"{type(e).__name__}: {e}", "ts": time.time()})
        if not args.json_events:
            raise
        return 1


if __name__ == "__main__":
    sys.exit(main())
