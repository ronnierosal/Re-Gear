import stat
from dataclasses import replace
from types import SimpleNamespace
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from hdm.delivery.inherited_resource_scan import scan_inherited_resources
from hdm.delivery.device_filter_peer import WaitingPeerIdentity

CORE = b'pos:\t0\nflags:\t02000000\nmnt_id:\t12\nino:\t2\n'

class Reader:
    def __init__(self):
        self.rows={'fd/3':('/normal/library',stat.S_IFREG,0,CORE),
                   'map_files/1000-2000':('/normal/library',stat.S_IFREG,0,b'')}
        self.snapshots=0
        self.change=False
        self.fail=''
    def entries(self,fd,directory):
        if directory=='fd':self.snapshots+=1
        return tuple(key.split('/',1)[1] for key in self.rows if key.startswith(directory+'/'))
    def target_link(self,fd,relative):
        if self.fail=='link':raise PermissionError('private/path')
        return self.rows[relative][0]
    def target_stat(self,fd,relative):
        if self.fail=='stat':raise PermissionError('private/path')
        return SimpleNamespace(st_dev=1,st_ino=2+self.snapshots if self.change else 2,
                               st_mode=self.rows[relative][1],st_rdev=self.rows[relative][2])
    def fdinfo(self,fd,number):
        if self.fail=='fdinfo':raise PermissionError('private/path')
        raw = self.rows['fd/'+number][3]
        return raw.replace(b'ino:\t2\n', f'ino:\t{2+self.snapshots}\n'.encode()) if self.change else raw


