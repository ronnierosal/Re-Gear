"""Injected bus replies only; no bus or device is contacted."""
import json
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
    return reply('v', {'type': signature, 'data': list(values)})


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
