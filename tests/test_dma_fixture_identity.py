from dataclasses import replace
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.dma_fixture_identity import RenderTarget, collect_identity, resolve_targets


@unittest.skipUnless(os.name == 'posix', 'Linux sysfs names and dev_t require POSIX fixtures')
class RenderResolverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.drm,self.pci,self.chars,self.dev=(self.root/name for name in ('drm','pci','char','dev'))
        for path in (self.drm,self.pci,self.chars,self.dev):path.mkdir()
        self.bindings=(('0000:64:00.0','card4'),('0000:08:00.0','card9'))
        self.numbers={'card4':(226,4),'renderD132':(226,132),'card9':(226,9),'renderD137':(226,137)}
        for bdf,_ in self.bindings:(self.pci/bdf).mkdir()
        try:
            for name,(major,minor) in self.numbers.items():
                entry=self.drm/name
                entry.mkdir()
                bdf=self.bindings[0 if name in ('card4','renderD132') else 1][0]
                (entry/'device').symlink_to(self.pci/bdf,target_is_directory=True)
                (entry/'dev').write_text(f'{major}:{minor}\n')
                (self.chars/f'{major}:{minor}').symlink_to(entry,target_is_directory=True)
        except OSError as error:
            self.skipTest(f'symlink fixture unavailable: {error}')
        self.lstat=lambda path:SimpleNamespace(st_mode=stat.S_IFCHR|0o600,
                                               st_rdev=os.makedev(*self.numbers[path.name]))

    def resolve(self):
        return resolve_targets(self.bindings,drm_root=self.drm,pci_root=self.pci,
                               char_root=self.chars,dev_root=self.dev,lstat=self.lstat)

    def test_dynamic_exact_render_and_primary_minor(self):
        internal,external=self.resolve()
        self.assertEqual(internal,RenderTarget(str(self.dev/'renderD132'),os.makedev(226,132),4,self.bindings[0][0]))
        self.assertEqual(external.primary_minor,9)

    def test_regular_or_symlink_device_nodes_rejected(self):
        for mode in (stat.S_IFREG,stat.S_IFLNK):
            self.lstat=lambda path:SimpleNamespace(st_mode=mode,st_rdev=os.makedev(*self.numbers[path.name]))
            with self.assertRaises(ValueError):self.resolve()

    def test_wrong_device_number_and_sysfs_identity_rejected(self):
        self.lstat=lambda path:SimpleNamespace(st_mode=stat.S_IFCHR,st_rdev=0)
        with self.assertRaises(ValueError):self.resolve()

    def test_malformed_or_unreadable_inventory_does_not_become_absence(self):
        (self.drm/'renderD132'/'dev').write_text('226:0132\n')
        with self.assertRaises(ValueError):self.resolve()
        (self.drm/'renderD132'/'dev').unlink()
        with self.assertRaises(OSError):self.resolve()

    def test_sysdev_char_must_resolve_to_exact_class_entry(self):
        link=self.chars/'226:132'
        link.unlink()
        link.symlink_to(self.drm/'card4',target_is_directory=True)
        with self.assertRaises(ValueError):self.resolve()


class FixtureCollectionTests(unittest.TestCase):
    def setUp(self):
        self.internal=SimpleNamespace(gpu_bdf='0000:64:00.0')
        self.external=SimpleNamespace(verified=True,gpu_bdf='0000:08:00.0')
        self.targets=(RenderTarget('/dev/dri/renderD132',1,4,self.internal.gpu_bdf),
                      RenderTarget('/dev/dri/renderD137',2,9,self.external.gpu_bdf))
        self.context=Mock(return_value=dict(ready=True,code='audio_context_observed',context_digest='a'*64))
        self.nodes=Mock(return_value=self.targets)
        self.sources=dict(context_capture=self.context,resolve_nodes=self.nodes,
            drm=SimpleNamespace(scan=lambda:(SimpleNamespace(name='card4',pci_bdf=self.internal.gpu_bdf),
                                              SimpleNamespace(name='card9',pci_bdf=self.external.gpu_bdf))),
            pci=SimpleNamespace(scan_pci=lambda:(),scan_usb4_checked=lambda:((),True)),
            host=SimpleNamespace(scan=lambda:object()),platform='linux',effective_uid=lambda:0)

    def collect(self):
        with patch('scripts.dma_fixture_identity.match_ally_x_analog_audio',return_value=self.internal), \
             patch('scripts.dma_fixture_identity.match_gpd_g1',return_value=self.external):
            return collect_identity(**self.sources)

    def test_stable_context_and_nodes_sampled_twice(self):
        result=self.collect()
        self.assertEqual(result.internal,self.targets[0])
        self.assertEqual(result.context_digest,'a'*64)
        self.assertEqual(self.context.call_count,2)
        self.assertEqual(self.nodes.call_count,2)

    def test_context_or_nodes_change_reject(self):
        self.context.side_effect=[dict(ready=True,code='audio_context_observed',context_digest=v*64) for v in ('a','b')]
        with self.assertRaises(ValueError):self.collect()
        self.context.side_effect=None
        self.nodes.side_effect=[self.targets,(replace(self.targets[0],device=3),self.targets[1])]
        with self.assertRaises(ValueError):self.collect()

    def test_unknown_context_or_transport_fail_closed(self):
        self.context.return_value=dict(ready=False,code='context_unavailable')
        with self.assertRaises(ValueError):self.collect()
        self.nodes.assert_not_called()
        self.context.return_value=dict(ready=True,code='audio_context_observed',context_digest='a'*64)
        self.sources['pci']=SimpleNamespace(scan_pci=lambda:(),scan_usb4_checked=lambda:((),False))
        with self.assertRaises(ValueError):self.collect()
        self.nodes.assert_not_called()

    def test_platform_and_privilege_guards_before_capture(self):
        self.sources['platform']='win32'
        with self.assertRaises(ValueError):self.collect()
        self.sources['platform']='linux'
        self.sources['effective_uid']=lambda:1000
        with self.assertRaises(ValueError):self.collect()
        self.context.assert_not_called()


if __name__=='__main__':unittest.main()
