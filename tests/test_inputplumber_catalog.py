"""Injected bus replies only; no bus or device is contacted."""
import json
import os
import subprocess
import sys
import unittest

from regear.adapters.steamos.commands import CommandResult, InputPlumberReadCommandRunner
from regear.adapters.steamos.inputplumber_catalog import InputPlumberReader, ReaderLimits
from regear.domain.controller_catalog import EvidenceState

ROOT = InputPlumberReadCommandRunner.ROOT
MANAGER = 'org.shadowblip.InputManager'
COMPOSITE = 'org.shadowblip.Input.CompositeDevice'


def reply(signature, *values):
    return json.dumps({'type': signature, 'data': list(values)})


def variant(signature, *values):
    return reply('v', {'type': signature, 'data': values[0] if len(values) == 1 else list(values)})


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.hook = None
        self.xml = {
            ROOT: '<node><node name="Manager"/><node name="CompositeDevice0"/></node>',
            ROOT + '/Manager': '<node><interface name="org.shadowblip.InputManager"><property name="Version" type="s" access="read"/></interface></node>',
            ROOT + '/CompositeDevice0': '<node><interface name="org.shadowblip.Input.CompositeDevice"><property name="ProfileName" type="s" access="read"/><property name="SourceDevicePaths" type="as" access="read"/></interface></node>',
        }

    def run(self, argv):
        InputPlumberReadCommandRunner.validate(argv)
        self.calls.append(argv)
        tail = argv[len(InputPlumberReadCommandRunner.PREFIX):]
        if tail[4] == 'GetId': out = reply('s', 'a' * 32)
        elif tail[4] == 'GetNameOwner': out = reply('s', ':1.24')
        elif tail[4] == 'Introspect': out = reply('s', self.xml[tail[2]])
        elif tail[-1] == 'SourceDevicePaths': out = variant('as', [])
        else: out = variant('s', 'fixture')
        result = CommandResult(tuple(argv), 0, out, '')
        return self.hook(tail, result) if self.hook else result


