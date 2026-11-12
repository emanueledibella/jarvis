"""Exercise the Linux deployment with synthetic data and no container network."""

import argparse
import json
import subprocess
import time
import uuid


def docker(*arguments, check=True):
    return subprocess.run(["docker", *arguments], check=check, capture_output=True, text=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-image", default="jarvis-remote-core:dev")
    parser.add_argument("--worker-image", default="jarvis-document-worker:dev")
    options = parser.parse_args()
    name = "jarvis-qa-" + uuid.uuid4().hex[:12]
    core, worker, data, socket = name + "-core", name + "-worker", name + "-data", name + "-socket"
    restrictions = ["--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "128", "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m"]  # nosec B108 -- Private container tmpfs, never a host temporary pathname.
    try:
        docker("run", "-d", "--name", worker, *restrictions, "--memory", "512m", "-v", socket + ":/run/jarvis-worker", options.worker_image)
        for _ in range(100):
            if docker("inspect", "--format", "{{.State.Health.Status}}", worker) == "healthy":
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Isolated parser did not become healthy.")
        docker("run", "-d", "--name", core, *restrictions, "--memory", "1536m", "-v", data + ":/data", "-v", socket + ":/run/jarvis-worker",
               "-e", "JARVIS_REMOTE_PUBLIC_URL=https://jarvis.invalid", "-e", "JARVIS_REMOTE_DOCUMENT_WORKER_SOCKET=/run/jarvis-worker/parser.sock", options.core_image)
        for _ in range(100):
            if docker("inspect", "--format", "{{.State.Health.Status}}", core) == "healthy":
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Remote core did not become healthy.")
        program = r'''
import asyncio,base64,json,os,urllib.request,urllib.error
from pathlib import Path
from jarvis.remote_store import RemoteStore
async def code():
    store=RemoteStore(Path('/data'));await store.open()
    try:return await store.pairing_code(owner=True)
    finally:await store.close()
def request(path,body=None,token=''):
    headers={'Host':'jarvis.invalid','Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    req=urllib.request.Request('http://127.0.0.1:8765'+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
    return json.load(urllib.request.urlopen(req,timeout=30))
try:request('/api/tasks');raise AssertionError('Anonymous core access')
except urllib.error.HTTPError as error:assert error.code==401
paired=request('/remote/v1/pair',{'code':asyncio.run(code()),'name':'Synthetic deployment QA','platform':'android'})
token=paired['access_token']
settings=request('/api/settings',token=token)
for flag in ('voice_enabled','wake_enabled'):
    assert settings['values'][flag] is True, 'Companion voice must not be forced off by the core image: '+flag
    assert flag not in settings['locked'], 'Companion voice must remain configurable: '+flag
phone=request('/api/telephony/status',token=token)
assert phone['hosting']=='remote' and phone['dependencies'] is None,phone
assert phone['requirements'] and not phone['ready'],phone
try:request('/api/telephony/start',{},token);raise AssertionError('Unconfigured telephony was activated')
except urllib.error.HTTPError as error:
    assert error.code==400
    detail=json.load(error)['detail']
    assert 'Twilio account SID' in detail and 'telephony_account_id' not in detail,detail
assert request('/api/settings',token=token)['values']['telephony_enabled'] is False
session=request('/api/voice/session',token=token)
source=request('/api/documents',{'name':'fixture.txt','content':base64.b64encode(b'chosen synthetic source').decode(),'scope':'personal','privacy_revision':session['revision'],'session_id':session['client_session_id']},token)
assert source['isolation']=='isolated_container_worker',source
detail=request('/api/documents/'+source['id']+'?scope=personal',token=token)
assert detail['parts'][0]['text']=='chosen synthetic source',detail
assert os.getuid()==10001
assert not Path('/var/run/docker.sock').exists()
request('/remote/v1/devices/'+paired['device_id']+'/revoke',{},token)
try:request('/api/tasks',token=token);raise AssertionError('Revoked device accepted')
except urllib.error.HTTPError as error:assert error.code==401
print('Core authentication, companion voice settings, remote telephony preflight, isolated parsing, non-root execution and revocation passed.')
'''
        print(docker("exec", core, "/app/.venv/bin/python", "-c", program))
        info = json.loads(docker("inspect", worker))[0]
        assert info["HostConfig"]["NetworkMode"] == "none"
        assert all(mount["Destination"] != "/data" for mount in info["Mounts"])
        print("Parser has no network, core data or provider credentials.")
    finally:
        docker("rm", "-f", core, worker, check=False)
        docker("volume", "rm", data, socket, check=False)


if __name__ == "__main__":
    main()
