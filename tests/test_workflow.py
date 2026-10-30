"""Run with python3 -m unittest discover -s tests -v. Test data stays in temp dirs."""
from copy import deepcopy
from datetime import date
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import tarot_session as t
import calendar_context as cal


class SessionTests(unittest.TestCase):
    def session(self,n=3,**kw):return t.new_session('测试问题，未来三个月',[f'牌位{i}' for i in range(1,n+1)],**kw)
    def test_deck_is_complete(self):
        self.assertEqual(len(t.CARDS),78)
        self.assertEqual(len({c['name'] for c in t.CATALOG}),78)
        for _ in range(20):
            s=self.session();t.validate(s)
            self.assertEqual(len({x['id'] for x in s['deck']}),78)
            self.assertTrue(all(x['orientation'] in t.ORIENTATIONS for x in s['deck']))
    def test_no_card_revealed_at_start(self):
        p=t.public(self.session(mode='numbers'))
        self.assertEqual(p['status'],'shuffled');self.assertEqual(p['cards'],[])
        self.assertNotIn('deck',p);self.assertNotIn('nonce',p)
    def test_numeric_order_is_position_order(self):
        s=self.session(mode='numbers');deck=deepcopy(s['deck']);t.draw_initial(s,[78,1,42])
        self.assertEqual([x['number'] for x in s['drawn']],[78,1,42])
        self.assertEqual([x['card_id'] for x in s['drawn']],[deck[n-1]['id'] for n in [78,1,42]])
        self.assertEqual(s['deck'],deck)
    def test_bad_numbers_do_not_mutate(self):
        for nums in ([0,2,3],[1,2,79],[1,1,3],[1,2],[1,2,3,4],[True,2,3],[1,2,2.5]):
            with self.subTest(nums=nums):
                s=self.session(mode='numbers');old=deepcopy(s)
                with self.assertRaises(ValueError):t.draw_initial(s,nums)
                self.assertEqual(s,old)
    def test_numeric_auto_switch_is_explicit(self):
        s=self.session(mode='numbers');old=deepcopy(s)
        with self.assertRaises(ValueError):t.draw_initial(s)
        self.assertEqual(s,old);t.draw_initial(s,automatic=True)
        self.assertEqual(s['deck'],old['deck'])
    def test_cannot_mix_auto_and_numbers(self):
        s=self.session()
        with self.assertRaises(ValueError):t.draw_initial(s,[1,2,3],automatic=True)
    def test_no_second_initial_draw(self):
        s=self.session();t.draw_initial(s)
        with self.assertRaises(ValueError):t.draw_initial(s)
    def test_supplements_keep_original_cards(self):
        s=self.session();t.draw_initial(s);old=deepcopy(s['drawn']);deck=deepcopy(s['deck'])
        for _ in range(10):t.supplement(s,'我主动邀约会如何？',count=3,parent=2)
        self.assertEqual(s['drawn'][:3],old);self.assertEqual(s['deck'],deck)
        self.assertEqual(len({x['card_id'] for x in s['drawn']}),33)
        self.assertEqual(s['drawn'][-1]['parent_draw_id'],2)
    def test_supplement_before_initial_rejected(self):
        with self.assertRaises(ValueError):t.supplement(self.session(),'追问')
    def test_supplement_errors_preserve_state(self):
        for kw in ({'count':0},{'count':4},{'parent':9},{'numbers':[1]},{'question':' '}):
            s=self.session();t.draw_initial(s,[1,2,3]);old=deepcopy(s)
            params={'question':'追问'}|kw
            with self.assertRaises(ValueError):t.supplement(s,**params)
            self.assertEqual(s,old)
    def test_can_use_last_card_then_exhaustion_is_clear(self):
        s=self.session();t.draw_initial(s)
        for _ in range(25):t.supplement(s,'继续',count=3)
        self.assertEqual(t.public(s)['remaining_count'],0)
        with self.assertRaises(ValueError):t.supplement(s,'还要一张')
    def test_fixed_direction(self):
        s=self.session(upright_only=True);t.draw_initial(s);t.supplement(s,'追问')
        self.assertTrue(all(r['orientation']=='正位' for r in s['drawn']))
    def test_deck_and_metadata_corruption_rejected(self):
        for mutate in (lambda s:s['deck'].reverse(),lambda s:s['positions'].reverse(),lambda s:s.update(question='换个问题')):
            s=self.session();mutate(s)
            with self.assertRaises(ValueError):t.validate(s)
    def test_record_must_match_fixed_card(self):
        s=self.session();t.draw_initial(s);s['drawn'][0]['orientation']='逆位' if s['drawn'][0]['orientation']=='正位' else '正位'
        with self.assertRaises(ValueError):t.validate(s)
    def test_user_provided_cards_kept(self):
        s=self.session(provided=[('c02','正位'),('s02','正位'),('c08','逆位')])
        self.assertEqual(s['origin'],'provided')
        self.assertEqual([x['card_id'] for x in s['drawn']],['c02','s02','c08'])
        t.supplement(s,'追问',count=3)
        self.assertEqual(len({r['card_id'] for r in s['drawn']}),6)
    def test_invalid_external_cards_rejected(self):
        for pairs in ([('x99','正位')]*3,[('c02','正位')]*3,[('c02','侧位'),('s02','正位'),('c08','正位')]):
            with self.assertRaises(ValueError):self.session(provided=pairs)
    def test_invalid_spread(self):
        for args in [('', ['现况'], 'single'),('问题',[], 'row'),('问题',[' '],'single'),('问题',['a','b'],'choice')]:
            with self.assertRaises(ValueError):t.new_session(*args)
    def test_private_paths_only(self):
        with self.assertRaises(ValueError):t.outside(ROOT/'private.json')
    def test_cli_restart_and_atomic_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'session.json'
            def run(*args):return subprocess.run([sys.executable,str(ROOT/'scripts/tarot_session.py'),*args],capture_output=True,text=True)
            r=run('start','--state',str(f),'--question','测试','--positions','现况','阻碍','建议','--mode','numbers')
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertEqual(os.stat(f).st_mode&0o777,0o600)
            old=f.read_bytes();r=run('draw','--state',str(f),'--numbers','1','1','2')
            self.assertNotEqual(r.returncode,0);self.assertEqual(f.read_bytes(),old)
            self.assertEqual(run('draw','--state',str(f),'--numbers','78','2','6').returncode,0)
            p=json.loads(run('show','--state',str(f)).stdout)
            self.assertEqual(p['used_numbers'],[78,2,6]);self.assertNotIn('deck',p)
            old=f.read_bytes();self.assertNotEqual(run('start','--state',str(f),'--question','新题','--positions','a').returncode,0)
            self.assertEqual(f.read_bytes(),old)
    def test_concurrent_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'x.json'
            with t.lock(p):
                with self.assertRaises(ValueError):
                    with t.lock(p):pass
            self.assertFalse(p.with_suffix('.json.lock').exists())


