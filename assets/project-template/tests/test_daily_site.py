import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import daily_site as site
from render_issue import render_issue


class DailyUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.assets = self.root / 'source'
        (self.assets / 'vendor').mkdir(parents=True)
        (self.assets / 'vendor/alpine.min.js').write_text('// local test runtime')
        self.output = self.root / 'site'

    def tearDown(self):
        self.tmp.cleanup()

    def issue(self, day='2026-10-13', title='真实测试资讯'):
        return {'schema_version':1, 'date':day,
                'product':{'featured':[], 'personal':[], 'quick':[{'title':title,'label':'功能更新','core':'只用于临时目录中的工作流验证。','url':'https://example.org/source'}], 'unselected':[]},
                'builders':[], 'podcast':None, 'source_note':'隔离测试数据'}

    def publish(self, issue, **kwargs):
        return site.publish(issue, self.output, self.assets, **kwargs)

    def test_idempotent_and_explicit_replace(self):
        first=self.publish(self.issue())
        self.assertEqual(self.publish(self.issue())['status'],'unchanged')
        changed=self.issue(title='同一期修订')
        with self.assertRaises(site.ValidationError):self.publish(changed)
        self.assertEqual(site.status(self.output)['release'],first['release'])
        second=self.publish(changed,replace=True)
        self.assertNotEqual(first['release'],second['release'])
        self.assertTrue((self.output/'releases'/first['release']/'index.html').exists())

    def test_old_import_does_not_replace_latest_and_navigation_is_real(self):
        self.publish(self.issue('2026-10-20'))
        self.publish(self.issue('2026-09-30'))
        state=site.status(self.output)
        self.assertEqual(state['latest'],'2026-10-20')
        html=(self.output/'current/index.html').read_text()
        self.assertIn("issues/2026-09-30.html",html)
        self.assertIn('2026 年 9 月',html)
        self.assertIn('2026年10月20日',html)
        self.assertNotIn("emptyDay=",html)
        archive=(self.output/'current/issues/2026-09-30.html').read_text()
        self.assertIn("2026-10-20.html",archive)
        self.assertIn('../vendor/alpine.min.js',archive)

    def test_bad_input_and_render_failure_leave_current(self):
        first=self.publish(self.issue())
        bad=self.issue('2026-10-20');bad['product']['quick'][0]['url']='javascript:alert(1)'
        with self.assertRaises(site.ValidationError):self.publish(bad)
        with patch.object(site,'load_renderer',return_value=lambda *a,**kw: (_ for _ in ()).throw(RuntimeError('forced render failure'))):
            with self.assertRaises(RuntimeError):self.publish(self.issue('2026-10-20'))
        self.assertEqual(site.status(self.output)['release'],first['release'])
        self.assertFalse(list((self.output/'releases').glob('.staging-*')))

    def test_missing_asset_and_empty_issue_rejected(self):
        issue=self.issue();issue['product']['featured']=[{'title':'图文资讯','label':'产品发现','url':'https://example.org/a','core':'事实','display':{'points':[['','事实']], 'judgment':'判断'},'image':{'path':'assets/no.png','width':1,'height':1,'caption':'','kind':''}}]
        with self.assertRaises(site.ValidationError):self.publish(issue)
        empty=self.issue();empty['product']['quick']=[]
        with self.assertRaises(site.ValidationError):self.publish(empty)
        self.assertFalse((self.output/'current').exists())

    def test_preview_does_not_commit_and_rollback_keeps_history(self):
        a=self.publish(self.issue())
        candidate=self.publish(self.issue('2026-10-20'),preview_root=self.root/'previews')
        self.assertEqual(candidate['status'],'preview')
        self.assertTrue((Path(candidate['preview_path'])/'issues/2026-10-13.html').exists())
        self.assertEqual(site.status(self.output)['release'],a['release'])
        b=self.publish(self.issue('2026-10-20'))
        site.rollback('2026-10-13',self.output)
        self.assertEqual(site.status(self.output)['latest'],'2026-10-13')
        site.rollback(None,self.output,release_id=b['release'])
        self.assertEqual(site.status(self.output)['latest'],'2026-10-20')

    def test_unknown_time_avatar_and_no_image_render_without_false_info(self):
        issue=self.issue();issue['builders']=[{'author':'真实姓名','role':'','avatar':None,'one_sentence':'当天的一句话重点','paragraphs':['完整观点。'],'links':[{'text':'原文','url':'https://example.org/post'}],'publication':None}]
        site.validate_issue(issue,self.assets)
        html=render_issue(issue,[issue['date']])
        self.assertIn('avatar-placeholder',html)
        self.assertNotIn('Thibault',html)
        self.assertNotIn('class="identity-time"',html)
        self.assertNotIn('展开全文',html)

    def test_timezone_and_traversal_checks(self):
        bad=self.issue();bad['date']='2026-02-30'
        with self.assertRaises(site.ValidationError):site.validate_issue(bad,self.assets)
        with self.assertRaises(site.ValidationError):site.local_asset('assets/../private.png',self.assets,'image')
        with self.assertRaises(site.ValidationError):site.publication({'published_at':'2026-10-13T12:00:00'},site.issue_date('2026-10-13'),'date')
        with self.assertRaises(site.ValidationError):site.publication({'published_at':'2026-10-14T00:00:00+08:00'},site.issue_date('2026-10-13'),'date')

    def test_publish_lock_and_missing_vendor(self):
        with site.site_lock(self.output):
            with self.assertRaises(site.ValidationError):self.publish(self.issue())
        (self.assets/'vendor/alpine.min.js').unlink()
        with self.assertRaises(site.ValidationError):self.publish(self.issue())
        self.assertFalse((self.output/'current').exists())

    def test_duplicate_categories_rejected(self):
        issue=self.issue();issue['product']['unselected']=copy.deepcopy(issue['product']['quick'])
        with self.assertRaises(site.ValidationError):self.publish(issue)

    def test_dated_assets_preserve_history_even_if_source_filename_reused(self):
        images=self.assets/'assets';images.mkdir()
        path=images/'avatar.svg'
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"><rect width="2" height="2" fill="red"/></svg>')
        def with_avatar(day):
            issue=self.issue(day);issue['builders']=[{'author':'A','role':'','avatar':'assets/avatar.svg','publication':None,'one_sentence':'观点','paragraphs':['完整段落。'],'links':[{'text':'来源','url':'https://example.org/post'}]}]
            return issue
        self.publish(with_avatar('2026-10-13'))
        original=(self.output/'current/assets/2026-10-13/avatar.svg').read_bytes()
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"><rect width="2" height="2" fill="blue"/></svg>')
        self.publish(with_avatar('2026-10-20'))
        self.assertEqual((self.output/'current/assets/2026-10-13/avatar.svg').read_bytes(),original)
        self.assertNotEqual((self.output/'current/assets/2026-10-20/avatar.svg').read_bytes(),original)



if __name__=='__main__':unittest.main()
