"""Command-line interface."""
from __future__ import annotations
import argparse
import logging
from pathlib import Path
from .data import generate_requests, load_requests
from .simulator import simulate


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="pcache")
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="create a synthetic request log")
    g.add_argument("--out", type=Path, default=Path("data/requests.csv"))
    g.add_argument("--hours", type=int, default=72)
    s = sub.add_parser("simulate", help="compare cache policies")
    s.add_argument("--data", type=Path)
    s.add_argument("--generate", action="store_true")
    s.add_argument("--capacity", type=int, default=200)
    r = sub.add_parser("report", help="save metrics.csv and PNG charts")
    r.add_argument("--data", type=Path)
    r.add_argument("--generate", action="store_true")
    r.add_argument("--capacity", type=int, default=200)
    r.add_argument("--out", type=Path, default=Path("reports"))
    r.add_argument("--k", type=int, default=10, help="k for precision@k")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.cmd == "generate":
        args.out.parent.mkdir(parents=True, exist_ok=True)
        generate_requests(hours=args.hours).to_csv(args.out, index=False)
        print(f"wrote {args.out}")
        return
    df = generate_requests() if args.generate or not args.data else load_requests(args.data)
    if args.cmd == "simulate":
        print("Hit rate (%) on held-out hours:")
        print(simulate(df, args.capacity).to_string())
    else:
        from .report import build_report  # matplotlib is only needed here
        metrics = build_report(df, args.capacity, args.out, args.k)
        summary = metrics[metrics["section"] != "top_sample"]
        print(summary.pivot(index="region", columns="name", values="value").to_string())
        print(f"wrote charts and metrics.csv to {args.out}/")


if __name__ == "__main__":
    main()