class CalendarTests(unittest.TestCase):
    def test_valentine_is_also_makeup_day(self):
        r=cal.context(date(2026,2,14),'CN')
        self.assertTrue(r['official_makeup_workday'])
        self.assertTrue(any(x['event']=='情人节' for x in r['candidates']))
    def test_qixi_years(self):
        for day in [date(2026,8,19),date(2027,8,8)]:
            self.assertTrue(any(x['event']=='七夕' for x in cal.context(day,'CN')['candidates']))
        self.assertFalse(any(x['event']=='七夕' for x in cal.context(date(2027,8,19),'CN')['candidates']))
    def test_unknown_future_year_not_faked(self):
        self.assertTrue(cal.context(date(2028,8,1),'CN')['verification_needed'])
    def test_region_is_not_language(self):
        r=cal.context(date(2026,9,25),'HK')
        self.assertTrue(r['verification_needed'])
        self.assertFalse(any(x['mode']=='假期安排' for x in r['candidates']))
    def test_year_boundary(self):
        r=cal.context(date(2026,12,27),'CN')
        self.assertTrue(any('2027' in x for x in r['verification_needed']))
        self.assertTrue(any(x['mode']=='年末／新年' for x in r['candidates']))
    def test_old_holiday_not_recommended(self):
        self.assertFalse(any(x['event']=='国庆' for x in cal.context(date(2026,10,19),'CN')['candidates']))
    def test_leap_day_month_end(self):
        self.assertTrue(any(x['mode']=='月度整理' for x in cal.context(date(2028,2,29),'CN')['candidates']))


