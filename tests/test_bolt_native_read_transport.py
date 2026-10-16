import json
import unittest
import time
from unittest.mock import patch
from regear.adapters.steamos.commands import BoltNativeReadCommandRunner, CommandResult
from regear.adapters.steamos.bolt_native_read_transport import BoltNativeReadTransport
from regear.adapters.steamos.usb4_native_evidence import NativeRead
from regear.ports.usb4_native_evidence import ReadBudget

ROOT='/org/freedesktop/bolt';PATH=ROOT+'/devices/a';OWNER=':1.42'
class Runner:
    def __init__(self):self.calls=[];self.error='';self.bad=None
    def run(self,argv):
        argv=BoltNativeReadCommandRunner.validate(argv);self.calls.append(argv)
        member=argv[len(BoltNativeReadCommandRunner.PREFIX)+4]
        if member=='GetNameOwner':value={'type':'s','data':[OWNER]}
        elif member=='Introspect':value={'type':'s','data':['<node/>']}
        elif member=='ListDevices':value={'type':'ao','data':[[PATH]]}
        else:
            prop=argv[-1];v={'Uid':('s','private-uid'),'Status':('s','connected'),'Stored':('b',False)}[prop]
            value={'type':'v','data':[{'type':v[0],'data':v[1]}]}
        return CommandResult(argv,0,self.bad or json.dumps(value),'',self.error)

class TransportTests(unittest.TestCase):
    def setUp(self):self.runner=Runner();self.transport=BoltNativeReadTransport(self.runner,clock=lambda:10);self.budget=ReadBudget(13,65536,64)
    def test_only_fixed_nonactivating_reads_and_no_getall_keys(self):
        r=NativeRead(OWNER,PATH,'org.freedesktop.DBus.Properties','GetAll',('org.freedesktop.bolt1.Device',))
        result=json.loads(self.transport(r,self.budget));self.assertEqual(False,result['Stored'])
        self.assertEqual(['Uid','Status','Stored'],[a[-1] for a in self.runner.calls])
        for argv in self.runner.calls:
            self.assertIn('--auto-start=no',argv);self.assertIn('--allow-interactive-authorization=no',argv)
            self.assertNotIn('GetAll',argv);self.assertNotIn('Key',argv)
    def test_owner_and_inventory_envelopes(self):
        for request,expected in [(NativeRead('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetNameOwner',('org.freedesktop.bolt',)),OWNER),(NativeRead(OWNER,ROOT,'org.freedesktop.bolt1.Manager','ListDevices'),[PATH])]:
            self.assertEqual(expected,json.loads(self.transport(request,self.budget)))
    def test_forged_query_and_write_are_denied_before_runner(self):
        requests=[NativeRead(OWNER,PATH,'org.freedesktop.bolt1.Device','Authorize',('none',)),NativeRead('org.freedesktop.bolt',PATH,'org.freedesktop.DBus.Properties','GetAll',('org.freedesktop.bolt1.Device',)),NativeRead(OWNER,'/elsewhere','org.freedesktop.DBus.Introspectable','Introspect')]
        for r in requests:
            with self.assertRaises(ValueError):self.transport(r,self.budget)
        self.assertEqual([],self.runner.calls)
    def test_cli_rejects_write_and_arbitrary_property(self):
        base=BoltNativeReadCommandRunner.PREFIX
        for tail in [('call',OWNER,PATH,'org.freedesktop.bolt1.Device','Authorize','s','none'),('call',OWNER,PATH,'org.freedesktop.DBus.Properties','Get','ss','org.freedesktop.bolt1.Device','Key')]:
            with self.assertRaises(ValueError):BoltNativeReadCommandRunner.validate(base+tail)
        with patch('regear.adapters.steamos.commands.subprocess.Popen') as popen:
            with self.assertRaises(ValueError):BoltNativeReadCommandRunner().run(base+('call',OWNER,PATH,'x','Set'))
            popen.assert_not_called()
    def test_errors_bad_envelopes_bounds_and_expiry(self):
        q=NativeRead(OWNER,ROOT,'org.freedesktop.bolt1.Manager','ListDevices')
        for bad in ('bad','{"type":"ao","type":"ao","data":[[]]}','{"type":"s","data":["x"]}'):
            self.runner.bad=bad
            with self.assertRaises(ValueError):self.transport(q,self.budget)
        self.runner.bad=None;self.runner.error='inputplumber.timeout'
        with self.assertRaises(TimeoutError):self.transport(q,self.budget)
        self.runner.error='';self.runner.bad=' '*65537
        with self.assertRaises(ValueError):self.transport(q,self.budget)
        with self.assertRaises(TimeoutError):self.transport(q,ReadBudget(9,65536,64))

class ChildBoundaryTests(unittest.TestCase):
    """Real software children only; no system bus or device access."""
    def child(self,code,runner):
        from tests.test_inputplumber_read_commands import TransportRegression
        argv=BoltNativeReadCommandRunner.PREFIX+('call','org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetNameOwner','s','org.freedesktop.bolt')
        return TransportRegression.child(self,code,runner,argv)
    def test_bounded_success_and_cumulative_output_poison(self):
        runner=BoltNativeReadCommandRunner();runner._remaining_bytes=8
        self.assertTrue(self.child("print('1234')",runner).ok)
        result=self.child("print('1234')",runner)
        self.assertEqual('inputplumber.output_limit',result.error);self.assertEqual('',result.stdout)
        with patch('regear.adapters.steamos.commands.subprocess.Popen') as popen:
            self.assertFalse(runner.run(BoltNativeReadCommandRunner.PREFIX+('call','org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetNameOwner','s','org.freedesktop.bolt')).ok)
            popen.assert_not_called()
    def test_timeout_reaps_child_and_discards_output(self):
        runner=BoltNativeReadCommandRunner();runner._deadline=time.monotonic()+.15
        started=time.monotonic();result=self.child('import time;time.sleep(20)',runner)
        self.assertEqual('inputplumber.timeout',result.error);self.assertEqual('',result.stdout);self.assertLess(time.monotonic()-started,2)

if __name__=='__main__':unittest.main()
