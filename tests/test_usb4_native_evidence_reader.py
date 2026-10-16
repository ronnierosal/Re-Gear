"""Offline native read contract; no bus, permission request or device writes."""
import json
import unittest
from regear.application.usb4_native_evidence import collect_native_evidence
from regear.ports.usb4_native_evidence import Fact, ReadLimits
from regear.adapters.steamos.usb4_native_evidence import BoltNativeEvidenceReader

MANAGER = '<node><interface name="org.freedesktop.bolt1.Manager"><method name="ListDevices"><arg direction="out" type="ao"/></method></interface></node>'
DEVICE = '<node><interface name="org.freedesktop.bolt1.Device"><method name="Authorize"><arg direction="in" type="s"/></method><property name="Uid" type="s" access="read"/><property name="Status" type="s" access="read"/><property name="Stored" type="b" access="read"/></interface></node>'

class Transport:
    def __init__(self):
        self.calls=[]; self.owners=iter((':1.42', ':1.42')); self.devices=['/org/freedesktop/bolt/devices/a']
        self.manager=MANAGER; self.device=DEVICE; self.properties={'Uid':'private-binding','Status':'connected','Stored':False}
    def __call__(self, request, budget):
        self.calls.append((request,budget))
        if request.member=='GetNameOwner': value=next(self.owners)
        elif request.member=='Introspect': value=self.manager if request.path=='/org/freedesktop/bolt' else self.device
        elif request.member=='ListDevices': value=self.devices
        elif request.member=='GetAll': value=self.properties
        else: raise AssertionError('unexpected operation')
        return json.dumps(value).encode()

class ReaderTests(unittest.TestCase):
    def collect(self,t=None,clock=lambda:10,limits=ReadLimits()):
        self.t=t or Transport()
        return collect_native_evidence(BoltNativeEvidenceReader(self.t,clock=clock),clock=clock,limits=limits)
    def test_verified_interface_never_implies_permission_or_fresh_binding(self):
        r=self.collect(); self.assertEqual('evidence.observed',r.code)
        self.assertIs(r.snapshot.api,Fact.OBSERVED)
        self.assertIs(r.snapshot.static_permission,Fact.UNKNOWN)
        self.assertIs(r.snapshot.plugin_context,Fact.UNKNOWN)
        self.assertIs(r.snapshot.enrollment_store,Fact.OBSERVED)
        self.assertIs(r.snapshot.attachment_state,Fact.UNKNOWN)
        self.assertIsNone(r.snapshot.attachment)
        for q,b in self.t.calls:
            self.assertFalse(q.auto_start); self.assertFalse(q.interactive)
            self.assertIn(q.member,('GetNameOwner','Introspect','ListDevices','GetAll'))
            if q.member!='GetNameOwner': self.assertEqual(':1.42',q.destination)
        self.assertFalse(hasattr(r,'mutation_allowed'))
    def test_absent_owner_never_reads_manager(self):
        t=Transport();t.owners=iter((None,));self.assertEqual('evidence.service_unavailable',self.collect(t).code)
        self.assertEqual(1,len(t.calls))
    def test_owner_change_withdraws_all_evidence(self):
        t=Transport();t.owners=iter((':1.42',':1.43'));r=self.collect(t)
        self.assertEqual('evidence.owner_changed',r.code);self.assertIsNone(r.snapshot)
    def test_unknown_and_mismatched_interfaces(self):
        for field,value in [('manager','<node/>'),('device',DEVICE.replace('type="s"','type="u"')),('device','<!DOCTYPE node><node/>')]:
            t=Transport();setattr(t,field,value);r=self.collect(t)
            self.assertEqual('evidence.unsupported',r.code);self.assertIsNone(r.snapshot)
    def test_no_or_multiple_devices_never_choose_one(self):
        for devices,expected in [([],Fact.UNKNOWN),(['/a','/b'],Fact.AMBIGUOUS)]:
            t=Transport();t.devices=devices;r=self.collect(t)
            self.assertIs(r.snapshot.attachment_state,expected);self.assertIsNone(r.snapshot.attachment)
            self.assertFalse(any(q.member=='GetAll' for q,_ in t.calls))
    def test_denied_timeout_and_malformed_fail_closed(self):
        for error,code in [(PermissionError(),'denied'),(TimeoutError(),'timeout'),(ValueError('private detail'),'error')]:
            def fail(q,b):raise error
            r=self.collect(fail);self.assertEqual('evidence.'+code,r.code);self.assertIsNone(r.snapshot)
        for value in (b'not json',b'{}',b'"well.known.name"'):
            r=self.collect(lambda q,b:value);self.assertNotEqual('evidence.observed',r.code)
    def test_budget_and_properties_are_strict(self):
        self.assertEqual('evidence.error',self.collect(lambda q,b:b' '*65537).code)
        t=Transport();t.properties['Stored']='false';self.assertEqual('evidence.error',self.collect(t).code)
        r=self.collect(limits=ReadLimits(max_objects=3));self.assertNotEqual('evidence.observed',r.code)
        self.assertTrue(all(b.max_bytes<=65536 and b.max_objects<=64 for _,b in self.t.calls))
    def test_clock_deadline_and_backwards_clock(self):
        for values in ((10,41),(10,9)):
            times=iter(values)
            self.assertNotEqual('evidence.observed',self.collect(clock=lambda:next(times)).code)
        now=[10];t=Transport()
        def slow(q,b):
            result=t(q,b);now[0]=41;return result
        self.assertEqual('evidence.timeout',self.collect(slow,clock=lambda:now[0]).code)
    def test_owner_wire_cannot_hide_unaccounted_padding(self):
        self.assertEqual('evidence.error',self.collect(lambda q,b:b'  ":1.42"').code)
    def test_cumulative_bytes_and_private_identity(self):
        t=Transport();r=self.collect(t)
        total=sum(len(json.dumps(v).encode()) for v in (MANAGER,t.devices,DEVICE,t.properties))+4
        self.assertEqual(total,r.snapshot.bytes_read)
        self.assertNotIn('private-binding',repr(r))
        self.assertNotIn(':1.42',repr(r))
        t=Transport();t.manager=MANAGER+' '*65500
        self.assertNotEqual('evidence.observed',self.collect(t).code)
    def test_canonical_dbus_doctype_is_accepted_without_resolution(self):
        declaration='<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN" "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">'
        t=Transport();t.manager=declaration+MANAGER;t.device=declaration+DEVICE
        self.assertEqual('evidence.observed',self.collect(t).code)
        for extra in ('<!ENTITY x "secret">', '<!DOCTYPE node SYSTEM "file:///private">', declaration.replace('1.0//EN','1.1//EN'),declaration+'<!DOCTYPE node>'):
            t=Transport();t.manager=extra+MANAGER
            self.assertEqual('evidence.unsupported',self.collect(t).code)

if __name__=='__main__':unittest.main()
