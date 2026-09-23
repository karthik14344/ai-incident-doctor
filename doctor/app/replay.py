"""Replay trigger: diagnose a stored incident again from its evidence snapshot.

    python -m app.replay inc_7d9a2ebe7a
    python -m app.replay incidents/recorded/b1-timeout-1/bundle.json --arm logs_only \
        --provider ollama --model llama3 --out runs/

Nothing live is touched: the bundle already holds the alert, logs, metric
series, deploy records and commit range. The evaluation harness uses only this
entry point, so every run is repeatable without breaking the app again.
"""

import argparse
import json
import os
import sys
import time

from app import reasoner, report, store
from app.prompt import ARMS
from app.settings import SETTINGS, provider_config, ProviderConfig


def load_bundle(ref: str):
    if os.path.exists(ref):
        with open(ref, encoding="utf-8") as fh:
            return json.load(fh)
    bundle = store.load(ref, "bundle.json")
    if bundle is None:
        raise SystemExit(f"no stored incident or bundle file called {ref!r}")
    return bundle


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("incident", help="incident id in the doctor's store, or a path to bundle.json")
    ap.add_argument("--arm", choices=ARMS, default="logs_commits_incidents")
    ap.add_argument("--provider", help="override DOCTOR_PROVIDER for this run")
    ap.add_argument("--model")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--out", help="directory for report.json / report.md (default: print)")
    args = ap.parse_args(argv)

    bundle = load_bundle(args.incident)
    if args.provider:
        base = provider_config("DOCTOR") if (SETTINGS.primary and SETTINGS.primary.provider == args.provider) else None
        cfg = ProviderConfig(provider=args.provider, model=args.model or (base.model if base else ""),
                             api_key=base.api_key if base else None, base_url=base.base_url if base else None)
        if args.provider == "ollama":
            from app.settings import doctor_ollama_url
            cfg.base_url = doctor_ollama_url()
        providers = [cfg]
    else:
        providers = None
    started = time.time()
    result = reasoner.diagnose(bundle, arm=args.arm, providers=providers, verify_fix=not args.no_verify)
    result["trigger"] = "replay"
    result["replayed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))
    md = report.to_markdown(result, bundle)
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1, default=str)
        with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as fh:
            fh.write(md)
        print(os.path.join(args.out, "report.json"))
    else:
        print(md)
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
