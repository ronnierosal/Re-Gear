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
        self.manager=MANAGER; self.device=DEVICE; self.properties={'Uid':'private-binding','Status':'connected','Stored':False}; self.statuses={}
    def __call__(self, request, budget):
        self.calls.append((request,budget))
        if request.member=='GetNameOwner': value=next(self.owners)
        elif request.member=='Introspect': value=self.manager if request.path=='/org/freedesktop/bolt' else self.device
        elif request.member=='ListDevices': value=self.devices
        elif request.member=='GetAll': value=self.properties
        elif request.member=='Get':
            assert request.arguments==('org.freedesktop.bolt1.Device','Status')
            value=self.statuses.get(request.path,'unknown')
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

    def test_current_and_remembered_objects_only_inspect_candidate_in_every_order(self):
        import itertools
        paths=['/org/freedesktop/bolt/devices/current','/org/freedesktop/bolt/devices/stored','/org/freedesktop/bolt/devices/host']
        for count in (2,3):
            for order in itertools.permutations(paths[:count]):
                t=Transport();t.devices=list(order)
                t.statuses={p:('connected' if p==paths[0] else 'disconnected') for p in paths[:count]}
                report=self.collect(t)
                self.assertEqual('evidence.observed',report.code)
                self.assertIs(report.snapshot.api,Fact.OBSERVED)
                self.assertIs(report.snapshot.attachment_state,Fact.UNKNOWN)
                self.assertIs(report.snapshot.enrollment_store,Fact.UNKNOWN)
                self.assertIs(report.snapshot.static_permission,Fact.UNKNOWN)
                self.assertIsNone(report.snapshot.attachment)
                self.assertFalse(any(q.member=='GetAll' for q,_ in t.calls))
                inspected=[q.path for q,_ in t.calls if q.member=='Introspect' and q.path!='/org/freedesktop/bolt']
                self.assertEqual([paths[0]],inspected)

    def test_host_candidate_never_becomes_external_attachment_or_enrollment(self):
        t=Transport();t.devices=['/host','/stored']
        t.statuses={'/host':'authorized','/stored':'disconnected'}
        r=self.collect(t)
        self.assertIs(r.snapshot.api,Fact.OBSERVED)
        self.assertIs(r.snapshot.attachment_state,Fact.UNKNOWN)
        self.assertIs(r.snapshot.enrollment_store,Fact.UNKNOWN)
        self.assertIsNone(r.snapshot.attachment)

    def test_unresolved_inventory_never_selects_or_partially_inspects(self):
        for statuses in (['connected','authorized'],['disconnected','disconnected'],
                         ['connected','unknown'],['connected','connecting'],
                         ['connected','authorizing'],['connected','unexpected'],
                         ['connected',None],['connected',True]):
            for order in (statuses,statuses[::-1]):
                t=Transport();t.devices=['/a','/b'];t.statuses=dict(zip(t.devices,order))
                r=self.collect(t)
                self.assertIs(r.snapshot.attachment_state,Fact.AMBIGUOUS)
                self.assertIs(r.snapshot.api,Fact.UNKNOWN)
                self.assertIsNone(r.snapshot.attachment)
                self.assertFalse(any(q.member=='Introspect' and q.path!='/org/freedesktop/bolt' for q,_ in t.calls))
        t=Transport();t.devices=['/a','/b','/c','/d']
        self.assertIs(self.collect(t).snapshot.attachment_state,Fact.AMBIGUOUS)
        self.assertFalse(any(q.member in ('Get','GetAll') for q,_ in t.calls))

    def test_candidate_owner_change_withdraws_all_evidence(self):
        t=Transport();t.devices=['/a','/b'];t.statuses={'/a':'connected','/b':'disconnected'}
        t.owners=iter((':1.42',':1.43'))
        r=self.collect(t)
        self.assertEqual('evidence.owner_changed',r.code);self.assertIsNone(r.snapshot)
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

    def test_representative_introspection_layout_and_safe_attribute_references(self):
        t=Transport()
        t.manager='''<node name="/org/freedesktop/bolt">
          <interface name='org.freedesktop.DBus.Peer'><method name='Ping'/></interface>
          <interface name="org.freedesktop.bolt1.Manager">
            <annotation name="org.example.Note" value="a &amp; b &lt; c &gt; d &quot; e &apos; &#65; &#x42;"/>
            <method name="ListDevices"><arg name="devices" type="a&#111;" direction="out" /></method>
          </interface><node name="devices"/>
        </node>'''
        t.device=DEVICE.replace('direction="in" ', '').replace('access="read"','access="readwrite"')
        self.assertEqual('evidence.observed',self.collect(t).code)

    def test_malformed_or_unsupported_xml_never_qualifies(self):
        invalid = [
            MANAGER.replace('</node>', '</interface>'), MANAGER+MANAGER,
            MANAGER.replace('<node>', '<node duplicate="a" duplicate="b">'),
            MANAGER.replace('<node>', '<node xmlns="urn:fake">'),
            MANAGER.replace('<node>', '<prefix:node>'),
            MANAGER.replace('<node>', '<node a="&unknown;">'),
            MANAGER.replace('<node>', '<node a="&#0;">'),
            MANAGER.replace('<node>', '<node a="&#xD800;">'),
            MANAGER.replace('<node>', '<node a="&#x110000;">'),
            MANAGER.replace('<node>', '<node a="&#xFFFE;">'),
            MANAGER.replace('<node>', '<node a="&amp">'),
            MANAGER.replace('<node>', '<node a="raw<value">'),
            MANAGER.replace('<node>', '<node a="first"b="second">'),
            MANAGER.replace('<node>', '<node a=unquoted>'),
            MANAGER.replace('<node>', '<node a="unfinished>'),
            '<!--malformed--comment-->'+MANAGER, '<?xml version="1.0"?>'+MANAGER,
            MANAGER.replace('</node>', '<?instruction?></node>'),
            MANAGER.replace('<node>', '<node>untrusted text'),
            MANAGER+'trailing', '\x00'+MANAGER, '\ufffe'+MANAGER,
            '<!DOCTYPE node [<!ENTITY x "expanded">]>'+MANAGER,
            '<!DOCTYPE node SYSTEM "https://example.invalid/dtd">'+MANAGER,
        ]
        for xml in invalid:
            with self.subTest(xml=invalid.index(xml)):
                t=Transport();t.manager=xml
                report=self.collect(t)
                self.assertEqual('evidence.unsupported',report.code)
                self.assertIsNone(report.snapshot)
                self.assertEqual(2,len(t.calls))

    def test_parser_bounds_before_unbounded_tree_or_recursion(self):
        for xml in ('<node>'*17+'</node>'*17,
                    '<node>'+'<node/>'*1024+'</node>',
                    '<node '+ ' '.join(f'a{i}="x"' for i in range(33)) +'/>',
                    MANAGER+' '*65536, MANAGER+'\u0100'*33000):
            with self.subTest(length=len(xml)):
                with self.assertRaises(NotImplementedError):
                    BoltNativeEvidenceReader._interface(xml,'org.freedesktop.bolt1.Manager')

    def test_standard_gdbus_comment_header_is_inert_and_qualifies(self):
        declaration='<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN" "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">'
        t=Transport()
        t.manager=declaration+'\n<!-- GDBus 2.0 -->\n'+MANAGER
        t.device=declaration+'\n<!-- GDBus 2.0 -->\n'+DEVICE
        self.assertEqual('evidence.observed',self.collect(t).code)

    def test_valid_comments_are_not_parsed_as_elements_or_declarations(self):
        for comment in ('<!---->', '<!-- harmless -->', '<!-- <node/> -->',
                        '<!-- <!ENTITY x SYSTEM "file:///private"> <?not-a-PI?> &unknown; -->'):
            with self.subTest(comment=comment):
                t=Transport()
                t.manager=comment+MANAGER.replace('<method',comment+'<method')+comment
                self.assertEqual('evidence.observed',self.collect(t).code)
        t=Transport();t.manager=MANAGER.replace('type="ao"','type="s"')+'<!-- type="ao" -->'
        self.assertEqual('evidence.unsupported',self.collect(t).code)

    def test_malformed_comments_and_declarations_outside_comments_remain_unsupported(self):
        invalid = ['<!-- missing end', '<!-- a--b -->', '<!-- ends--->',
                   '<!-- nested <!-- comment -->', '<!--\x00-->',
                   '<!--good--><!ENTITY x "value">', '<!--good--><?instruction?>',
                   '<!--good--><![CDATA[value]]>', '<!--good--><!DOCTYPE node>',
                   MANAGER.replace('<node>', '<node <!--not-attribute-->>'),
                   '<!---->'*1025]
        for prefix in invalid:
            t=Transport();t.manager=prefix+MANAGER
            self.assertEqual('evidence.unsupported',self.collect(t).code)

    def test_comment_limit_is_finite_and_valid_xml_oracle_agrees(self):
        from xml.etree import ElementTree
        from regear.adapters.steamos.usb4_native_evidence import _introspection_tree
        xml='<!---->'*1024+MANAGER
        self.assertEqual(ElementTree.fromstring(xml).tag,_introspection_tree(xml)[0])
        for body in ('a','-','--','a-b','a--b','<node/>','&name;','a-'):
            xml='<!--'+body+'-->'+MANAGER
            try:
                tree=_introspection_tree(xml)
            except NotImplementedError:
                with self.assertRaises(ElementTree.ParseError):ElementTree.fromstring(xml)
            else:
                self.assertEqual(ElementTree.fromstring(xml).tag,tree[0])

    def test_duplicate_or_nested_contract_members_still_fail_exact_qualification(self):
        invalid_managers=[MANAGER.replace('</node>',MANAGER[6:-7]+'</node>'),
            MANAGER.replace('</interface>','<method name="ListDevices"><arg type="ao" direction="out"/></method></interface>'),
            MANAGER.replace('type="ao"','type="s"'),
            MANAGER.replace('<method','<node><method').replace('</method>','</method></node>')]
        for xml in invalid_managers:
            t=Transport();t.manager=xml
            self.assertEqual('evidence.unsupported',self.collect(t).code)

    def test_subset_never_accepts_malformed_xml_in_deterministic_mutation_corpus(self):
        # Independent stdlib oracle is test-only; not present in packaged runtime.
        from xml.etree import ElementTree
        from regear.adapters.steamos.usb4_native_evidence import _introspection_tree
        checked=0
        for position in range(len(MANAGER)):
            variants=[MANAGER[:position]+MANAGER[position+1:]]
            variants += [MANAGER[:position]+char+MANAGER[position:] for char in '<>&"\'/=:\x00']
            for xml in variants:
                try:
                    root=_introspection_tree(xml)
                except NotImplementedError:
                    continue
                reference=ElementTree.fromstring(xml)
                self.assertEqual(reference.tag,root[0])
                self.assertEqual(reference.attrib,root[1])
                checked+=1
        self.assertGreater(checked,10)

    def test_duplicate_or_mismatched_device_properties_fail_qualification(self):
        for xml in (DEVICE.replace('</interface>','<property name="Uid" type="s" access="read"/></interface>'),
                    DEVICE.replace('access="read"','access="write"'),
                    DEVICE.replace('type="s"','type="u"')):
            t=Transport();t.device=xml
            self.assertEqual('evidence.unsupported',self.collect(t).code)

if __name__=='__main__':unittest.main()