class AssetTests(unittest.TestCase):
    def test_legacy_traditional_names_keep_original_session(self):
        from render_spread import render
        s=t.new_session('旧版显示名称',['当前关系'],provided=[('c14','正位')])
        s['drawn'][0]['card']=t.CARDS['c14']['name_traditional']
        t.validate(s)
        old=deepcopy(s)
        with tempfile.TemporaryDirectory() as tmp:
            result=render(s,Path(tmp)/'legacy.png')
            self.assertEqual(result['caption_table'][0]['card'],'圣杯国王')
        self.assertEqual(s,old)
    def test_all_images_match_manifest(self):
        from PIL import Image
        self.assertEqual(len(list((ROOT/'assets/cards').glob('*.jpg'))),78)
        for c in t.CATALOG:
            f=ROOT/'assets'/c['image']
            with self.subTest(card=c['id']):
                self.assertEqual(hashlib.sha256(f.read_bytes()).hexdigest(),c['sha256'])
                with Image.open(f) as im:self.assertEqual(im.size,(c['width'],c['height']));im.verify()
    def test_standard_major_numbering_and_courts(self):
        self.assertEqual(t.CARDS['m08']['name'],'力量');self.assertEqual(t.CARDS['m11']['name'],'正义')
        self.assertEqual(t.CARDS['c11']['english'],'Page of Cups');self.assertEqual(t.CARDS['s14']['english'],'King of Swords')
    def test_every_layout_renders(self):
        from render_spread import render
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            for layout,n in [('single',1),('row',3),('triangle',3),('grid',5),('relationship',6),('choice',5),('grid',9),('celtic',10)]:
                with self.subTest(layout=layout,n=n):
                    s=t.new_session('排版测试',[f'牌位{i}' for i in range(n)],layout=layout)
                    t.draw_initial(s);t.supplement(s,'追问',parent=1)
                    f=Path(tmp)/(layout+str(n)+'.png')
                    result=render(s,f);self.assertEqual(result['card_count'],n+1)
                    with Image.open(f) as im:self.assertGreater(im.width,250);self.assertGreater(im.height,400)
                    self.assertEqual(render(s,f,only='supplements')['card_count'],1)
                    self.assertEqual(render(s,f,only='initial')['card_count'],n)
    def test_reversed_image_pixels_rotate_not_mirror(self):
        from render_spread import render
        from PIL import Image,ImageChops
        s=t.new_session('逆位测试',['现况'],layout='single',provided=[('m00','逆位')])
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'image.png';render(s,p)
            with Image.open(ROOT/'assets'/t.CARDS['m00']['image']) as src:
                expected=src.convert('RGB').transpose(Image.Transpose.ROTATE_180)
                expected.thumbnail((240,400),Image.Resampling.LANCZOS)
            with Image.open(p) as rendered:
                x=30+262+(240-expected.width)//2
                got=rendered.crop((x,100,x+expected.width,100+expected.height))
                self.assertIsNone(ImageChops.difference(expected,got).getbbox())
    def test_render_does_not_change_state(self):
        from render_spread import render
        s=t.new_session('测试',['现况']);t.draw_initial(s);old=deepcopy(s)
        with tempfile.TemporaryDirectory() as tmp:render(s,Path(tmp)/'x.png')
        self.assertEqual(s,old)
    def test_bundled_font_renders_standard_labels(self):
        from render_spread import render
        s=t.new_session('字体测试',['现况','阻碍','建议']);t.draw_initial(s)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(render(s,Path(tmp)/'x.png')['label_language'],'zh')
    def test_missing_glyph_uses_complete_caption_table(self):
        from render_spread import render
        label='自订牌位\U0010ffff'
        s=t.new_session('字体缺字测试',[label]);t.draw_initial(s)
        with tempfile.TemporaryDirectory() as tmp:
            result=render(s,Path(tmp)/'x.png')
            self.assertEqual(result['label_language'],'ordinal_english')
            self.assertEqual(result['caption_table'][0]['position'],label)


if __name__=='__main__':unittest.main()
