#!/usr/bin/env python3
"""Small append-only governance record. No knowledge edits or native submissions."""
import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys


class Invalid(ValueError):
    pass


COMMON = {'version', 'id', 'at', 'scope', 'type', 'targets', 'evidence'}
EXTRA = {
    'issue': {'issue_id', 'previous', 'goal', 'advice', 'remaining', 'status',
              'blocker', 'recheck', 'submissions'},
    'feedback': {'task_id', 'effect'},
    'action': {'detail', 'verification', 'reviewed_feedback'},
}


def require(ok, message):
    if not ok:
        raise Invalid(message)


def text(value, blank=False):
    return isinstance(value, str) and (blank or bool(value.strip()))


def absolute(value):
    return text(value) and os.path.isabs(value) and os.path.normpath(value) == value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f'duplicate JSON key: {key}')
        result[key] = value
    return result


def parse(raw):
    return json.loads(raw, object_pairs_hook=unique_object)


def shape(e):
    require(isinstance(e, dict), 'event must be an object')
    kind = e.get('type')
    require(isinstance(kind, str) and kind in EXTRA, 'invalid event type')
    require(set(e) == COMMON | EXTRA[kind], 'missing or unknown event fields')
    require(type(e['version']) is int and e['version'] == 1, 'version must be 1')
    for key in ('id', 'at', 'evidence'):
        require(text(e[key]), f'{key} must be nonempty text')
    require(datetime.fromisoformat(e['at'].replace('Z', '+00:00')).utcoffset() is not None,
            'at requires timezone')
    scope = e['scope']
    require(isinstance(scope, dict) and set(scope) == {'kind', 'root'}, 'invalid scope')
    require(scope['kind'] in ('project', 'user') and absolute(scope['root']),
            'scope requires kind and normalized absolute root')
    targets = e['targets']
    require(isinstance(targets, list) and targets and all(text(t) for t in targets),
            'targets must contain concrete nonempty locations')
    require(len(set(targets)) == len(targets), 'duplicate targets')
    if kind == 'issue':
        for key in ('issue_id', 'goal', 'advice'):
            require(text(e[key]), f'{key} required')
        for key in ('remaining', 'blocker', 'recheck'):
            require(text(e[key], blank=True), f'{key} must be text')
        require(e['previous'] is None or text(e['previous']), 'invalid previous')
        require(e['status'] in ('open', 'resolved', 'withdrawn', 'invalid'), 'invalid status')
        require(bool(e['remaining'].strip()) == (e['status'] == 'open'),
                'open needs remaining; closed must clear remaining')
        require(not e['blocker'].strip() or bool(e['recheck'].strip()), 'blocker needs recheck')
        require(isinstance(e['submissions'], list), 'submissions must be a list')
        paths = set()
        for s in e['submissions']:
            require(isinstance(s, dict) and set(s) == {'path', 'sha256'}, 'invalid submission')
            require(absolute(s['path']) and isinstance(s['sha256'], str)
                    and re.fullmatch(r'[0-9a-f]{64}', s['sha256']), 'invalid submission path/hash')
            require(s['path'] not in paths, 'duplicate submission path')
            paths.add(s['path'])
    elif kind == 'feedback':
        require(len(targets) == 1 and text(e['task_id']), 'feedback needs one target and task_id')
        require(e['effect'] in ('helped', 'failed', 'exception', 'corrected'), 'invalid effect')
    else:
        require(text(e['detail']) and text(e['verification']), 'action needs detail/verification')
        refs = e['reviewed_feedback']
        require(isinstance(refs, list) and all(text(r) for r in refs), 'invalid reviewed_feedback')
        require(len(set(refs)) == len(refs), 'duplicate feedback references')


def transition(e, events):
    by_id = {x['id']: x for x in events}
    require(e['id'] not in by_id, 'duplicate event id')
    if e['type'] == 'issue':
        prior = [x for x in events if x['type'] == 'issue' and x['issue_id'] == e['issue_id']]
        if not prior:
            require(e['issue_id'] == e['id'] and e['previous'] is None
                    and e['status'] == 'open', 'first issue must be open with issue_id=id, previous=null')
        else:
            last = prior[-1]
            require(e['scope'] == last['scope'], 'issue scope cannot change')
            require(e['previous'] == last['id'], 'stale previous; read latest issue before updating')
            require(all(s in e['submissions'] for s in last['submissions']),
                    'retain previous submission evidence')
    elif e['type'] == 'action':
        for ref in e['reviewed_feedback']:
            f = by_id.get(ref)
            require(f is not None and f['type'] == 'feedback', 'feedback reference not found')
            require(f['scope'] == e['scope'] and set(f['targets']) <= set(e['targets']),
                    'feedback scope/target mismatch')


def home():
    return Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser().resolve()


def safe_ledger(value):
    p = Path(value).expanduser().absolute()
    require(p.name == 'events.jsonl', 'ledger filename must be events.jsonl')
    for part in (p, *p.parents):
        require(not part.is_symlink(), f'symlink not allowed: {part}')
    protected = [home() / 'memories', Path.home() / '.codex/memories',
                 Path(__file__).resolve().parents[1]]
    resolved = p.resolve()
    require(not any(resolved == q.resolve() or q.resolve() in resolved.parents for q in protected),
            'ledger must be outside system memories and the skill')
    if p.exists():
        info = p.stat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'ledger must be a regular single-link file')
    return p


