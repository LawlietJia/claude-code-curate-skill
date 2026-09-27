#!/usr/bin/env python3
"""Create one new isolated fixture; refuses an existing/symlink destination."""
import argparse
import json
import os
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__);p.add_argument('destination');a=p.parse_args()
root=Path(os.path.abspath(a.destination))
if any(x.is_symlink() for x in [root,*root.parents]): raise SystemExit('Use canonical non-symlink path')
root.mkdir(parents=True,exist_ok=False)
files=json.loads((Path(__file__).parent/'fixtures/knowledge.json').read_text())
for rel,text in files.items():
    target=root/rel
    if root not in target.resolve().parents: raise SystemExit('Fixture path escapes destination')
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
(root/'assets').mkdir()
(root/'assets/curate-history.jsonl').write_text(json.dumps(dict(pattern_key='tool:render:auth',detail='Earlier auth retry knowledge; project identity not recorded.'),ensure_ascii=False)+'\n')
print(json.dumps(dict(project=str(root),memory=str(root/'memory'),assets=str(root/'assets')),indent=2))
