"""Offline launcher tests: native capture is always replaced by a fake."""
import contextlib
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('capture_launcher',ROOT/'scripts/capture_bolt_inventory.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def report(self,**changes):
        values=dict(code='capture.observed',object_count=2,type_counts=(('host',1),('peripheral',1)),status_counts=(('authorized',2),),sysfs_path='/sys/devices/private/fixture',calls=8,bytes_read=100)
        return SimpleNamespace(**(values|changes))
    def run_main(self,report=None,args=(),isolated=True,error=None):
        output=io.StringIO()
        with patch.object(launcher.sys,'flags',SimpleNamespace(isolated=isolated,no_site=isolated)),patch.object(launcher,'_capture_once',return_value=report or self.report(),side_effect=error) as capture,contextlib.redirect_stdout(output):
            code=launcher.main(list(args))
        return code,json.loads(output.getvalue()),capture.call_count,output.getvalue()
    def test_one_capture_hash_only_no_path_owner_or_permission(self):
        code,result,calls,raw=self.run_main()
        self.assertEqual(0,code);self.assertEqual(1,calls);self.assertLess(len(raw.encode()),4096)
        self.assertEqual(hashlib.sha256(b'/sys/devices/private/fixture').hexdigest(),result['advertised_path_sha256'])
        for private in ('/sys/','private',':1.42','attachment','grant','authorized_device'):
            self.assertNotIn(private,raw)
        self.assertEqual('advertised_only_not_binding',result['path_digest_scope'])
    def test_arguments_and_nonisolated_startup_do_not_capture(self):
        for args,isolated in ((['--property','Key'],True),([],False)):
            code,result,calls,_=self.run_main(args=args,isolated=isolated)
            self.assertEqual(2,code);self.assertEqual(0,calls);self.assertIsNone(result['advertised_path_sha256'])
    def test_failures_sanitized_and_no_retry(self):
        for error in (ImportError('secret /private/module'),OSError('private native error'),RuntimeError(':1.42 /sys/devices/private')):
            code,result,calls,raw=self.run_main(error=error)
            self.assertEqual(1,code);self.assertEqual(1,calls);self.assertEqual('capture.launcher_failed',result['code']);self.assertNotIn('private',raw)
    def test_unknown_owner_and_timeout_never_publish_digest(self):
        for status in ('capture.owner_changed','capture.timeout','capture.unavailable','capture.inventory_unresolved'):
            code,result,_,_=self.run_main(self.report(code=status,sysfs_path=None))
            self.assertEqual(1,code);self.assertIsNone(result['advertised_path_sha256'])
    def test_untrusted_report_fields_and_output_bounds_rejected(self):
        for change in (dict(code='private'*10000),dict(type_counts=(('private',1),)),dict(status_counts=(('secret',2),)),dict(calls=9),dict(bytes_read=65537),dict(object_count=True),dict(sysfs_path='/sys/devices/../secret'),dict(code='capture.owner_changed')):
            code,result,_,raw=self.run_main(self.report(**change))
            self.assertEqual(1,code);self.assertEqual('capture.launcher_failed',result['code']);self.assertLess(len(raw.encode()),4096)
    def test_environment_does_not_select_operation(self):
        with patch.dict('os.environ',{'PYTHONPATH':'/untrusted','BOLT_PROPERTY':'Key','REGEAR_CAPTURE_COMMAND':'private'}):
            code,result,calls,_=self.run_main()
        self.assertEqual(0,code);self.assertEqual(1,calls);self.assertEqual('capture.observed',result['code'])
    def test_isolated_loader_constructs_exactly_one_runner_and_capture(self):
        child=r'''
import builtins,importlib.util,json,pathlib,sys,types
script=pathlib.Path(sys.argv[1]);root=script.parents[1]
spec=importlib.util.spec_from_file_location('fixed_launcher',script)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
calls=[]
class Runner:
 def __init__(self):calls.append('runner')
def capture(r):
 assert type(r) is Runner
 calls.append('capture');return 'fake-only'
fake=types.SimpleNamespace(commands=types.SimpleNamespace(__file__=str(root/'backend/regear/adapters/steamos/commands.py'),BoltInventoryCaptureCommandRunner=Runner),bolt_inventory_capture=types.SimpleNamespace(__file__=str(root/'backend/regear/adapters/steamos/bolt_inventory_capture.py'),capture_inventory=capture))
original=builtins.__import__
def intercepted(name,*a,**k):
 if name=='regear.adapters.steamos':return fake
 return original(name,*a,**k)
builtins.__import__=intercepted
assert m._capture_once()=='fake-only'
assert calls==['runner','capture']
print(json.dumps(calls))
'''
        r=subprocess.run([sys.executable,'-I','-S','-B','-c',child,str(ROOT/'scripts/capture_bolt_inventory.py')],capture_output=True,text=True,timeout=10)
        self.assertEqual(0,r.returncode,r.stderr);self.assertEqual(['runner','capture'],json.loads(r.stdout))
    def test_actual_launcher_rejects_arguments_before_importing_backend(self):
        r=subprocess.run([sys.executable,'-I','-S','-B',str(ROOT/'scripts/capture_bolt_inventory.py'),'--unsupported'],capture_output=True,text=True,timeout=10)
        self.assertEqual(2,r.returncode);self.assertEqual('capture.launcher_rejected',json.loads(r.stdout)['code']);self.assertEqual('',r.stderr)


if __name__=='__main__':unittest.main()
