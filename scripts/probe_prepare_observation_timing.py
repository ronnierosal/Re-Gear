"""Read-only trusted collector timing, not a session launch budget proof."""
import math
import os
from pathlib import Path
import platform
import sys
import time
import json

if Path(__file__).name!='__main__.py':sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))

from hdm.delivery.device_receive_layout_cache import DmaReceiveLayoutCache,MAX_BTF_BYTES
from hdm.adapters.steamos.device_receive_symbols import read_receive_symbols
from scripts.dma_fixture_identity import collect_identity
from scripts.probe_paired_owner_death import boot_hash
from scripts.probe_receive_pin_fixture import _error_fields


def read_btf():
    with open('/sys/kernel/btf/vmlinux','rb') as source:
        return source.read(MAX_BTF_BYTES+1)


def measure(*,identity=collect_identity,btf=read_btf,symbols=read_receive_symbols,
            boot=boot_hash,clock=time.monotonic,cache=None,stage=lambda value:None):
    """Exactly three fresh collections; start timestamps remain local only."""
    cache=DmaReceiveLayoutCache() if cache is None else cache
    previous=None
    def now():
        nonlocal previous
        value=clock()
        if (type(value) not in (int,float) or not math.isfinite(value) or value<0
                or (previous is not None and value<previous)):
            raise ValueError('monotonic collection clock unavailable')
        previous=value
        return value
    start=now();reference=None;samples=[]
    for _ in range(3):
        collected_at=now()
        if collected_at-start>=30:raise TimeoutError('observation sampling deadline')
        stage('boot_before');before=boot()
        stage('identity');tick=now();observed=identity();identity_end=now()
        stage('btf');raw=btf();layout=cache.parse(raw,pointer_size=8);btf_end=now()
        stage('symbols');symbol_value=symbols();symbols_end=now()
        stage('boot_after');after=boot();finished=now()
        if finished-start>=30:raise TimeoutError('observation sampling deadline')
        # Address values are compared in memory and never included in output.
        evidence=(before,observed,layout,symbol_value)
        if before!=after or (reference is not None and evidence!=reference):
            return dict(state='changed',samples_completed=len(samples),
                session_launch_budget_verified=False,launch_authorized=False,disconnect_clearance=False)
        reference=evidence
        samples.append(dict(total_seconds=finished-collected_at,identity_seconds=identity_end-tick,
            btf_seconds=btf_end-identity_end,symbol_seconds=symbols_end-btf_end))
    return dict(state='ready',samples_completed=3,samples=samples,total_seconds=now()-start,
        each_collector_within_five_seconds=all(sample['total_seconds']<5 for sample in samples),
        session_launch_budget_verified=False,launch_authorized=False,disconnect_clearance=False)


def run_probe(*,stage=lambda value:None):
    stage('preflight')
    if platform.system()!='Linux' or platform.machine()!='x86_64' or os.geteuid()!=0:
        raise ValueError('root Linux x86_64 required')
    return measure(stage=stage)


def run_launch_probe(*,stage=lambda value:None):
    """Compare the lean hardware collector; not the authenticated handshake."""
    stage('preflight')
    if platform.system()!='Linux' or platform.machine()!='x86_64' or os.geteuid()!=0:
        raise ValueError('root Linux x86_64 required')
    from hdm.adapters.steamos.prepare_hardware_identity import PrepareHardwareIdentitySource
    source=PrepareHardwareIdentitySource()
    result=measure(identity=lambda:source.collect(deadline=time.monotonic()+2),stage=stage)
    result['collector']='launch_hardware'
    result['authenticated_session_observed']=False
    return result


def main():
    if sys.argv[1:] not in (['--read-only-observation'],['--read-only-launch-observation']):
        raise SystemExit('Explicit read-only observation mode required')
    current=['startup']
    run=run_launch_probe if sys.argv[1:] == ['--read-only-launch-observation'] else run_probe
    try:report=run(stage=lambda value:current.__setitem__(0,value))
    except Exception as error:
        report=dict(state='error',stage=current[0],**_error_fields(error),
            session_launch_budget_verified=False,launch_authorized=False,disconnect_clearance=False)
    report.update(read_only=True,player_mutation=False)
    print(json.dumps(report,sort_keys=True))
    return 0 if report['state']=='ready' else 1


if __name__=='__main__':raise SystemExit(main())
