import unittest
from unittest.mock import Mock,patch
from regear.delivery.usb4_native_diagnostic import read_usb4_native_diagnostic, unavailable
from regear.application.usb4_native_evidence import EvidenceReport
from regear.ports.usb4_native_evidence import Fact,NativeSnapshot

class DiagnosticTests(unittest.TestCase):
    def test_categories_only_no_private_identity_or_eligibility(self):
        collector=Mock(return_value=EvidenceReport('evidence.observed',NativeSnapshot(captured_at=10,api=Fact.OBSERVED)))
        result=read_usb4_native_diagnostic(collector=collector)
        self.assertEqual('observed',result['api']);self.assertEqual('unknown',result['static_permission'])
        self.assertEqual('observed',result['plugin_context']);self.assertFalse(result['hardware_write']);self.assertFalse(result['mutation_allowed'])
        self.assertNotIn('captured_at',result);self.assertNotIn('uid',result);self.assertNotIn('token',result)
    def test_import_or_reader_error_is_categorical_not_startup_failure(self):
        with patch('regear.delivery.usb4_native_diagnostic.create_reader',side_effect=ImportError('private path')):
            result=read_usb4_native_diagnostic()
        self.assertEqual('usb4_diagnostic.reader_unavailable',result['code']);self.assertNotIn('private',repr(result))
    def test_unavailable_never_constructs_reader(self):
        with patch('regear.delivery.usb4_native_diagnostic.create_reader') as factory:
            result=unavailable();factory.assert_not_called()
        self.assertFalse(result['available']);self.assertEqual('unknown',result['plugin_context'])
    def test_context_category_never_becomes_static_grant_permission(self):
        collector=Mock(return_value=EvidenceReport('evidence.observed',NativeSnapshot(captured_at=10)))
        for uid,expected in ((0,'root'),(1000,'nonroot'),(None,'unknown')):
            with patch('regear.delivery.usb4_native_diagnostic.os.geteuid',return_value=uid,create=True):
                result=read_usb4_native_diagnostic(collector=collector)
            self.assertEqual(expected,result['process_identity']);self.assertEqual('unknown',result['static_permission'])
    def test_concurrent_request_never_constructs_another_reader(self):
        from regear.delivery.usb4_native_diagnostic import _READ_LOCK
        with _READ_LOCK,patch('regear.delivery.usb4_native_diagnostic.create_reader') as factory:
            self.assertEqual('usb4_diagnostic.busy',read_usb4_native_diagnostic()['code']);factory.assert_not_called()

class ImportDiagnosticTests(unittest.TestCase):
    def test_missing_import_has_fixed_stage_category_and_no_factory(self):
        import importlib
        real=importlib.import_module
        def missing(name):
            if name=='regear.adapters.steamos.usb4_native_evidence':
                raise ModuleNotFoundError('/private/raw/path credential',name='xml.etree.ElementTree')
            return real(name)
        with patch('regear.delivery.usb4_native_diagnostic.create_reader') as factory,patch('importlib.import_module',side_effect=missing):
            result=read_usb4_native_diagnostic();factory.assert_not_called()
        row=next(x for x in result['imports'] if x['stage']=='reader')
        self.assertEqual({'stage':'reader','outcome':'failed','failure':'xml_runtime_unavailable'},row)
        self.assertNotIn('private',repr(result));self.assertNotIn('ElementTree',repr(result));self.assertNotIn('ModuleNotFoundError',repr(result))
    def test_missing_symbol_is_distinct_and_never_executes_factory(self):
        import importlib,types
        real=importlib.import_module
        def stale(name):
            return types.ModuleType(name) if name=='regear.adapters.steamos.commands' else real(name)
        with patch('regear.delivery.usb4_native_diagnostic.create_reader') as factory,patch('importlib.import_module',side_effect=stale):
            result=read_usb4_native_diagnostic();factory.assert_not_called()
        self.assertIn({'stage':'command_runner','outcome':'failed','failure':'symbol_unavailable'},result['imports'])
    def test_unclassified_import_name_and_exception_text_never_escape(self):
        with patch('regear.delivery.usb4_native_diagnostic.create_reader') as factory,patch('importlib.import_module',side_effect=ImportError('secret traceback',name='private.serial.identifier')):
            result=read_usb4_native_diagnostic();factory.assert_not_called()
        self.assertTrue(all(x['failure']=='dependency_unavailable' for x in result['imports'][1:]))
        self.assertNotIn('private',repr(result));self.assertNotIn('secret',repr(result))
    def test_successful_fixed_imports_continue_to_injected_collector(self):
        collector=Mock(return_value=EvidenceReport('evidence.observed',NativeSnapshot(captured_at=10)))
        result=read_usb4_native_diagnostic(collector=collector)
        self.assertEqual(6,len(result['imports']));self.assertTrue(all(x['outcome']=='ready' and x['failure']=='none' for x in result['imports']))
        collector.assert_called_once()