class InheritedResourceTests(unittest.TestCase):
    def setUp(self):
        self.reader=Reader()
        self.identity=WaitingPeerIdentity(123,1000,77,'a'*32,'gamescope-session.service',
                                         '/fixture/session',1,22)
        self.peer=SimpleNamespace(proc_fd=12,revalidate=Mock(return_value=self.identity))
        self.now=10
    def scan(self,**kwargs):
        with patch('hdm.delivery.inherited_resource_scan.os.major',lambda dev:dev>>20,create=True), \
             patch('hdm.delivery.inherited_resource_scan.os.minor',lambda dev:dev&((1<<20)-1),create=True):
            return scan_inherited_resources(self.peer,((226,132),),deadline=20,
                reader=self.reader,clock=lambda:self.now,platform='linux',**kwargs)

    def test_two_stable_snapshots_not_clearance(self):
        result=self.scan()
        self.assertTrue(result.complete)
        self.assertFalse(result.target_character_seen)
        self.assertFalse(result.dma_buf_seen)
        self.assertFalse(result.unclassified_seen)
        self.assertEqual(self.reader.snapshots,2)
        self.assertEqual(self.peer.revalidate.call_count,3)
        self.assertFalse(hasattr(result,'disconnect_clearance'))
        self.assertNotIn('/normal',repr(result))

    def test_exact_character_fd_and_mapping_detected(self):
        for relative in ('fd/3','map_files/1000-2000'):
            self.setUp()
            self.reader.rows[relative]=('/dev/dri/renderD132',stat.S_IFCHR,(226<<20)|132,CORE)
            self.assertTrue(self.scan().target_character_seen)

    def test_dma_exporter_any_name_and_dma_mapping_name(self):
        for info in (CORE+b'exp_name: amdgpu\n',CORE+b'exp_name: unrelated_exporter\n',CORE+b'exp_name:\n'):
            self.reader.rows['fd/3']=('/anonymous-buffer',stat.S_IFREG,0,info)
            self.assertTrue(self.scan().dma_buf_seen)
        self.reader.rows['fd/3']=('/normal/file',stat.S_IFREG,0,CORE)
        self.reader.rows['map_files/1000-2000']=('/dmabuf:private-name',stat.S_IFREG,0,b'')
        self.assertTrue(self.scan().dma_buf_seen)

    def test_fdinfo_core_missing_duplicate_malformed_and_inode_mismatch(self):
        samples = [CORE.replace(line,b'') for line in CORE.splitlines(keepends=True)]
        samples += [CORE+line for line in CORE.splitlines(keepends=True)]
        samples += [CORE.replace(b'pos:\t0', b'pos:\t9223372036854775808'),
                    CORE.replace(b'flags:\t02000000',b'flags:\t08'),
                    CORE.replace(b'mnt_id:\t12',b'mnt_id:\t0'),
                    CORE.replace(b'ino:\t2',b'ino:\t3'),
                    CORE.replace(b'ino:\t2',b'ino:\t18446744073709551616')]
        for raw in samples:
            with self.subTest(raw=raw):
                self.reader.rows['fd/3']=('/normal/file',stat.S_IFREG,0,raw)
                self.assertFalse(self.scan().complete)

    def test_repeated_resource_fields_allowed_and_dma_survives_bad_core(self):
        self.reader.rows['fd/3']=('/normal/file',stat.S_IFREG,0,CORE+b'tfd: 7 events: 19\ntfd: 8 events: 19\n')
        self.assertTrue(self.scan().complete)
        self.reader.rows['fd/3']=('/normal/file',stat.S_IFREG,0,b'pos: invalid\nexp_name: anything\n')
        result=self.scan()
        self.assertFalse(result.complete)
        self.assertTrue(result.dma_buf_seen)

    def test_anonymous_mapping_and_unknown_inode_are_unclassified(self):
        for link in ('anon_inode:[unknown]','/memfd:unknown (deleted)','[anonymous]'):
            self.reader.rows['map_files/1000-2000']=(link,stat.S_IFREG,0,b'')
            self.assertTrue(self.scan().unclassified_seen)

    def test_read_failure_and_changed_identity_incomplete(self):
        for failure in ('link','stat','fdinfo'):
            self.reader.fail=failure
            result=self.scan()
            self.assertFalse(result.complete)
            self.assertNotIn('private',repr(result))
        self.reader.fail=''
        self.reader.change=True
        self.assertEqual(self.scan().code,'resources_changed')

    def test_bad_peer_and_deadline_stop_before_snapshot(self):
        self.peer.revalidate.return_value=False
        self.assertFalse(self.scan().complete)
        self.assertEqual(self.reader.snapshots,0)
        self.peer.revalidate.return_value=self.identity
        self.now=20
        self.assertEqual(self.scan().code,'deadline_expired')
        self.assertEqual(self.reader.snapshots,0)

    def test_invalid_fdinfo_and_inventory_rejected(self):
        for info in (b'',b'bad-line',b'x'*16385,b'pos: 0\n'*257):
            self.reader.rows['fd/3']=('/normal/file',stat.S_IFREG,0,info)
            self.assertFalse(self.scan().complete)
        self.reader.entries=lambda fd,directory:('../escape',)
        self.assertFalse(self.scan().complete)
        self.reader.entries=lambda fd,directory:tuple(str(i) for i in range(4097))
        self.assertFalse(self.scan().complete)

    def test_known_character_evidence_preserved_on_later_error(self):
        self.reader.rows['fd/3']=('/dev/dri/renderD132',stat.S_IFCHR,(226<<20)|132,b'bad')
        result=self.scan()
        self.assertFalse(result.complete)
        self.assertTrue(result.target_character_seen)

    def test_fdinfo_and_mapping_list_drift_make_observation_incomplete(self):
        original=self.reader.fdinfo
        self.reader.fdinfo=lambda fd,number:original(fd,number)+(
            b'pos_extra: 1\n' if self.reader.snapshots==2 else b'')
        self.assertEqual(self.scan().code,'resources_changed')
        self.setUp()
        original_entries=self.reader.entries
        def entries(fd,directory):
            names=original_entries(fd,directory)
            return () if directory=='map_files' and self.reader.snapshots==2 else names
        self.reader.entries=entries
        self.assertEqual(self.scan().code,'resources_changed')

    def test_final_peer_revalidation_failure_retains_observations(self):
        self.peer.revalidate.side_effect=[self.identity,self.identity,ValueError('peer changed')]
        self.assertFalse(self.scan().complete)
        self.assertEqual(self.reader.snapshots,2)

    def test_typed_unchanged_peer_identity_and_procfd_required(self):
        self.peer.revalidate.return_value=None
        self.assertFalse(self.scan().complete)
        self.assertEqual(self.reader.snapshots,0)
        self.peer.revalidate.side_effect=[self.identity,replace(self.identity,starttime=88)]
        self.assertFalse(self.scan().complete)
        self.setUp()
        def changed_handle():
            self.peer.proc_fd=13
            return self.identity
        self.peer.revalidate.side_effect=changed_handle
        self.assertFalse(self.scan().complete)
        self.assertEqual(self.reader.snapshots,0)


if __name__=='__main__':unittest.main()
