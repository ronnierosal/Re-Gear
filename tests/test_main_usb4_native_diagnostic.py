import asyncio
import unittest
from unittest.mock import Mock,patch

class MainDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_mini_constructor_to_rpc_both_profiles(self):
        from tests.test_main_process_delivery import load_main_module
        from regear.adapters.steamos.host import HostRecord
        from regear.delivery import build_profile_config
        for profile in ('development','production'):
            with self.subTest(profile=profile),patch.object(build_profile_config,'BUILD_PROFILE',profile):
                module=load_main_module(real_dock_gate=True,real_host_admission=True)
                with patch('regear.adapters.steamos.host.HostDiscovery.scan',return_value=HostRecord('GPD','G1617-01','unknown')),patch.object(module,'DeviceAuthorizationFacade') as auth,patch.object(module,'RootOwnedRuntimeState') as store,patch.object(module,'SleepGuardController') as lease,patch.object(module,'DiagnosticsApi'),patch.object(module,'read_usb4_native_diagnostic',return_value={'code':'fixture.read'}) as read,patch.object(module.asyncio,'create_task') as schedule,patch.object(module.Plugin,'_reconcile_device_authorization_disconnect') as reconcile:
                    plugin=module.Plugin()
                    result=await plugin.get_usb4_native_diagnostic()
                    if profile=='development':self.assertEqual('fixture.read',result['code']);read.assert_called_once_with()
                    else:read.assert_not_called();self.assertFalse(result['available'])
                    for spy in (auth,store,lease,schedule,reconcile):spy.assert_not_called()
                    denied=await plugin.confirm_device_authorization('a'*32,True,'authorize')
                    self.assertEqual('runtime.observation_only',denied['code'])
    async def test_unloading_and_extra_arguments_never_read(self):
        from tests.test_main_process_delivery import load_main_module
        module=load_main_module(real_dock_gate=True,real_host_admission=True)
        from regear.adapters.steamos.host import HostRecord
        with patch('regear.adapters.steamos.host.HostDiscovery.scan',return_value=HostRecord('GPD','G1617-01','unknown')),patch.object(module,'DiagnosticsApi'),patch.object(module,'read_usb4_native_diagnostic') as read:
            plugin=module.Plugin();plugin._unloading=True
            self.assertFalse((await plugin.get_usb4_native_diagnostic())['available'])
            with self.assertRaises(TypeError):await plugin.get_usb4_native_diagnostic(destination='arbitrary')
            read.assert_not_called()

if __name__=='__main__':unittest.main()
