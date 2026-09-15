import argparse
from dataclasses import asdict
import json
from pathlib import Path
import jd_material_agent as agent
import manual_resume
import direct_resume

def build_parser():
    parser = argparse.ArgumentParser(description='Independent self-operated material maintenance')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('provider-info')
    inspect = sub.add_parser('inspect-handoff')
    inspect.add_argument('--handoff', type=Path, required=True)
    inspect.add_argument('--erp', required=True)
    plan = sub.add_parser('plan-resume')
    plan.add_argument('--handoff', type=Path, required=True)
    plan.add_argument('--erp', required=True)
    plan.add_argument('--output-dir', type=Path, required=True)
    plan.add_argument('--cache-dir', type=Path, nargs='+', required=True)
    direct_plan = sub.add_parser('plan-direct', parents=[plan], add_help=False)
    direct_plan.set_defaults(command='plan-direct')
    export = sub.add_parser('export-pending')
    export.add_argument('--output-dir', type=Path, required=True)
    export.add_argument('--delivery-dir', type=Path, required=True)
    export.add_argument('--erp', required=True)
    export.add_argument('--confirm-token', required=True)
    discover = sub.add_parser('plan-self-operated')
    discover.add_argument('--erp', required=True)
    discover.add_argument('--owner-erp')
    discover.add_argument('--output-dir', type=Path)
    discover.add_argument('--target-spu-id')
    discover.add_argument('--target-spu-ids', nargs='+')
    discover.add_argument('--webcli-profile')
    discover.add_argument('--timeout', type=float, default=180)
    run = sub.add_parser('run-resume')
    run.add_argument('--erp', required=True)
    run.add_argument('--output-dir', type=Path, required=True)
    run.add_argument('--confirm-token', required=True)
    run.add_argument('--confirm', required=True)
    run.add_argument('--webcli-profile')
    run.add_argument('--limit', type=int)
    run.add_argument('--batch-size', type=int, default=10)
    run.add_argument('--defer-incomplete', action='store_true')
    run.add_argument('--category-id', type=int, default=0)
    run.add_argument('--spu-concurrency', type=int, default=5)
    run.add_argument('--image-concurrency', type=int, default=4)
    run.add_argument('--timeout', type=float, default=600)
    direct_run = sub.add_parser('run-direct', parents=[run], add_help=False)
    direct_run.set_defaults(command='run-direct')
    direct_run.add_argument('--repair-segment')
    direct_run.add_argument('--cached-only', action='store_true')
    direct_run.add_argument('--pipeline', action='store_true')
    direct_run.add_argument('--resource-cooldown', action='store_true')
    title_run = sub.add_parser('run-titles', parents=[run], add_help=False)
    title_run.set_defaults(command='run-titles')
    first = sub.add_parser('maintain-self-operated')
    first.add_argument('--erp')
    first.add_argument('--output-dir', type=Path)
    first.add_argument('--webcli-profile')
    first.add_argument('--target-spu-id')
    first.add_argument('--target-spu-ids', nargs='+')
    first.add_argument('--confirm')
    first.add_argument('--plan-only', action='store_true')
    first.add_argument('--batch-size', type=int, default=10)
    first.add_argument('--category-id', type=int, default=0)
    first.add_argument('--spu-concurrency', type=int, default=5)
    first.add_argument('--image-concurrency', type=int, default=4)
    first.add_argument('--timeout', type=float, default=600)
    first.add_argument('--pipeline', action=argparse.BooleanOptionalAction, default=True)
    first.add_argument('--resource-cooldown', action='store_true')
    return parser

def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == 'maintain-self-operated':
        import first_use
        result = first_use.run_auto(args)
    elif args.command == 'provider-info':
        result = {**asdict(agent.PROVIDER), 'variant': agent.VARIANT_ID, 'version': agent.SKILL_VERSION}
    elif args.command == 'inspect-handoff':
        snapshot = manual_resume.load_handoff(args.handoff, args.erp)
        result = {'status': 'verified-offline', 'summary': snapshot.queue['summary'], 'source': snapshot.queue['basis'], 'legacyRunnerMustNotResume': True}
    elif args.command == 'plan-resume':
        result = manual_resume.plan_resume(args.handoff, args.erp, args.output_dir, args.cache_dir)
    elif args.command == 'plan-direct':
        result = direct_resume.plan_direct(args.handoff, args.erp, args.output_dir, args.cache_dir)
    elif args.command == 'export-pending':
        result = manual_resume.export_pending(args.output_dir, args.erp, args.confirm_token, args.delivery_dir)
        result = {key: value for key, value in result.items() if key not in ('scope', 'incomplete')}
    elif args.command == 'run-resume':
        result = manual_resume.run_resume(args)
    elif args.command == 'run-direct':
        result = direct_resume.run_direct(args)
    elif args.command == 'run-titles':
        import direct_titles
        result = direct_titles.run_titles(args)
    else:
        result = agent.run_plan_self_operated(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
