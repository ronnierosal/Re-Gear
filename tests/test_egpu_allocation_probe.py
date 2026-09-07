import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.probe_egpu_allocations import bounded_text, capture_processes, summarize
from hdm.domain.models import EgpuResourceKind


class AllocationProbeTests(unittest.TestCase):
    def row(self, raw):
        return dict(name='steam', fdinfo=[('drm_render', raw)]*3,
                    mapping_counts={}, libraries=['mesa_opengl'], errors=[])

    def test_duplicate_descriptors_are_not_summed_and_identifiers_redacted(self):
        raw='drm-driver: amdgpu\ndrm-client-id: 5\ndrm-resident-vram: 2 MiB\n'
        data={('123', 100):self.row(raw)}
        result=summarize(data,data,device_stable=True)
        clients=result['processes'][0]['graphics_clients']
        self.assertEqual(len(clients),1)
        self.assertEqual(clients[0]['descriptor_count'],3)
        self.assertEqual(clients[0]['stats']['resident_bytes']['vram'],2*1024*1024)
        self.assertNotIn('client_id',clients[0]['stats'])
        self.assertEqual(clients[0]['activity']['status'],'unknown')

    def test_changed_device_or_process_cannot_produce_activity_delta(self):
        first='drm-driver: amdgpu\ndrm-client-id: 5\ndrm-engine-gfx: 10 ns\n'
        second=first.replace('10 ns','20 ns')
        before={('123',100):self.row(first)}
        after={('123',100):self.row(second)}
        result=summarize(before,after,device_stable=False)
        self.assertEqual(result['processes'][0]['graphics_clients'][0]['activity']['status'],'unknown')
        after={('123',101):self.row(second)}
        result=summarize(before,after,device_stable=True)
        self.assertFalse(result['process_set_stable'])
        self.assertFalse(result['processes'][0]['process_stable'])

    def test_read_bound(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'value'
            p.write_bytes(b'x'*20)
            with self.assertRaises(ValueError):bounded_text(p,10)

    def test_before_sample_errors_are_not_lost(self):
        raw='drm-driver: amdgpu\ndrm-client-id: 5\n'
        first=self.row(raw)
        first['errors']=['descriptors_unreadable']
        after=self.row(raw)
        result=summarize({('123',100):first},{('123',100):after},device_stable=True)
        self.assertIn('descriptors_unreadable',result['processes'][0]['errors'])

    def test_unreadable_descriptors_remain_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'123'
            p.mkdir()
            (p/'comm').write_text('gamescope-wl\n')
            (p/'stat').write_text('123 (name with spaces) '+' '.join(['0']*19+['100']))
            (p/'maps').write_text('')
            rows,errors=capture_processes({},proc_root=Path(d))
            self.assertIn('descriptors_unreadable',rows[('123',100)]['errors'])

    def test_mapping_only_holder_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'123'
            p.mkdir()
            (p/'fd').mkdir()
            (p/'comm').write_text('steam\n')
            (p/'stat').write_text('123 (steam) '+' '.join(['0']*19+['100']))
            (p/'maps').write_text('100-200 rw-s 0 00:01 1 /dev/dri/renderD900\n')
            rows,_=capture_processes({'/dev/dri/renderD900':EgpuResourceKind.DRM_RENDER},proc_root=Path(d))
            result=summarize(rows,rows,device_stable=True)
            self.assertEqual(result['processes'][0]['mapping_counts'],{'drm_render':1})
            self.assertEqual(result['processes'][0]['graphics_clients'],[])
