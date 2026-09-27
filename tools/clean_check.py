#!/usr/bin/env python3
"""Copy all nonignored source (including untracked files), bootstrap/build/install locally.

This integration check retains its copy and command logs. Only bootstrap may use
network. No existing directories are removed or source files altered.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from verify import fingerprint
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    output=(args.output or ROOT/'build'/('clean-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))).resolve()
    if output.exists(): raise SystemExit('Refusing to reuse an existing clean-check directory')
    output.mkdir(parents=True);source=output/'source';source.mkdir();install=output/'installed'
    report={'status':'RUNNING','source_before':fingerprint(),'output':str(output),'steps':[]}
    lock=ROOT/'build/quarry-activity.lock';lock.parent.mkdir(exist_ok=True)
    with lock.open('a+') as handle:
        try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise SystemExit('Quarry verification/benchmark activity lock is held')
        paths=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
        copied={}
        for name in sorted(set(filter(None,paths))):
            original=ROOT/name
            if not original.is_file(): continue
            destination=source/name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,destination)
            copied[name]=hashlib.sha256(destination.read_bytes()).hexdigest()
        report['copied_source_files']=copied
        # A new virtual environment is provisioned by the documented bootstrap;
        # reuse only verified header cache, never any object or native binary.
        cache=source/'.deps/include';cache.mkdir(parents=True)
        for name in ('json.hpp','doctest.h'): shutil.copy2(ROOT/'.deps/include'/name,cache/name)
        report['bootstrap_header_cache']='Pinned SHA256-checked headers copied; all native build products created afresh'
        def run(name,command,cwd=source,env=None):
            path=output/(name+'.log')
            with path.open('w') as log:
                log.write('cwd: '+str(cwd)+'\ncommand: '+json.dumps([str(x) for x in command])+'\n\n');log.flush()
                process=subprocess.run([str(x) for x in command],cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
            report['steps'].append({'name':name,'command':[str(x) for x in command],'cwd':str(cwd),'environment':env,'exit_code':process.returncode,'log':str(path)})
            (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
            if process.returncode: raise RuntimeError(name+' failed; see '+str(path))
        try:
            run('bootstrap',['python3.12','tools/bootstrap.py'])
            run('configure',['.venv/bin/cmake','--preset','release'])
            run('build',['.venv/bin/cmake','--build','--preset','release'])
            run('native',['.venv/bin/ctest','--preset','release'])
            run('install',['.venv/bin/cmake','--install','build/release','--prefix',install])
            minimal={'PATH':'/usr/bin:/bin','LC_ALL':'C'}
            native_cmake=next((source/'.venv').glob('lib/python*/site-packages/cmake/data/bin/cmake'))
            run('native-core-configure',[native_cmake,'-S',source,'-B',output/'core-only','-DCMAKE_BUILD_TYPE=Release'],cwd=output,env=minimal)
            run('native-core-build',[native_cmake,'--build',output/'core-only','--target','quarry','quarry_core','-j','4'],cwd=output,env=minimal)
            run('native-core-demo',[output/'core-only/quarry','demo'],cwd=output,env=minimal)
            consumer=output/'consumer.cpp'
            consumer.write_text('#include "quarry/quarry.hpp"\n#include <iostream>\nint main(int argc,char**argv){if(argc!=2)return 2;quarry::Engine e;e.load_catalog(argv[1]);auto r=e.query("SELECT COUNT(*) AS n FROM sales");std::cout<<r.rows[0][0].integer()<<"\\n";return r.rows[0][0].integer()==96?0:1;}\n')
            run('installed-core-consumer-build',['/usr/bin/c++','-std=c++20','-I'+str(install/'include'),consumer,install/'lib/libquarry_core.a','-o',output/'consumer'],cwd=output,env=minimal)
            run('installed-core-consumer',[output/'consumer',install/'share/quarry/examples/catalog.json'],cwd=output,env=minimal)
            run('installed-demo',[install/'bin/quarry','demo'],cwd=output,env=minimal)
            run('installed-explain',[install/'bin/quarry','explain','--catalog',install/'share/quarry/examples/catalog.json','--sql-file',install/'share/quarry/examples/query.sql','--engine','vector','--optimizer','on','--analyze'],cwd=output,env=minimal)
            if sys.platform=='darwin': run('runtime-libraries',['/usr/bin/otool','-L',install/'bin/quarry'],cwd=output,env=minimal)
            elif sys.platform.startswith('linux'): run('runtime-libraries',['/usr/bin/ldd',install/'bin/quarry'],cwd=output,env=minimal)
            library_log=(output/'runtime-libraries.log').read_text().lower()
            if 'python' in library_log or 'duckdb' in library_log: raise RuntimeError('Unexpected Python/DuckDB runtime dependency')
            source_unchanged=all(hashlib.sha256((source/name).read_bytes()).hexdigest()==digest for name,digest in copied.items())
            report['copied_source_unchanged']=source_unchanged
            if not source_unchanged: raise RuntimeError('Source copy changed during clean build')
            report['status']='PASS'
        except Exception as error:
            report['status']='FAIL';report['error']=str(error)
        report['source_after']=fingerprint();report['original_source_unchanged']=report['source_before']==report['source_after']
        if not report['original_source_unchanged']: report['status']='FAIL'
        report['finished_utc']=datetime.now(timezone.utc).isoformat()
        (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'status':report['status'],'summary':str(output/'summary.json')}))
        return 0 if report['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
