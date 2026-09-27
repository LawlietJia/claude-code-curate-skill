#!/usr/bin/env python3
"""Small local checks for Claude Code curate. No semantic edits or external calls."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


def digest(data):
    return hashlib.sha256(data).hexdigest()


def issue(kind, file='', line=0, target='', severity='error'):
    return dict(type=kind, file=file, line=line, target=target, severity=severity)


def absolute(path):
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def reject_symlinks(path):
    p = absolute(path)
    for item in [p, *p.parents]:
        if item.is_symlink():
            raise ValueError('Refusing symlink path: ' + str(item))
    return p


def visible_markdown(text, manual):
    """Blank examples while retaining line positions. Not a full Markdown renderer."""
    text = re.sub(r'<!--[\s\S]*?-->', lambda m: '\n'*m[0].count('\n'), text)
    out, fence = [], None
    for number, line in enumerate(text.split('\n'), 1):
        m = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if fence:
            if m and m[1][0] == fence[0] and len(m[1]) >= len(fence):
                fence = None
            out.append('')
        elif m:
            fence = m[1]; out.append('')
        elif line.startswith(('    ', '\t')):
            # Indentation can be code OR a nested list; don't silently certify it.
            if '[' in line or re.search(r'<a\s|<img\s', line, re.I): manual.append(number)
            out.append('')
        else:
            out.append(line)
    # Match equal-length backtick spans, including multiline examples.
    s = '\n'.join(out)
    return re.sub(r'(?<!`)(`+)(?!`)([\s\S]*?)(?<!`)\1(?!`)',
                  lambda m: '\n'*m[0].count('\n'), s)


def destination(text, start=0, inline=False):
    """Read a destination; inline links require a valid title/outer terminator."""
    i = start
    while i < len(text) and text[i].isspace(): i += 1
    if i >= len(text): return None
    if text[i] == '<':
        end = text.find('>', i+1)
        if end == -1 or '<' in text[i+1:end]: return None
        value, i = text[i+1:end], end+1
    else:
        chars, depth = [], 0
        while i < len(text):
            c = text[i]
            if c == '\\' and i+1 < len(text):
                chars.append(text[i+1]); i += 2; continue
            if c == '<': return None
            if c == '(':
                depth += 1
            elif c == ')':
                if depth == 0: break
                depth -= 1
            elif c.isspace():
                if depth: return None
                break
            chars.append(c); i += 1
        if depth: return None
        value = ''.join(chars)
    if not inline: return value
    rest = text[i:]
    if rest.startswith(')'): return value
    if not rest or not rest[0].isspace(): return None
    rest = rest.lstrip()
    if rest.startswith(')'): return value
    # Optional CommonMark title followed by the outer closing parenthesis.
    title = r'''^(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\((?:\\.|[^()\\])*\))\s*\)'''
    return value if re.match(title, rest) else None


def links(text):
    definitions, found, manual = {}, [], []
    clean = visible_markdown(text, manual)
    for number, line in enumerate(clean.split('\n'), 1):
        m = re.match(r'^ {0,3}\[([^\]]+)\]:\s*(.*)', line)
        if m:
            definitions[' '.join(m[1].lower().split())] = destination(m[2])
    for number, line in enumerate(clean.split('\n'), 1):
        if re.match(r'^ {0,3}\[[^\]]+\]:', line): continue
        if '[[' in line: manual.append(number)
        # Handle ordinary inline and reference Markdown links, including images.
        for m in re.finditer(r'(?<!\\)\[([^\]\n]*)\]', line):
            label, tail = m[1], line[m.end():]
            target = None
            if tail.startswith('('):
                target = destination(tail, 1, inline=True)
                if target is None: manual.append(number)
            elif tail.startswith('['):
                ref = re.match(r'^\[([^\]]*)\]', tail)
                if ref:
                    key = ' '.join((ref[1] or label).lower().split())
                    target = definitions.get(key)
                    if target is None: manual.append(number)
            elif ' '.join(label.lower().split()) in definitions:
                target = definitions[' '.join(label.lower().split())]
            if target is not None: found.append((number, target))
        if re.search(r'<a\s|<img\s', line, re.I): manual.append(number)
    return list(dict.fromkeys(found)), sorted(set(manual))


def inventory(root):
    root = absolute(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Memory must be an existing non-symlink directory: '+str(root))
    root = root.resolve()
    files, bodies, issues = {}, {}, []
    def walk_error(error):
        raise error
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
        for name in list(dirs):
            p=Path(directory)/name
            if p.is_symlink():
                issues.append(issue('symlink',str(p.relative_to(root))))
                dirs.remove(name)
            elif name == '.git': dirs.remove(name)
        for name in sorted(names):
            if not name.lower().endswith('.md'): continue
            p=Path(directory)/name; rel=str(p.relative_to(root))
            if p.is_symlink():
                issues.append(issue('symlink',rel)); continue
            data=p.read_bytes()
            files[rel]=digest(data)
            bodies[rel]=data.decode('utf-8')
    return root, dict(sorted(files.items())), bodies, issues


def inspect(args):
    root, files, bodies, issues = inventory(args.memory)
    for rel, body in bodies.items():
        extracted, manual = links(body)
        issues.extend(issue('manual_link_review',rel,n,severity='warning') for n in manual)
        for number, target in extracted:
            parsed=urlsplit(target)
            if parsed.scheme or parsed.netloc or target.startswith('#'): continue
            raw=unquote(parsed.path)
            if not raw: continue
            p=Path(os.path.expanduser(raw))
            dest=p if p.is_absolute() else root/Path(rel).parent/p
            if not dest.exists(): issues.append(issue('broken_link',rel,number,target))
    metrics = None
    if 'MEMORY.md' not in bodies:
        issues.append(issue('missing_index','MEMORY.md'))
    else:
        text=bodies['MEMORY.md'].strip()
        lines=text.count('\n')+1 if text else 0
        units=len(text.encode('utf-16-le'))//2
        byte_count=len(text.encode('utf-8'))
        known=args.claude_version=='2.1.269'
        metrics=dict(lines=lines,utf16_units=units,utf8_bytes=byte_count,
                     version=args.claude_version,exact_model_verified=known,
                     would_truncate=(lines>200 or units>25000) if known else None)
        if known and metrics['would_truncate']:
            issues.append(issue('index_load_limit','MEMORY.md'))
        if byte_count>25000 or lines>150:
            issues.append(issue('index_soft_budget','MEMORY.md',severity='warning'))
        if not known:
            issues.append(issue('runtime_limit_unverified','MEMORY.md',severity='warning'))
    if args.snapshot:
        path=reject_symlinks(args.snapshot)
        if path == root or root in path.parents:
            raise ValueError('Snapshot must be outside memory directory')
        snapshot=dict(schema_version=1,memory=str(root),files=files,
                      created_at=dt.datetime.now(dt.timezone.utc).isoformat())
        with path.open('x',encoding='utf-8') as f:
            json.dump(snapshot,f,ensure_ascii=False,indent=2); f.write('\n')
    return dict(ok=not any(i['severity']=='error' for i in issues),
                memory=str(root),project=str(Path(args.project).resolve()) if args.project else None,
                coverage='All Markdown under the supplied memory root; no semantic or arbitrary project-wide link audit.',
                files=[dict(path=p,sha256=h) for p,h in files.items()],index=metrics,issues=issues)


def guard(args):
    snapshot=json.loads(Path(args.snapshot).read_text())
    if snapshot.get('schema_version')!=1 or not isinstance(snapshot.get('files'),dict):
        raise ValueError('Invalid snapshot')
    expected=reject_symlinks(snapshot['memory'])
    root, current, _, issues=inventory(expected)
    if str(root)!=snapshot['memory']: raise ValueError('Snapshot memory root identity changed')
    old=snapshot['files']
    changed=sorted(p for p in old.keys()|current.keys() if old.get(p)!=current.get(p))
    return dict(ok=not changed and not issues,changed=changed,issues=issues,
                note='Optimistic pre-write check only; use exact-content edits and recheck immediately before each change.')


ACTIONS={'create','merge','dedup','archive','delete','promote','verify','no-op','skip','retire-audit','handoff','smart-review','feedback'}
REQUIRED={'schema_version','event_id','run_id','ts','project','mode','action','target','detail','verification'}
OPTIONAL={'pattern_key','source','feedback','reviewed_feedback'}
AREAS='user|project|workflow|tool|skill|hook|search|environment|knowledge'


def canonical_key(key):
    return bool(re.fullmatch(r'(?:'+AREAS+r')\.[a-z][a-z0-9]*(?:-[a-z0-9]+)*',key))


def validate_event(event):
    if not isinstance(event,dict): raise ValueError('Event must be an object')
    if REQUIRED-event.keys(): raise ValueError('Missing event fields: '+','.join(sorted(REQUIRED-event.keys())))
    if event.keys()-(REQUIRED|OPTIONAL): raise ValueError('Unknown event fields: '+','.join(sorted(event.keys()-(REQUIRED|OPTIONAL))))
    if type(event['schema_version']) is not int or event['schema_version']!=3:
        raise ValueError('Current ledger accepts only schema_version 3')
    for key in (REQUIRED-{'schema_version','target'}) | ({'pattern_key','source'} & event.keys()):
        if not isinstance(event[key],str) or not event[key].strip():
            raise ValueError(key+' must be a nonempty string')
    timestamp=dt.datetime.fromisoformat(event['ts'].replace('Z','+00:00'))
    if timestamp.tzinfo is None: raise ValueError('ts needs an explicit timezone')
    project=Path(event['project'])
    if not project.is_absolute() or str(project.resolve())!=event['project']:
        raise ValueError('project must be a canonical absolute path')
    if event['mode'] not in {'quick','deep'}: raise ValueError('Invalid mode')
    if event['action'] not in ACTIONS: raise ValueError('Invalid action')
    if not isinstance(event['target'],list) or not event['target'] or any(not isinstance(t,str) or not t.strip() for t in event['target']):
        raise ValueError('target must be a nonempty string array')
    feedback=event.get('feedback')
    if event['action']=='feedback':
        if not isinstance(feedback,dict) or set(feedback)!={'task_id','effect','evidence'}:
            raise ValueError('Feedback needs task_id, effect and evidence')
        if any(not isinstance(v,str) or not v.strip() for v in feedback.values()):
            raise ValueError('Feedback fields must be nonempty strings')
        if feedback['effect'] not in {'helped','failed','exception','corrected'} or len(event['target'])!=1:
            raise ValueError('Feedback needs one concrete target and an actual-use/correction effect')
    elif 'feedback' in event: raise ValueError('feedback object requires feedback action')
    if 'reviewed_feedback' in event:
        refs=event['reviewed_feedback']
        if event['action'] not in {'merge','dedup','promote','verify','archive','delete'}:
            raise ValueError('Only completed governance/review can consume feedback')
        if not isinstance(refs,list) or not refs or any(not isinstance(x,str) or not x.strip() for x in refs) or len(set(refs))!=len(refs):
            raise ValueError('reviewed_feedback must contain unique nonempty event IDs')


def read_events(body):
    events, identities = [], {}
    if body and not body.endswith('\n'): raise ValueError('Current ledger has an incomplete final line')
    for number,line in enumerate(body.split('\n'),1):
        if not line.strip(): continue
        try:
            event=json.loads(line);validate_event(event)
            if event['event_id'] in identities: raise ValueError('Duplicate event_id')
        except (ValueError,TypeError) as e:
            raise ValueError('Current ledger line '+str(number)+': '+str(e)) from e
        for ref in event.get('reviewed_feedback',[]):
            original=identities.get(ref)
            if not original or original['action']!='feedback' or original['project']!=event['project']:
                raise ValueError('reviewed_feedback must reference prior feedback in the same project')
            if not set(original['target']).issubset(event['target']):
                raise ValueError('Review must include the original feedback target')
        identities[event['event_id']]=event;events.append(event)
    return events,identities


def legacy_records(assets):
    """Read old rows as candidates, not as validated current events."""
    for name in ['curate-history.legacy.jsonl','curate-history.jsonl']:
        p=reject_symlinks(Path(assets)/name)
        if not p.exists(): continue
        for number,line in enumerate(p.read_text(encoding='utf-8').splitlines(),1):
            if not line.strip(): continue
            try:
                row=json.loads(line)
                if not isinstance(row,dict): raise ValueError('Not an object')
                yield name,number,row,None
            except ValueError as error: yield name,number,None,str(error)


def ledger_events(path):
    path=reject_symlinks(path)
    if not path.exists(): return []
    with path.open(encoding='utf-8') as file:
        fcntl.flock(file,fcntl.LOCK_SH)
        return read_events(file.read())[0]


def history(args):
    assets=reject_symlinks(args.assets)
    if not assets.is_dir(): raise ValueError('Assets directory does not exist')
    project=str(Path(args.project).resolve())
    terms=[x.casefold() for x in args.query if x.strip()]
    if not terms: raise ValueError('Use a nonempty related-topic query')
    matches,warnings=[],[]
    rows=list(legacy_records(assets))
    current=assets/'curate-events.v3.jsonl'
    for row in ledger_events(current): rows.append((current.name,row['event_id'],row,None))
    for name,position,row,error in rows:
        if error:
            warnings.append(dict(file=name,position=position,error=error));continue
        scope=row.get('project')
        if scope is not None and (not isinstance(scope,str) or not Path(scope).is_absolute() or str(Path(scope).resolve())!=scope):
            warnings.append(dict(file=name,position=position,error='Legacy project is not a canonical absolute identity; treated as unknown',original_project=scope))
            scope=None
        if scope is not None and scope!=project: continue
        if not any(term in json.dumps(row,ensure_ascii=False).casefold() for term in terms): continue
        preview=str(row.get('detail',row.get('summary','')))
        matches.append(dict(file=name,position=position,scope='project' if scope==project else 'unknown',
                            pattern_key=row.get('pattern_key'),action=row.get('action'),
                            preview=preview[:400],preview_truncated=len(preview)>400))
    page=matches[args.offset:args.offset+args.limit]
    end=args.offset+len(page)
    return dict(ok=True,matches=page,total=len(matches),truncated=end<len(matches),
                next_offset=end if end<len(matches) else None,warnings=warnings,
                note='Candidate evidence only. Unknown project remains unknown; read active knowledge separately. Old rows are not efficacy counts.')


def feedback(args):
    project=str(Path(args.project).resolve())
    rows=[x for x in ledger_events(args.ledger) if x['project']==project]
    reviewed={ref for row in rows for ref in row.get('reviewed_feedback',[])}
    facts=[x for x in rows if x['action']=='feedback' and (not args.target or x['target'][0]==args.target)]
    pending=[x for x in facts if x['event_id'] not in reviewed]
    pending.sort(key=lambda x:x['feedback']['effect']=='helped')
    grouped={}
    for row in facts:
        item=row['feedback']
        grouped.setdefault(row['target'][0],{}).setdefault(item['task_id'],set()).add(item['effect'])
    summary=[dict(target=target,task_count=len(tasks),
                  helped_tasks=sum(effects=={'helped'} for effects in tasks.values()),
                  review_tasks=sum(effects!={'helped'} for effects in tasks.values())) for target,tasks in sorted(grouped.items())]
    page=pending[args.offset:args.offset+args.limit];end=args.offset+len(page)
    return dict(ok=True,pending=page,pending_count=len(pending),summary=summary,
                truncated=end<len(pending),next_offset=end if end<len(pending) else None,
                note='Counts deduplicate project/target/task; conflicting effects are not success votes. Counts are recorded signals, not proof or an automatic ranking.')


def append(args):
    event=json.loads(Path(args.event).read_text());validate_event(event)
    if event['action'] in {'smart-review','retire-audit'}:
        raise ValueError('This action is read-only historical compatibility; create native governance events instead')
    path=reject_symlinks(args.ledger)
    if not path.parent.is_dir(): raise ValueError('Create the intended ledger directory explicitly first')
    fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+',encoding='utf-8') as file:
        fcntl.flock(file,fcntl.LOCK_EX)
        metadata=os.fstat(file.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink!=1:
            raise ValueError('Ledger must be a regular file with one link')
        body=file.read();_,identities=read_events(body)
        if event['event_id'] in identities:
            if identities[event['event_id']]!=event: raise ValueError('Conflicting event_id; ledger unchanged')
            return dict(ok=True,appended=False,event_id=event['event_id'])
        key=event.get('pattern_key')
        if key and not canonical_key(key):
            known={x.get('pattern_key') for x in identities.values()}
            known.update(row.get('pattern_key') for _,_,row,error in legacy_records(path.parent)
                         if not error and isinstance(row.get('pattern_key'),str))
            if key not in known: raise ValueError('New pattern_key must use controlled area.topic; only exact existing legacy keys may be reused')
        if event['action']=='feedback':
            for old in identities.values():
                if old['action']=='feedback' and all(old[k]==event[k] for k in ['project','target','feedback']):
                    return dict(ok=True,appended=False,event_id=old['event_id'],reason='Same task evidence already recorded')
        encoded=json.dumps(event,ensure_ascii=False,separators=(',',':'))+'\n'
        read_events(body+encoded)  # Validate references before any bytes are appended.
        file.seek(0,os.SEEK_END)
        file.write(encoded)
        file.flush();os.fsync(file.fileno())
        file.seek(0);_,confirmed=read_events(file.read())
        if confirmed.get(event['event_id'])!=event: raise ValueError('Append readback failed')
    return dict(ok=True,appended=True,event_id=event['event_id'])


def validate(args):
    p=reject_symlinks(args.ledger)
    with p.open(encoding='utf-8') as f:
        fcntl.flock(f,fcntl.LOCK_SH);events,_=read_events(f.read())
    return dict(ok=True,records=len(events),note='Structure only; not proof of correctness or future benefit.')


def skill(args):
    root=Path(args.root).resolve();main=root/'SKILL.md'
    body=main.read_text();errors=[]
    if not body.startswith('---\n') or '\n---\n' not in body[4:]:
        errors.append('Missing frontmatter')
    else:
        header=body.split('---',2)[1]
        if not re.search(r'^name: curate$',header,re.M): errors.append('Expected name curate')
        match=re.search(r'^description: (.+)$',header,re.M)
        if not match or len(match[1])>1024: errors.append('Description absent or >1024 characters')
    if len(body.split('\n'))>300: errors.append('Main skill exceeds declared 300-line design target')
    for rel in ['references/governance.md','references/audit.md','scripts/curate_check.py','evals/test_curate_check.py']:
        if not (root/rel).is_file(): errors.append('Missing '+rel)
    for p in [main,*sorted((root/'references').glob('*.md'))]:
        for number,target in links(p.read_text())[0]:
            if urlsplit(target).scheme or target.startswith('#'):continue
            if not (p.parent/unquote(target.split('#')[0])).exists(): errors.append(str(p.relative_to(root))+':'+str(number)+' missing '+target)
    return dict(ok=not errors,errors=errors,note='Packaging checks only; run scenario probes separately.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('inspect',help='Read-only Markdown inventory and link/index checks')
    p.add_argument('--memory',required=True);p.add_argument('--project');p.add_argument('--claude-version');p.add_argument('--snapshot')
    p=sub.add_parser('guard',help='Check file drift against an inspect snapshot');p.add_argument('--snapshot',required=True)
    p=sub.add_parser('append',help='Validate and idempotently append one current v3 event')
    p.add_argument('--ledger',required=True);p.add_argument('--event',required=True)
    p=sub.add_parser('validate',help='Validate only a current v3 ledger');p.add_argument('--ledger',required=True)
    p=sub.add_parser('skill',help='Check the skill package, not model behavior');p.add_argument('--root',required=True)
    p=sub.add_parser('history',help='Read scoped current and unknown-scope legacy topic candidates')
    p.add_argument('--assets',required=True);p.add_argument('--project',required=True)
    p.add_argument('--query',action='append',required=True)
    p.add_argument('--limit',type=int,default=10);p.add_argument('--offset',type=int,default=0)
    p=sub.add_parser('feedback',help='Read pending feedback and per-task recorded signals')
    p.add_argument('--ledger',required=True);p.add_argument('--project',required=True);p.add_argument('--target')
    p.add_argument('--limit',type=int,default=10);p.add_argument('--offset',type=int,default=0)
    args=parser.parse_args()
    if hasattr(args,'limit') and (not 1<=args.limit<=100 or args.offset<0): parser.error('limit must be 1..100 and offset nonnegative')
    try: result=globals()[args.command](args)
    except (OSError,ValueError,TypeError,KeyError,UnicodeError) as e: result=dict(ok=False,error=str(e))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['ok'] else 1


if __name__=='__main__': sys.exit(main())