class ReaderTests(unittest.TestCase):
    def test_bundled_runtime_without_elementtree_still_enumerates(self):
        self.runtime_replay(False)

    def test_missing_expat_fails_closed_without_runner_calls(self):
        self.runtime_replay(True)

    def runtime_replay(self, missing_expat):
        code = '''
import importlib.abc, sys
class MissingXML(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('xml.etree') or (MISSING and (fullname in ('xml.parsers.expat', 'pyexpat'))):
            raise ModuleNotFoundError(fullname, name=fullname)
sys.meta_path.insert(0, MissingXML())
from test_inputplumber_catalog import FakeRunner, InputPlumberReader, EvidenceState
runner = FakeRunner()
frame = InputPlumberReader(runner).read_snapshot()
if MISSING:
    assert frame.availability is EvidenceState.UNKNOWN
    assert frame.objects == {} and frame.connection_epoch == ''
    assert not frame.enumeration_complete and not runner.calls
else:
    assert frame.availability is EvidenceState.KNOWN and frame.enumeration_complete
    assert frame.objects and runner.calls
'''.replace('MISSING', repr(missing_expat))
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(['backend', 'tests']))
        result = subprocess.run([sys.executable, '-c', code], capture_output=True,
                                text=True, env=env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_collects_private_frame_with_exact_reads(self):
        runner = FakeRunner()
        frame = InputPlumberReader(runner).read_snapshot()
        self.assertEqual(frame.availability, EvidenceState.KNOWN)
        self.assertTrue(frame.enumeration_complete)
        self.assertEqual(frame.objects[ROOT+'/Manager'][MANAGER]['Version'].value, 'fixture')
        self.assertEqual(frame.objects[ROOT+'/CompositeDevice0'][COMPOSITE]['SourceDevicePaths'].value, ())
        self.assertTrue(all(c[len(InputPlumberReadCommandRunner.PREFIX)] == 'call' for c in runner.calls))
        self.assertTrue(all(c[len(InputPlumberReadCommandRunner.PREFIX)+1] == ':1.24'
                            for c in runner.calls if c[len(InputPlumberReadCommandRunner.PREFIX)+4] in ('Introspect', 'Get')))

    def assert_discarded(self, runner, **kwargs):
        frame = InputPlumberReader(runner, **kwargs).read_snapshot()
        self.assertNotEqual(frame.availability, EvidenceState.KNOWN)
        self.assertEqual(frame.objects, {})
        self.assertEqual(frame.connection_epoch, '')
        self.assertFalse(frame.enumeration_complete)

    def test_provider_replacement_and_bus_restart(self):
        for method, new in [('GetId', 'b'*32), ('GetNameOwner', ':1.25')]:
            runner = FakeRunner()
            seen = []
            def hook(tail, result):
                if tail[4] == method:
                    seen.append(1)
                    if len(seen) > 1: return CommandResult(result.argv, 0, reply('s', new), '')
                return result
            runner.hook = hook
            self.assert_discarded(runner)

    def test_topology_and_relationship_churn(self):
        for method in ('Introspect', 'Get'):
            runner = FakeRunner()
            seen = []
            def hook(tail, result):
                if tail[4] == method and (method == 'Introspect' and tail[2] == ROOT or method == 'Get' and tail[-1] == 'SourceDevicePaths'):
                    seen.append(1)
                    if len(seen) > 1:
                        out = reply('s', '<node/>') if method == 'Introspect' else variant('as', [ROOT+'/Source0'])
                        return CommandResult(result.argv, 0, out, '')
                return result
            runner.hook = hook
            self.assert_discarded(runner)

    def test_malformed_and_denied_never_retain_old_data(self):
        for out in ('bad', '{"type":"s","type":"s","data":["x"]}', variant('u', 42),
                    variant('s', 'x', 'y'), reply('s', 'x'), variant('s', '\ud800')):
            runner = FakeRunner()
            runner.hook = lambda tail, r: CommandResult(r.argv, 0, out, '') if tail[4] == 'Get' else r
            frame = InputPlumberReader(runner).read_snapshot()
            self.assertFalse(frame.enumeration_complete)
            for props in frame.objects.values():
                for reads in props.values():
                    self.assertTrue(all(p.value is None for p in reads.values()))
        runner = FakeRunner()
        reader = InputPlumberReader(runner)
        self.assertTrue(reader.read_snapshot().enumeration_complete)
        runner.hook = lambda tail, r: CommandResult(r.argv, 1, '', 'private denied detail')
        self.assertEqual(reader.read_snapshot().objects, {})

    def test_xml_and_enumeration_bounds_fail_closed(self):
        for xml in ('<!DOCTYPE node [<!ENTITY x "x">]><node/>', '<node><node name="../escape"/></node>',
                    '<node><node name="Manager"/><node name="Manager"/></node>', '<node><interface name="broken"/></node>'):
            runner = FakeRunner(); runner.xml[ROOT] = xml
            self.assert_discarded(runner)
        self.assert_discarded(FakeRunner(), limits=ReaderLimits(max_objects=1))
        self.assert_discarded(FakeRunner(), limits=ReaderLimits(max_calls=1))
        self.assert_discarded(FakeRunner(), limits=ReaderLimits(max_bytes=50))

    def test_unknown_methods_and_write_only_properties_never_called(self):
        runner = FakeRunner()
        runner.xml[ROOT+'/Manager'] = '<node><interface name="org.shadowblip.InputManager"><method name="CreateTargetDevice"/><property name="ManageAllDevices" type="b" access="readwrite"/><property name="Version" type="s" access="write"/></interface></node>'
        InputPlumberReader(runner).read_snapshot()
        self.assertFalse(any(c[-1] in ('CreateTargetDevice','ManageAllDevices','Version') for c in runner.calls))

    def test_runner_exceptions_and_unbounded_limits(self):
        runner = FakeRunner()
        def fail(tail, r): raise RuntimeError('private secret')
        runner.hook = fail
        self.assert_discarded(runner)
        for kwargs in ({'max_calls':513}, {'max_bytes':1048577}, {'max_objects':True}, {'max_depth':0}):
            with self.assertRaises(ValueError): ReaderLimits(**kwargs)

    def test_parser_handoff_preserves_private_evidence(self):
        from regear.adapters.steamos.controller_catalog import parse_provider_frame
        catalog = parse_provider_frame(InputPlumberReader(FakeRunner()).read_snapshot())
        self.assertEqual(catalog.version.value, 'fixture')
        self.assertTrue(catalog.enumeration_complete)
        self.assertEqual(catalog.devices[0].profile_name.value, 'fixture')
        self.assertFalse(hasattr(InputPlumberReader(FakeRunner()), 'public_projection'))

    def test_real_array_signatures_and_udev_dictionary(self):
        runner = FakeRunner()
        runner.xml[ROOT] = '<node><node name="Source0"/></node>'
        runner.xml[ROOT+'/Source0'] = '<node><interface name="org.shadowblip.Input.Source.UdevDevice"><property name="Properties" type="a{ss}" access="read"/></interface><interface name="org.shadowblip.Input.Source.EventDevice"><property name="SupportedKeys" type="aq" access="read"/></interface></node>'
        runner.hook = lambda tail, r: CommandResult(r.argv, 0, variant('a{ss}', {'ID_BUS':'usb'}) if tail[-1] == 'Properties' else variant('aq', [304, 305]), '') if tail[4] == 'Get' else r
        frame = InputPlumberReader(runner).read_snapshot()
        self.assertTrue(frame.enumeration_complete)
        self.assertEqual(frame.objects[ROOT+'/Source0']['org.shadowblip.Input.Source.EventDevice']['SupportedKeys'].value, (304, 305))

    def test_noncanonical_relation_and_oversized_property_are_unknown(self):
        for value in (['relative'], [ROOT+'/Source0', ROOT+'/Source0'], ['x'*1025]):
            runner = FakeRunner()
            runner.hook = lambda tail, r: CommandResult(r.argv, 0, variant('as', value), '') if tail[-1] == 'SourceDevicePaths' else r
            frame = InputPlumberReader(runner).read_snapshot()
            self.assertFalse(frame.enumeration_complete)
            self.assertIsNone(frame.objects[ROOT+'/CompositeDevice0'][COMPOSITE]['SourceDevicePaths'].value)

    def test_construction_does_not_collect_and_frame_has_no_authority(self):
        runner = FakeRunner(); reader = InputPlumberReader(runner)
        self.assertEqual(runner.calls, [])
        frame = reader.read_snapshot()
        self.assertEqual(set(frame.__dataclass_fields__), {'connection_epoch', 'objects', 'availability', 'enumeration_complete', 'interface_states'})
        self.assertFalse(any(hasattr(reader, name) for name in ('apply', 'set_profile', 'set_target', 'reopen', 'start')))

    def test_busctl_native_variant_payloads_are_known(self):
        # systemd busctl --json=short encodes a variant's inner data directly.
        samples = {
            'Version': '{"type":"v","data":[{"type":"s","data":"1.0"}]}',
            'ProfileName': '{"type":"v","data":[{"type":"s","data":"Fixture Profile"}]}',
            'SourceDevicePaths': '{"type":"v","data":[{"type":"as","data":[]}]}',
        }
        runner = FakeRunner()
        runner.hook = lambda tail, r: CommandResult(r.argv, 0, samples[tail[-1]], '') if tail[4] == 'Get' else r
        frame = InputPlumberReader(runner).read_snapshot()
        self.assertTrue(frame.enumeration_complete)
        self.assertEqual(frame.objects[ROOT+'/Manager'][MANAGER]['Version'].value, '1.0')
        self.assertEqual(frame.objects[ROOT+'/CompositeDevice0'][COMPOSITE]['ProfileName'].value, 'Fixture Profile')
        self.assertEqual(frame.objects[ROOT+'/CompositeDevice0'][COMPOSITE]['SourceDevicePaths'].value, ())

    def test_zbus_5_12_standard_doctype_is_stripped_before_xml_parser(self):
        from unittest.mock import patch
        from xml.parsers import expat
        # Pinned zbus-5.12.0 object_server/node.rs:160-163 emits this header.
        doctype = '\n<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"\n "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">\n'
        runner = FakeRunner()
        runner.xml = {path: doctype+xml for path, xml in runner.xml.items()}
        original = expat.ParserCreate
        case = self
        class CheckedParser:
            def __init__(self, **kwargs):
                object.__setattr__(self, 'parser', original(**kwargs))
            def __getattr__(self, name):
                return getattr(self.parser, name)
            def __setattr__(self, name, value):
                setattr(self.parser, name, value)
            def Parse(self, xml, final):
                case.assertNotIn('<!', xml)
                return self.parser.Parse(xml, final)
        with patch('xml.parsers.expat.ParserCreate', side_effect=CheckedParser):
            frame = InputPlumberReader(runner).read_snapshot()
        self.assertEqual(frame.availability, EvidenceState.KNOWN)
        self.assertTrue(frame.enumeration_complete)

    def test_doctype_entities_and_alternate_external_ids_stay_rejected(self):
        from unittest.mock import patch
        doctype = '<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN" "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">'
        for xml in (doctype.replace('http://www.freedesktop.org', 'https://attacker.invalid')+'<node/>',
                    doctype[:-1]+' [<!ENTITY secret SYSTEM "file:///etc/passwd">]><node/>',
                    doctype+doctype+'<node/>',
                    '<node>'+doctype+'</node>',
                    doctype+'<!ENTITY secret "expanded"><node/>',
                    '<!DOCTYPE node SYSTEM "file:///etc/passwd"><node/>',
                    doctype+'<node>&secret;</node>'):
            runner = FakeRunner(); runner.xml[ROOT] = xml
            if '&secret;' in xml:
                # Undefined references are rejected by the entity-free parser;
                # declarations themselves must be rejected before parsing.
                self.assert_discarded(runner)
            else:
                with patch('xml.parsers.expat.ParserCreate') as parse:
                    self.assert_discarded(runner)
                    parse.assert_not_called()

    def test_expat_strict_syntax_and_retained_structure_budgets(self):
        malformed = (
            '<node><interface></node>', '<node/><node/>',
            '<node name="a" name="b"/>', '<node name="unterminated/>',
            '<node>&external;</node>', '<node>&#0;</node>',
            '<node>&#xD800;</node>', '<node><!-- bad--comment --></node>',
            '<node xmlns="urn:unexpected"/>', '<x:node/>',
            '<node ' + ' '.join('a%d="v"' % i for i in range(9)) + '/>',
            '<node><annotation value="' + 'x'*1025 + '"/></node>',
            '<node>' + '<annotation/>'*257 + '</node>',
            '<node>' + '<annotation>'*9 + '</annotation>'*9 + '</node>',
        )
        for xml in malformed:
            with self.subTest(xml=xml[:80]):
                runner = FakeRunner(); runner.xml[ROOT] = xml
                self.assert_discarded(runner)
                self.assertEqual(len(runner.calls), 3)
        runner = FakeRunner()
        runner.xml[ROOT] = '<node><annotation value="&lt;&gt;&amp;&quot;&apos;&#65;&#x42;"/></node>'
        frame = InputPlumberReader(runner).read_snapshot()
        self.assertTrue(frame.enumeration_complete)

    def test_expat_handlers_block_declarations_even_if_prescan_misses(self):
        from regear.adapters.steamos.inputplumber_catalog import _Read, _Invalid
        from xml.parsers import expat
        for xml in ('<!DOCTYPE node [<!ENTITY x "expanded">]><node>&x;</node>',
                    '<!DOCTYPE node SYSTEM "file:///etc/passwd"><node/>'):
            read = _Read(FakeRunner(), ReaderLimits(), expat)
            # Directly exercise defense-in-depth by hiding declarations only
            # from the lexical scan, while Expat receives the original XML.
            class HiddenDeclarations(str):
                def find(self, *args): return -1
            with self.assertRaises(_Invalid):
                read.xml_root(HiddenDeclarations(xml))

    def test_documentation_comments_are_bounded_and_accepted(self):
        header = '<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"\n "http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">'
        runner = FakeRunner()
        runner.xml = {path: '<!-- prolog documentation -->\n'+header+'\n'+xml.replace('<node>', '<node><!-- normal zbus documentation -->', 1)
                      for path, xml in runner.xml.items()}
        frame = InputPlumberReader(runner).read_snapshot()
        self.assertTrue(frame.enumeration_complete)
        self.assertEqual(frame.objects[ROOT+'/Manager'][MANAGER]['Version'].state, EvidenceState.KNOWN)
        runner = FakeRunner()
        runner.xml[ROOT] = '<node>' + '<!-- doc -->' * 257 + '</node>'
        self.assert_discarded(runner)
        runner.calls.clear()
        runner.xml[ROOT] = '<node>' + '<annotation>' * 8 + '<!-- doc -->' + '</annotation>' * 8 + '</node>'
        self.assert_discarded(runner)
        self.assertEqual(len(runner.calls), 3)  # XML depth rejected at first introspection.
        runner.xml[ROOT] = '<node/>' + '<!-- trailing -->' * 257
        self.assert_discarded(runner, limits=ReaderLimits(max_nodes=256))
        runner.xml[ROOT] = '<node><!-- unterminated</node>'
        self.assert_discarded(runner)

    def test_artificial_nested_variant_wrappers_are_rejected(self):
        malformed = {'Version': ('s', ['fixture']), 'ProfileName': ('s', ['fixture']),
                     'SourceDevicePaths': ('as', [[]])}
        runner = FakeRunner()
        def wrapped(tail, result):
            if tail[4] != 'Get': return result
            signature, data = malformed[tail[-1]]
            return CommandResult(result.argv, 0, json.dumps({'type':'v', 'data':[{'type':signature, 'data':data}]}), '')
        runner.hook = wrapped
        frame = InputPlumberReader(runner).read_snapshot()
        self.assertFalse(frame.enumeration_complete)
        self.assertIsNone(frame.objects[ROOT+'/Manager'][MANAGER]['Version'].value)
        self.assertIsNone(frame.objects[ROOT+'/CompositeDevice0'][COMPOSITE]['SourceDevicePaths'].value)
