"""Fake-only capture contract. Never starts a process or contacts a bus."""
import json
import unittest
from regear.adapters.steamos.commands import BoltNativeReadCommandRunner, CommandResult
from regear.adapters.steamos.bolt_inventory_capture import capture_inventory


class Fake:
    def __init__(self):
        self.calls=[]; self.paths=['/org/freedesktop/bolt/devices/host','/org/freedesktop/bolt/devices/peripheral']
        self.types=['host','peripheral'];self.statuses=['authorized','authorized']
        self.sysfs='/sys/devices/pci0000:00/fixture/0-1';self.owner_after=':1.42';self.transform=lambda v:v
    def run(self,argv):
        self.calls.append(argv);tail=argv[len(BoltNativeReadCommandRunner.PREFIX):]
        if tail[4]=='GetNameOwner':v={'type':'s','data':[':1.42' if len(self.calls)==1 else self.owner_after]}
        elif tail[4]=='ListDevices':v={'type':'ao','data':[self.paths]}
        else:
            index=self.paths.index(tail[2]);prop=tail[-1]
            value={'Type':self.types[index],'Status':self.statuses[index],'SysfsPath':self.sysfs}[prop]
            v={'type':'v','data':[{'type':'s','data':value}]}
        return CommandResult(argv,0,json.dumps(self.transform(v)),'')