class PackagedRuntimeTests(unittest.TestCase):
    def test_isolated_packaged_runtime_imports_transport_and_xml_fail_closed(self):
        import json,subprocess,sys,tempfile,zipfile
        from pathlib import Path
        from scripts.build_plugin import included_files,archive_name,archive_bytes
        child=r'''
import importlib.abc,json,sys
from pathlib import Path
backend=Path(sys.argv[1]);sys.path.insert(0,str(backend));mode=sys.argv[2]
assert not any(p.endswith('/tests') or p.endswith('\\tests') for p in sys.path)
class MissingXml(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if mode=='xml_missing' and fullname=='xml.etree.ElementTree':
   raise ModuleNotFoundError('/private/path must never be public',name=fullname)
  if mode=='xml_family_missing' and (fullname=='xml' or fullname.startswith('xml.')):
   raise ModuleNotFoundError('/private/path must never be public',name=fullname)
  if mode=='expat_missing' and fullname in ('pyexpat','_elementtree','xml.parsers.expat'):
   raise ModuleNotFoundError('/private/path must never be public',name=fullname)
sys.meta_path.insert(0,MissingXml())
from regear.delivery import usb4_native_diagnostic as facade
from regear.adapters.steamos import commands
calls=[]
def read(self,argv):
 argv=commands.BoltNativeReadCommandRunner.validate(argv);calls.append(1)
 tail=argv[len(commands.BoltNativeReadCommandRunner.PREFIX):];member=tail[4]
 manager='<node><interface name="org.freedesktop.bolt1.Manager"><method name="ListDevices"><arg direction="out" type="ao"/></method></interface></node>'
 device='<node><interface name="org.freedesktop.bolt1.Device"><method name="Authorize"><arg direction="in" type="s"/></method><property name="Uid" type="s" access="read"/><property name="Status" type="s" access="read"/><property name="Stored" type="b" access="read"/></interface></node>'
 if mode=='malformed':manager='<node>'
 if mode=='entity':manager='<!DOCTYPE node [<!ENTITY x SYSTEM "file:///private">]>'+manager
 if member=='GetNameOwner':value={'type':'s','data':[':1.42']}
 elif member=='Introspect':value={'type':'s','data':[manager if tail[2]=='/org/freedesktop/bolt' else device]}
 elif member=='ListDevices':value={'type':'ao','data':[['/org/freedesktop/bolt/devices/a']]}
 else:
  signature,data={'Uid':('s','private-fixture'),'Status':('s','connected'),'Stored':('b',False)}[tail[-1]]
  value={'type':'v','data':[{'type':signature,'data':data}]}
 return commands.CommandResult(argv,0,json.dumps(value),'')
commands.BoltNativeReadCommandRunner.run=read
if mode=='stale_commands':del commands.BoltNativeReadCommandRunner
result=facade.read_usb4_native_diagnostic()
assert 'private' not in repr(result) and 'ElementTree' not in repr(result)
assert Path(facade.__file__).is_relative_to(backend)
assert all(Path(m.__file__).is_relative_to(backend) for n,m in tuple(sys.modules.items()) if n.startswith('regear.') and getattr(m,'__file__',None))
print(json.dumps(dict(result=result,calls=len(calls))))
'''
        with tempfile.TemporaryDirectory() as value:
            root=Path(value);archive=root/'runtime-source-fixture.zip'
            # Same packaging source selection; no reservation/player package and no tests.
            with zipfile.ZipFile(archive,'x') as z:
                for file in included_files():
                    if '/backend/' in file.as_posix() and file.suffix=='.py':
                        z.writestr(archive_name(file),archive_bytes(file,profile='development'))
            with zipfile.ZipFile(archive) as z:z.extractall(root/'runtime')
            for mode in ('valid','xml_missing','xml_family_missing','expat_missing','stale_commands','malformed','entity'):
                with self.subTest(mode=mode):
                    run=subprocess.run([sys.executable,'-I','-S','-B','-c',child,str(root/'runtime/Re-Gear/backend'),mode],cwd=root,capture_output=True,text=True,timeout=15)
                    self.assertEqual(0,run.returncode,run.stderr);output=json.loads(run.stdout);result=output['result']
                    self.assertFalse(result['hardware_write']);self.assertFalse(result['mutation_allowed']);self.assertEqual('unknown',result['static_permission'])
                    if mode in ('valid','xml_missing','xml_family_missing','expat_missing'):
                        self.assertEqual('evidence.observed',result['code']);self.assertEqual(8,output['calls'])
                        self.assertTrue(all(x['outcome']=='ready' for x in result['imports']))
                    elif mode=='stale_commands':
                        self.assertEqual('usb4_diagnostic.reader_unavailable',result['code']);self.assertEqual(0,output['calls'])
                        self.assertTrue(any(x['failure']=='symbol_unavailable' for x in result['imports']))
                    else:self.assertEqual('evidence.unsupported',result['code']);self.assertEqual(2,output['calls'])

if __name__=='__main__':unittest.main()