@contextmanager
def locked(p, write=False):
    # Lock the existing state directory so first creation needs no lock file.
    p = safe_ledger(p)
    if write:
        p.parent.mkdir(parents=True, exist_ok=True)
    if not p.parent.exists():
        yield p
        return
    fd = os.open(p.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, (fcntl.LOCK_EX if write else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        yield safe_ledger(p)
    finally:
        os.close(fd)


def read_unlocked(p):
    if not p.exists():
        return []
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'r', encoding='utf-8') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'unsafe ledger file')
        events = []
        for number, line in enumerate(stream, 1):
            try:
                require(line.endswith('\n'), 'incomplete tail; preserve original, do not auto-repair')
                e = parse(line)
                shape(e)
                transition(e, events)
            except (ValueError, TypeError, KeyError) as err:
                raise Invalid(f'line {number}: {err}') from err
            events.append(e)
        return events


def read(value):
    with locked(value) as p:
        return read_unlocked(p)


def duplicate(e, events):
    for old in events:
        if old['id'] == e['id']:
            require(old == e, 'id already exists with different content')
            return old['id']
        if e['type'] == old['type'] == 'feedback':
            keys = ('scope', 'targets', 'task_id', 'effect', 'evidence')
            if all(old[k] == e[k] for k in keys):
                return old['id']
    if e['type'] == 'issue':
        prior = [x for x in events if x['type'] == 'issue' and x['issue_id'] == e['issue_id']]
        if prior:
            last = prior[-1]
            require(e['previous'] == last['id'], 'stale previous; read latest issue before updating')
            keys = set(e) - {'id', 'at', 'previous'}
            if all(last[k] == e[k] for k in keys):
                return last['id']
    return None


def append(value, e):
    shape(e)
    with locked(value, write=True) as p:
        events = read_unlocked(p)
        existing = duplicate(e, events)
        if existing:
            return {'appended': False, 'id': existing}
        transition(e, events)
        data = (json.dumps(e, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')
        fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'unsafe ledger file')
            with os.fdopen(fd, 'ab', closefd=False) as stream:
                stream.write(data)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        return {'appended': True, 'id': e['id']}


def select(events, scope, pending=False, query=''):
    scoped = [e for e in events if e['scope'] == scope]
    if pending:
        latest = {}
        reviewed = {r for e in scoped if e['type'] == 'action' for r in e['reviewed_feedback']}
        for e in scoped:
            if e['type'] == 'issue':
                latest[e['issue_id']] = e
        scoped = [e for e in scoped if
                  (e['type'] == 'issue' and latest[e['issue_id']]['id'] == e['id'] and e['status'] == 'open')
                  or (e['type'] == 'feedback' and e['id'] not in reviewed)]
    return [e for e in scoped if query.casefold() in json.dumps(e, ensure_ascii=False).casefold()]


def page(events, offset=0, limit=20, full=False):
    require(offset >= 0 and 1 <= limit <= 100, 'offset >= 0 and limit 1..100 required')
    items = events[offset:offset + limit]
    if not full:
        fields = ('id', 'type', 'issue_id', 'status', 'goal', 'remaining', 'blocker', 'recheck',
                  'targets', 'task_id', 'effect', 'evidence', 'submissions')
        items = [{k: (v[:240] + '…' if isinstance(v, str) and len(v) > 240 else v)
                  for k, v in e.items() if k in fields} for e in items]
    next_offset = offset + limit if offset + limit < len(events) else None
    return {'total': len(events), 'offset': offset, 'next_offset': next_offset, 'items': items}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('validate', 'pending', 'history', 'append'):
        cmd = sub.add_parser(name)
        cmd.add_argument('--ledger', default=str(home() / 'curate/events.jsonl'))
        if name == 'append':
            cmd.add_argument('--event', required=True)
        elif name in ('pending', 'history'):
            cmd.add_argument('--scope-kind', choices=('project', 'user'), required=True)
            cmd.add_argument('--root', required=True)
            cmd.add_argument('--offset', type=int, default=0)
            cmd.add_argument('--limit', type=int, default=20)
            cmd.add_argument('--full', action='store_true')
            if name == 'history':
                cmd.add_argument('--query', default='')
    args = parser.parse_args()
    try:
        if args.command == 'append':
            result = append(args.ledger, parse(Path(args.event).read_text(encoding='utf-8')))
        else:
            events = read(args.ledger)
            if args.command == 'validate':
                result = {'valid': True, 'events': len(events), 'ledger': str(Path(args.ledger).absolute())}
            else:
                require(absolute(args.root), 'use a normalized absolute root')
                scope = {'kind': args.scope_kind, 'root': args.root}
                result = page(select(events, scope, args.command == 'pending', getattr(args, 'query', '')),
                              args.offset, args.limit, args.full)
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, TypeError, KeyError) as err:
        print(json.dumps({'error': str(err)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
