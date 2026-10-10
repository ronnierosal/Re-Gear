"""Module-level snapshot enrichment seam; main.py wiring belongs the director."""
import asyncio
import unittest
from unittest.mock import Mock
from regear.adapters.steamos.usb4_attachment_observer import Usb4AttachmentObservation
from regear.delivery.usb4_waiting_observation import Usb4WaitingObservation
class SnapshotFacadeTests(unittest.IsolatedAsyncioTestCase):
    async def test_additive_snapshot_and_serialized_nonce(self):
        observer=Mock();observer.observe.return_value=Usb4AttachmentObservation('unauthorized',('private',))
        facade=Usb4WaitingObservation(observer);snapshot={'schema_version':3,'existing':{'value':True}}
        a,b=await asyncio.gather(facade.enrich_snapshot(snapshot),facade.enrich_snapshot(snapshot))
        self.assertEqual(a,b);self.assertNotIn('usb4_waiting',snapshot);self.assertEqual(a['existing'],snapshot['existing'])
        self.assertEqual(observer.observe.call_count,2)
    async def test_failed_observation_never_reuses_public_key(self):
        observer=Mock();facade=Usb4WaitingObservation(observer)
        observer.observe.return_value=Usb4AttachmentObservation('unauthorized',('private',))
        self.assertIsNotNone((await facade.enrich_snapshot({}))['usb4_waiting']['notice_key'])
        observer.observe.side_effect=OSError('private path')
        self.assertEqual((await facade.enrich_snapshot({}))['usb4_waiting'],{'schema_version':1,'state':'unknown','notice_key':None})
    async def test_cancellation_keeps_read_serialized_until_bounded_completion(self):
        import threading
        started=threading.Event();release=threading.Event();calls=[]
        def read():
            calls.append(1);started.set();release.wait(.5)
            return Usb4AttachmentObservation('unknown')
        observer=Mock();observer.observe.side_effect=read;facade=Usb4WaitingObservation(observer)
        first=asyncio.create_task(facade.enrich_snapshot({}))
        while not started.is_set(): await asyncio.sleep(.001)
        first.cancel();second=asyncio.create_task(facade.enrich_snapshot({}))
        await asyncio.sleep(.01);self.assertEqual(len(calls),1)
        release.set()
        with self.assertRaises(asyncio.CancelledError): await first
        self.assertEqual((await second)['usb4_waiting']['state'],'unknown')
