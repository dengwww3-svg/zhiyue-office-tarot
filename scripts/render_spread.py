#!/usr/bin/env python3
"""Render fixed RWS assets into a static spread; requires Pillow only for images."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from tarot_session import CARDS, ROOT, outside, validate


def supports_text(font, text):
    """Detect missing glyphs through Pillow, without a fontTools runtime dependency."""
    def signature(char):
        mask=font.getmask(char)
        return mask.size,bytes(mask)
    missing=signature('\U0010ffff')
    return all(char.isspace() or signature(char)!=missing for char in set(text))


def arrangement(layout,n):
    if layout=='single' and n==1:return [(1,0)],3,1
    if layout=='triangle' and n==3:return [(1,0),(0,1),(2,1)],3,2
    if layout=='choice' and n==5:return [(1,0),(0,1),(0,2),(2,1),(2,2)],3,3
    if layout=='celtic' and n==10:
        # Challenge sits beside the centre to keep both images and directions legible.
        return [(1,2),(2,2),(1,3),(0,2),(1,0),(3,2),(4,3),(4,2),(4,1),(4,0)],5,4
    cols=3 if n>=6 else min(3,n)
    return [(i%cols,i//cols) for i in range(n)],cols,(n+cols-1)//cols


def render(s,output,only='all',font_path=None):
    from PIL import Image,ImageDraw,ImageFont
    validate(s)
    # Translate legacy display names without mutating the saved reading or deck.
    records=[dict(r,card=CARDS[r['card_id']]['name']) for r in s['drawn']]
    if only=='initial':records=[x for x in records if x['kind']=='initial']
    elif only=='supplements':records=[x for x in records if x['kind']=='supplement']
    if not records:raise ValueError('No revealed cards to render')
    layout=s['layout'] if only!='supplements' else 'grid'
    initial=[x for x in records if x['kind']=='initial']
    extra=[x for x in records if x['kind']=='supplement']
    coords,cols,rows=arrangement(layout,len(initial)) if initial else ([],3,0)
    if extra:
        cols=max(cols,min(3,len(extra)))
        coords += [(i%3,rows+i//3) for i in range(len(extra))]
        rows+=(len(extra)+2)//3
    cw,ch=240,400
    gap,margin,header,footer=22,30,130 if layout=='celtic' else 100,44
    blockw,blockh=cw+gap,ch+110
    canvas=Image.new('RGB',(margin*2+cols*blockw-gap,header+rows*blockh+footer),'#f6f2fa')
    d=ImageDraw.Draw(canvas)
    bundled=ROOT/'assets/fonts/ZhiyueTarotLabels.otf'
    candidates=[Path(font_path)] if font_path else [bundled,Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
    fp=next((x for x in candidates if x.is_file()),None)
    font=ImageFont.truetype(str(fp),19) if fp else ImageFont.load_default()
    small=ImageFont.truetype(str(fp),16) if fp else ImageFont.load_default()
    # Check custom positions as well: the bundled subset cannot contain every name.
    required='知月塔罗 · 韦特牌阵交叉挑战牌并排展示，以保留图像与方向补充原牌…'
    required+=''.join(r['position']+r['card']+r['orientation'] for r in records)
    cjk=bool(fp and supports_text(font,required))
    d.text((margin,20),'知月塔罗 · 韦特牌阵' if cjk else 'Zhiyue Tarot | Rider-Waite-Smith',font=font,fill='#40334b')
    note='交叉挑战牌并排展示，以保留图像与方向' if cjk else 'Celtic cross: challenge placed alongside for legibility'
    if layout=='celtic':d.text((margin,53),note,font=small,fill='#675973')
    for r,(col,row) in zip(records,coords):
        c=CARDS[r['card_id']]
        f=ROOT/'assets'/c['image']
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest()!=c.get('sha256'):
            raise ValueError('Missing or changed standard card asset: '+c['id'])
        with Image.open(f) as src:
            im=src.convert('RGB')
        if r['orientation']=='逆位':im=im.transpose(Image.Transpose.ROTATE_180)
        im.thumbnail((cw,ch),Image.Resampling.LANCZOS)
        x,y=margin+col*blockw,header+row*blockh
        caption=f"{r['draw_id']}. {r['position']}" if cjk else f"{r['draw_id']}. "+('Supplement' if r['kind']=='supplement' else 'Position '+str(r['draw_id']))
        # Wrap long labels by measured width; do not clip user-defined positions.
        lines=['']
        for char in caption:
            if d.textlength(lines[-1]+char,font=small)>cw:lines.append(char)
            else:lines[-1]+=char
        if len(lines)>2:lines=[lines[0],lines[1][:-1]+'…']
        for j,line in enumerate(lines):d.text((x,y-45+j*21),line,font=small,fill='#40334b')
        canvas.paste(im,(x+(cw-im.width)//2,y))
        title=(r['card']+' · '+r['orientation']) if cjk else c['english']+' | '+('R' if r['orientation']=='逆位' else 'U')
        title_lines=['']
        for char in title:
            if d.textlength(title_lines[-1]+char,font=font)>cw:title_lines.append(char)
            else:title_lines[-1]+=char
        for j,line in enumerate(title_lines[:2]):d.text((x,y+ch+12+j*24),line,font=font,fill='#40334b')
        if r.get('parent_draw_id'):
            label=f"补充原牌 {r['parent_draw_id']}" if cjk else f"Clarifies card {r['parent_draw_id']}"
            d.text((x,y+ch+63),label,font=small,fill='#675973')
    d.text((margin,canvas.height-30),'RWS 1909 · Pamela Colman Smith / A. E. Waite',font=small,fill='#675973')
    output=outside(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(output,format='PNG')
    return dict(output=str(output),card_count=len(records),layout=layout,
                label_language='zh' if cjk else 'ordinal_english',
                caption_table=[{k:r[k] for k in ('draw_id','position','card','orientation','parent_draw_id')} for r in records])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state',required=True);p.add_argument('--output',required=True)
    p.add_argument('--only',choices=('all','initial','supplements'),default='all');p.add_argument('--font')
    a=p.parse_args()
    try:
        s=json.loads(outside(a.state).read_text(encoding='utf-8'))
        result=render(s,a.output,a.only,a.font)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,KeyError,TypeError,OSError,ImportError) as e:
        p.exit(2,json.dumps({'error':str(e)},ensure_ascii=False)+'\n')


if __name__=='__main__':main()