class CaptureTests(unittest.TestCase):
    def capture(self,f=None,clock=lambda:10):
        self.f=f or Fake();return capture_inventory(self.f,clock=clock)
    def test_complete_two_authorized_objects_both_orders(self):
        for reverse in (False,True):
            f=Fake()
            if reverse:f.paths.reverse();f.types.reverse();f.statuses.reverse()
            r=self.capture(f)
            self.assertEqual('capture.observed',r.code);self.assertEqual(8,len(f.calls))
            self.assertEqual(f.sysfs,r.sysfs_path);self.assertNotIn(f.sysfs,repr(r))
            self.assertEqual((('authorized',2),),r.status_counts)
            self.assertFalse(hasattr(r,'attachment'));self.assertFalse(hasattr(r,'grant'))
    def test_runner_is_separate_and_legacy_still_rejects_new_properties(self):
        from regear.adapters.steamos.commands import BoltInventoryCaptureCommandRunner as R
        base=R.PREFIX+('call',':1.42','/org/freedesktop/bolt/devices/a','org.freedesktop.DBus.Properties','Get','ss','org.freedesktop.bolt1.Device')
        for prop in ('Type','SysfsPath'):
            self.assertEqual(base+(prop,),R.validate(base+(prop,)))
            with self.assertRaises(ValueError):BoltNativeReadCommandRunner.validate(base+(prop,))
        for prop in ('Uid','Stored','Key','Policy','Authorize'):
            with self.assertRaises(ValueError):R.validate(base+(prop,))
        for tail in [('org.freedesktop.DBus.Introspectable','Introspect'),('org.freedesktop.DBus.Properties','GetAll','s','org.freedesktop.bolt1.Device')]:
            with self.assertRaises(ValueError):R.validate(base[:len(R.PREFIX)+3]+tail)
    def test_unknown_duplicate_types_and_disconnected_do_not_read_path(self):
        for types,statuses in [(['host','unknown'],['authorized']*2),(['peripheral']*2,['authorized']*2),(['host']*2,['authorized']*2),(['host','peripheral'],['authorized','disconnected']),(['host','peripheral'],['authorized','connecting']),(['host','peripheral'],['authorized','unknown'])]:
            f=Fake();f.types=types;f.statuses=statuses;r=self.capture(f)
            self.assertNotEqual('capture.observed',r.code);self.assertIsNone(r.sysfs_path)
            self.assertFalse(any(q[-1]=='SysfsPath' for q in f.calls));self.assertEqual(7,len(f.calls))
    def test_incomplete_or_oversized_inventory_is_not_truncated(self):
        for paths in ([],['/org/freedesktop/bolt/devices/a'],['/org/freedesktop/bolt/devices/a','/org/freedesktop/bolt/devices/b','/org/freedesktop/bolt/devices/c']):
            f=Fake();f.paths=paths;r=self.capture(f)
            self.assertEqual('capture.inventory_unresolved',r.code);self.assertEqual(3,len(f.calls));self.assertIsNone(r.sysfs_path)
    def test_duplicate_malformed_inventory_fails_closed(self):
        for paths in (['/org/freedesktop/bolt/devices/a']*2,['/wrong/a','/wrong/b'],[True,False]):
            f=Fake();f.paths=paths;r=self.capture(f)
            self.assertEqual('capture.malformed',r.code);self.assertIsNone(r.sysfs_path)
    def test_owner_change_discards_every_private_result(self):
        f=Fake();f.owner_after=':1.43';r=self.capture(f)
        self.assertEqual('capture.owner_changed',r.code);self.assertIsNone(r.sysfs_path);self.assertEqual((),r.status_counts)
    def test_noncanonical_paths_never_resolved(self):
        from unittest.mock import patch
        for value in ('','relative','/sys/devices/../private','/sys/devices//a','/sys/devices/a/','/etc/passwd','/sys/devices/a\n'):
            f=Fake();f.sysfs=value
            with patch('os.path.realpath',side_effect=AssertionError('no resolution')):
                r=self.capture(f)
            self.assertEqual('capture.malformed',r.code);self.assertIsNone(r.sysfs_path)
    def test_bad_envelopes_types_and_native_errors_are_categorical(self):
        for change in (lambda v:{**v,'extra':'private'},lambda v:{'type':'u','data':[2]},lambda v:{'type':'s','data':[True]}):
            f=Fake();f.transform=change;r=self.capture(f)
            self.assertEqual('capture.malformed',r.code);self.assertNotIn('private',repr(r))
        f=Fake();f.run=lambda q:CommandResult(q,1,'private','secret','denied secret')
        r=self.capture(f);self.assertEqual('capture.unavailable',r.code);self.assertNotIn('secret',repr(r))
    def test_total_time_output_and_clock_bounds(self):
        f=Fake();times=iter([10,10,14]);r=self.capture(f,clock=lambda:next(times,14))
        self.assertEqual('capture.timeout',r.code);self.assertLessEqual(len(f.calls),1)
        for clock in (lambda:float('nan'),iter([10,9]).__next__):
            self.assertEqual('capture.malformed',self.capture(clock=clock).code)
        f=Fake();f.run=lambda q:CommandResult(q,0,'x'*65537,'')
        self.assertEqual('capture.bounds',self.capture(f).code)
    def test_cumulative_bytes_and_runner_limits_do_not_reset_per_read(self):
        from regear.adapters.steamos.commands import BoltInventoryCaptureCommandRunner as R
        runner=R();self.assertEqual(8,runner._remaining_calls);self.assertEqual(65536,runner._remaining_bytes)
        with self.assertRaises(TypeError):R(max_calls=9)
        f=Fake();original=f.run
        def padded(q):
            r=original(q);return CommandResult(q,0,' '*10000+r.stdout,'')
        f.run=padded;r=self.capture(f)
        self.assertEqual('capture.bounds',r.code);self.assertLessEqual(len(f.calls),8);self.assertIsNone(r.sysfs_path)
    def test_strict_duplicate_deep_and_scalar_replies(self):
        for raw in ('{"type":"s","type":"s","data":[":1.42"]}', '['*9+'0'+']'*9):
            f=Fake();f.run=lambda q:CommandResult(q,0,raw,'')
            self.assertEqual('capture.malformed',self.capture(f).code)
        for field in ('Type','Status','SysfsPath'):
            for bad in (True,None,[],{'private':'value'}):
                f=Fake();original=f.run
                def invalid(q):
                    r=original(q)
                    if q[-1]==field:
                        return CommandResult(q,0,json.dumps({'type':'v','data':[{'type':'s','data':bad}]}),'')
                    return r
                f.run=invalid;r=self.capture(f)
                self.assertEqual('capture.malformed',r.code);self.assertIsNone(r.sysfs_path)
    def test_runner_rejects_altered_flags_paths_destination_and_mutations(self):
        from regear.adapters.steamos.commands import BoltInventoryCaptureCommandRunner as R
        valid=R.PREFIX+('call',':1.42','/org/freedesktop/bolt/devices/a','org.freedesktop.DBus.Properties','Get','ss','org.freedesktop.bolt1.Device','Type')
        for index,value in ((0,'busctl'),(3,'--allow-interactive-authorization=yes'),(4,'--auto-start=yes'),(len(R.PREFIX)+1,'org.freedesktop.bolt'),(len(R.PREFIX)+2,'/org/freedesktop/bolt/devices/../a'),(len(R.PREFIX)+4,'Set')):
            changed=list(valid);changed[index]=value
            with self.assertRaises(ValueError):R.validate(changed)
        with self.assertRaises(ValueError):R.validate(valid+('extra',))


if __name__=='__main__':unittest.main()
