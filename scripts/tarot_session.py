#!/usr/bin/env python3
"""Portable fixed-deck tarot sessions. State files must stay outside the shared skill."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT/'assets/deck.json').read_text(encoding='utf-8'))['cards']
CARDS = {c['id']: c for c in CATALOG}
LAYOUTS = {'single', 'row', 'triangle', 'grid', 'relationship', 'choice', 'celtic'}
ORIENTATIONS = {'正位', '逆位'}


def commitment(deck, nonce):
    return hashlib.sha256(json.dumps([deck, nonce], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def new_session(question, positions, layout='row', mode='auto', upright_only=False, provided=None):
    if not isinstance(question, str) or not question.strip():
        raise ValueError('Question is required')
    if not 1 <= len(positions) <= 10 or any(not isinstance(p, str) or not p.strip() for p in positions):
        raise ValueError('Provide 1–10 non-empty position labels')
    if layout not in LAYOUTS or mode not in {'auto', 'numbers'}:
        raise ValueError('Invalid layout or selection mode')
    if layout == 'single' and len(positions) != 1 or layout == 'choice' and len(positions) != 5 or layout == 'celtic' and len(positions) != 10:
        raise ValueError('Layout and position count disagree')
    rng = secrets.SystemRandom()
    deck = [{'id': c['id'], 'orientation': '正位' if upright_only else rng.choice(('正位', '逆位'))} for c in CATALOG]
    rng.shuffle(deck)
    s = dict(schema=1, session_id=str(uuid.uuid4()), question=question.strip(),
             positions=positions, layout=layout, mode=mode, upright_only=upright_only,
             origin='provided' if provided else 'program_random',
             created_at=datetime.now(timezone.utc).isoformat(), deck=deck,
             nonce=secrets.token_hex(32), drawn=[])
    if provided:
        if len(provided) != len(positions) or len({x[0] for x in provided}) != len(provided):
            raise ValueError('Provided cards must match positions and be distinct')
        for cid, orientation in provided:
            if cid not in CARDS or orientation not in ORIENTATIONS or upright_only and orientation != '正位':
                raise ValueError('Invalid provided card or direction')
            next(x for x in deck if x['id'] == cid)['orientation'] = orientation
        nums = [next(i+1 for i,x in enumerate(deck) if x['id'] == cid) for cid,_ in provided]
        for number,label in zip(nums,positions):
            append_card(s, number, label, 'initial', question)
    s['commitment'] = commitment(deck,s['nonce'])
    s['spread_commitment'] = commitment({k:s[k] for k in ('question','positions','layout','upright_only','origin')},s['nonce'])
    return s


def validate(s):
    if not isinstance(s,dict) or s.get('schema') != 1:
        raise ValueError('Unsupported session state')
    deck=s.get('deck',[])
    if len(deck)!=78 or {x.get('id') for x in deck}!=set(CARDS) or any(x.get('orientation') not in ORIENTATIONS for x in deck):
        raise ValueError('Deck is incomplete or invalid')
    if s.get('commitment') != commitment(deck,s.get('nonce')):
        raise ValueError('Fixed deck changed; do not silently reshuffle')
    if s.get('spread_commitment') != commitment({k:s[k] for k in ('question','positions','layout','upright_only','origin')},s.get('nonce')):
        raise ValueError('Question or fixed spread changed; start a new session')
    positions=s.get('positions',[])
    if not 1<=len(positions)<=10 or s.get('layout') not in LAYOUTS or s.get('mode') not in {'auto','numbers'}:
        raise ValueError('Invalid spread metadata')
    drawn=s.get('drawn',[])
    if len({x['number'] for x in drawn})!=len(drawn):
        raise ValueError('Duplicate card in session')
    initial=[x for x in drawn if x['kind']=='initial']
    if initial and len(initial)!=len(positions):
        raise ValueError('Partial initial draw is invalid')
    for i,r in enumerate(drawn,1):
        n=r['number']
        if type(n) is not int or not 1<=n<=78 or r['draw_id']!=i:
            raise ValueError('Invalid card number or draw ID')
        d=deck[n-1]
        card=CARDS[d['id']]
        valid_names={card['name'],card.get('name_traditional',card['name'])}
        if r['card_id']!=d['id'] or r['orientation']!=d['orientation'] or r['card'] not in valid_names:
            raise ValueError('Draw record disagrees with fixed deck')
        if r['kind']=='initial':
            if i>len(positions) or r['position']!=positions[i-1]:
                raise ValueError('Initial positions changed')
        elif r['kind']=='supplement':
            if len(initial)!=len(positions) or not str(r.get('question','')).strip():
                raise ValueError('Supplement requires an initial reading and question')
            parent=r.get('parent_draw_id')
            if parent is not None and (type(parent) is not int or not 1<=parent<i):
                raise ValueError('Invalid supplement parent')
        else:
            raise ValueError('Invalid draw kind')
    if s.get('upright_only') and any(x['orientation']!='正位' for x in deck):
        raise ValueError('Direction rule changed')
    return s


def append_card(s, number, position, kind, question, parent=None):
    d=s['deck'][number-1]; c=CARDS[d['id']]
    s['drawn'].append(dict(draw_id=len(s['drawn'])+1,number=number,card_id=c['id'],
                           card=c['name'],english=c['english'],orientation=d['orientation'],
                           position=position,kind=kind,question=question,parent_draw_id=parent,
                           image=str(ROOT/'assets'/c['image'])))


def select(s, count, numbers=None):
    used={r['number'] for r in s['drawn']}
    available=[n for n in range(1,79) if n not in used]
    if type(count) is not int or not 1<=count<=len(available):
        raise ValueError('Not enough remaining cards or invalid count')
    if numbers is None:
        return secrets.SystemRandom().sample(available,count)
    if len(numbers)!=count or len(set(numbers))!=count:
        raise ValueError('Select the required count of distinct numbers')
    if any(type(n) is not int or n not in available for n in numbers):
        raise ValueError('Numbers must be unused integers from 1 through 78')
    return numbers


def draw_initial(s,numbers=None,automatic=False):
    validate(s)
    if s['drawn']:
        raise ValueError('Initial cards already drawn; use supplement or start a new question')
    if numbers is not None and automatic:
        raise ValueError('Choose automatic draw or numbers, not both')
    if s['mode']=='numbers' and numbers is None and not automatic:
        raise ValueError('This session awaits the user’s numbers; do not substitute an automatic draw')
    nums=select(s,len(s['positions']),numbers)
    for number,label in zip(nums,s['positions']):
        append_card(s,number,label,'initial',s['question'])
    return validate(s)


def supplement(s,question,count=1,numbers=None,parent=None):
    validate(s)
    if not s['drawn'] or not question.strip():
        raise ValueError('Supplement needs the original reading and a follow-up question')
    if not 1<=count<=3:
        raise ValueError('Draw 1–3 supplementary cards per explicit request')
    if parent is not None and (type(parent) is not int or not 1<=parent<=len(s['drawn'])):
        raise ValueError('Parent card does not exist')
    nums=select(s,count,numbers)
    for i,number in enumerate(nums,1):
        append_card(s,number,f'补牌 {i}', 'supplement',question.strip(),parent)
    return validate(s)


def public(s):
    validate(s)
    return {k:s[k] for k in ('session_id','question','positions','layout','mode','origin','created_at','commitment')} | {
        'status':'drawn' if s['drawn'] else 'shuffled', 'cards':s['drawn'],
        'remaining_count':78-len(s['drawn']), 'used_numbers':[x['number'] for x in s['drawn']]}


def outside(path):
    p=Path(path).expanduser().absolute()
    if p.is_symlink() or p.resolve().is_relative_to(ROOT):
        raise ValueError('Store private session/output files outside the shared skill; symlink state is unsupported')
    return p


@contextmanager
def lock(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    lp=path.with_suffix(path.suffix+'.lock')
    try:
        fd=os.open(lp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:
        raise ValueError('Another operation is using this session; retry after it completes')
    try:
        os.close(fd);yield
    finally:
        lp.unlink(missing_ok=True)


def save(path,s):
    validate(s)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.tarot-')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(s,f,ensure_ascii=False,indent=2)
        os.replace(tmp,path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    for name in ('start','draw','add','show'):
        c=sub.add_parser(name);c.add_argument('--state',required=True)
        if name=='start':
            c.add_argument('--question',required=True);c.add_argument('--positions',nargs='+',required=True)
            c.add_argument('--layout',choices=sorted(LAYOUTS),default='row')
            c.add_argument('--mode',choices=('auto','numbers'),default='auto');c.add_argument('--upright-only',action='store_true')
            c.add_argument('--provided',nargs='+',help='Verified card IDs with direction, e.g. m00:正位')
        if name in ('draw','add'):
            c.add_argument('--numbers',type=int,nargs='+')
            if name=='draw':c.add_argument('--auto',action='store_true',help='Explicit user switch to automatic without reshuffling')
        if name=='add':
            c.add_argument('--question',required=True);c.add_argument('--count',type=int,default=1);c.add_argument('--parent',type=int)
    args=p.parse_args()
    try:
        path=outside(args.state)
        with lock(path):
            if args.command=='start':
                if path.exists():raise ValueError('Session already exists; choose a fresh private state path')
                provided=[x.split(':',1) for x in args.provided] if args.provided else None
                if provided and any(len(x)!=2 for x in provided):raise ValueError('Use card_id:正位 or card_id:逆位')
                s=new_session(args.question,args.positions,args.layout,args.mode,args.upright_only,provided)
            else:
                s=validate(json.loads(path.read_text(encoding='utf-8')))
                if args.command=='draw':draw_initial(s,args.numbers,args.auto)
                elif args.command=='add':supplement(s,args.question,args.count,args.numbers,args.parent)
            if args.command!='show':save(path,s)
            print(json.dumps(public(s),ensure_ascii=False,indent=2))
    except (ValueError,KeyError,TypeError,AttributeError,OSError,json.JSONDecodeError) as e:
        p.exit(2,json.dumps({'error':str(e)},ensure_ascii=False)+'\n')


if __name__=='__main__':
    main()
