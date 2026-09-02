"""CLI for simple reviewable article revision proposals."""

from __future__ import annotations

import argparse
import json
import sys

from ..proposals import (
    ProposalError,
    accept_proposal,
    create_proposal,
    reject_proposal,
    show_proposal,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="创建、查看、接受或拒绝任务内修改提案")
    sub = parser.add_subparsers(dest="action", required=True)

    create = sub.add_parser("create", help="生成候选稿与初稿的 unified diff")
    create.add_argument("--run-id")
    create.add_argument("--summary", default="")
    create.add_argument("--replace", action="store_true")

    show = sub.add_parser("show", help="查看当前修改提案")
    show.add_argument("--run-id")

    accept = sub.add_parser("accept", help="把当前候选稿应用为成稿")
    accept.add_argument("--run-id")

    reject = sub.add_parser("reject", help="拒绝提案且不修改成稿")
    reject.add_argument("--run-id")
    reject.add_argument("--reason", default="")

    args = parser.parse_args(argv)
    try:
        if args.action == "create":
            result = create_proposal(args.run_id, summary=args.summary, replace=args.replace)
        elif args.action == "show":
            result = show_proposal(args.run_id)
        elif args.action == "accept":
            result = accept_proposal(args.run_id)
        else:
            result = reject_proposal(args.run_id, reason=args.reason)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ProposalError, FileNotFoundError, KeyError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
