import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from hdm.delivery.drm_fdinfo import parse_drm_fdinfo, compare_engine_samples


class DrmFdinfoTests(unittest.TestCase):
    def sample(self, extra='', client='7', driver='amdgpu'):
        return parse_drm_fdinfo(f'drm-driver: {driver}\ndrm-client-id: {client}\n' + extra)

    def compare(self, before, after, **kwargs):
        return compare_engine_samples(before, after, before_device='device-a',
                                      after_device=kwargs.get('device', 'device-a'))

    def test_units_and_aliases_not_summed(self):
        value = self.sample('drm-resident-vram: 1 MiB\ndrm-memory-vram: 1024 KiB\n'
                            'drm-total-vram: 2048 KiB\ndrm-resident-gtt: 8\n')
        self.assertTrue(value.complete)
        self.assertEqual(value.resident_bytes, {'vram': 1048576, 'gtt': 8})
        self.assertEqual(value.total_bytes, {'vram': 2097152})
        self.assertEqual(self.sample('drm-memory-vram: 2 KiB').resident_bytes,
                         {'vram': 2048})

    def test_alias_conflict_fails(self):
        self.assertFalse(self.sample('drm-resident-vram: 1\ndrm-memory-vram: 2').complete)

    def test_missing_counters_unavailable(self):
        value = self.sample('pos: 0\ndrm-engine-capacity-gfx: 2\n')
        self.assertTrue(value.complete)
        self.assertEqual(value.engines_ns, {})
        self.assertEqual(self.compare(value, value).status, 'unknown')

    def test_total_cycles_not_memory_bytes(self):
        value = self.sample('drm-total-cycles-gfx: 123\ndrm-cycles-gfx: 7\n'
                            'drm-total-vram: 2048 KiB\n')
        self.assertTrue(value.complete)
        self.assertEqual(value.total_bytes, {'vram': 2097152})
        self.assertEqual(value.engines_ns, {})
        self.assertEqual(self.compare(value, value).status, 'unknown')

    def test_recognized_keys_reject_whitespace(self):
        for text in ('drm-driver : amdgpu', ' drm-driver: amdgpu',
                     'drm-driver: amdgpu\ndrm-engine-gfx : 1 ns',
                     'drm-driver: amdgpu\n\tdrm-total-vram: 1 KiB'):
            with self.subTest(text=text):
                value = parse_drm_fdinfo(text)
                self.assertFalse(value.complete)
                self.assertEqual(value.error, 'invalid_key_whitespace')

    def test_required_driver_optional_client(self):
        self.assertFalse(parse_drm_fdinfo('drm-client-id: 1').complete)
        value = parse_drm_fdinfo('drm-driver: amdgpu\ndrm-engine-gfx: 1 ns')
        self.assertTrue(value.complete)
        self.assertIsNone(value.client_id)
        self.assertEqual(self.compare(value, value).status, 'unknown')

    def test_duplicate_recognized_fields(self):
        for extra in ('drm-driver: amdgpu', 'drm-client-id: 7',
                      'drm-engine-gfx: 1 ns\ndrm-engine-gfx: 1 ns',
                      'drm-resident-vram: 2\ndrm-resident-vram: 2'):
            with self.subTest(extra=extra):
                self.assertFalse(self.sample(extra).complete)

    def test_malformed_fields(self):
        for extra in ('drm-engine-gfx: -1 ns', 'drm-engine-gfx: 1 ms',
                      'drm-engine-gfx: 1', 'drm-total-vram: 1 GB',
                      'drm-resident-vram: NaN', 'drm-memory-vram: -1',
                      'drm-engine-: 1 ns', 'drm-engine-gfx'):
            with self.subTest(extra=extra):
                self.assertFalse(self.sample(extra).complete)
        self.assertFalse(self.sample(client='-1').complete)

    def test_bounds(self):
        self.assertFalse(parse_drm_fdinfo('x' * 16385).complete)
        self.assertFalse(parse_drm_fdinfo('é' * 8193).complete)
        self.assertFalse(parse_drm_fdinfo('x\n' * 257).complete)

    def test_delta_and_unchanged(self):
        a = self.sample('drm-engine-gfx: 12 ns\ndrm-engine-dma: 3 ns')
        b = self.sample('drm-engine-gfx: 15 ns\ndrm-engine-dma: 3 ns')
        self.assertEqual(self.compare(a, b).status, 'observed_increase')
        self.assertEqual(self.compare(a, b).deltas_ns, {'gfx': 3, 'dma': 0})
        self.assertEqual(self.compare(a, a).status, 'observed_no_increase')

    def test_identity_and_counter_discontinuity(self):
        a = self.sample('drm-engine-gfx: 12 ns')
        for b in (self.sample('drm-engine-gfx: 13 ns', client='8'),
                  self.sample('drm-engine-gfx: 13 ns', driver='i915'),
                  self.sample('drm-engine-gfx: 11 ns'),
                  self.sample('drm-engine-dma: 13 ns'),
                  parse_drm_fdinfo('invalid')):
            with self.subTest(sample=b):
                result = self.compare(a, b)
                self.assertEqual(result.status, 'unknown')
                self.assertEqual(result.deltas_ns, {})
        self.assertEqual(self.compare(a, a, device='device-b').status, 'unknown')


if __name__ == '__main__':
    unittest.main()
