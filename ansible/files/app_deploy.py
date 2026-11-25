"""Patch only three existing facility Deployments. No Secret/PVC/Service changes.

Runs on the facility with Python's standard library and k3s kubectl.
Snapshots stay root-readable on the facility; they may contain inline env values.
"""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

NAMESPACE = 'coldguard'
SERVICES = ('collector', 'controller', 'field-web')
MODULES = {'collector': 'collector.data_collector',
           'controller': 'controller.controller_svc',
           'field-web': 'field_web.field_web'}
ROOT = Path('/var/lib/coldguard/app-deployments')
IMAGE = re.compile(r'^[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/'
                   r'coldguard-prod-(collector|controller|field-web)'
                   r'(?::[0-9a-f]{40}|@sha256:[0-9a-f]{64})$')


class DeployError(Exception):
    pass


class Kube:
    def __init__(self, argv):
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
            raise DeployError('kubectl must be a nonempty argv list')
        self.argv = argv

    def run(self, *args, timeout=60):
        proc = subprocess.run(self.argv + ['-n', NAMESPACE] + list(args),
                              text=True, capture_output=True, timeout=timeout)
        if proc.returncode:
            # kubectl patch errors can include submitted env values: keep details private.
            raise DeployError('kubectl command failed: ' + ' '.join(args[:2]))
        return proc.stdout

    def get(self, kind, name):
        return json.loads(self.run('get', kind, *([name] if name else []), '-o', 'json'))

    def patch(self, name, body):
        return json.loads(self.run('patch', 'deployment', name, '--type=strategic',
                                   '-p', json.dumps(body), '-o', 'json'))

    def rollout(self, name, timeout):
        self.run('rollout', 'status', 'deployment/' + name,
                 '--timeout=' + str(timeout) + 's', timeout=timeout + 30)


def container(deployment, name):
    found = [c for c in deployment['spec']['template']['spec']['containers'] if c['name'] == name]
    if len(found) != 1:
        raise DeployError('Expected container missing: ' + name)
    return found[0]


def validate_images(images):
    if not isinstance(images, dict) or set(images) != set(SERVICES):
        raise DeployError('Provide all three app_images; central-worker is not a facility target')
    for name, image in images.items():
        match = IMAGE.fullmatch(image) if isinstance(image, str) else None
        if not match or match.group(1) != name:
            raise DeployError('Use matching ECR repository and full commit SHA or digest: ' + name)


def check_live(kube, name):
    obj = kube.get('deployment', name)
    spec = obj['spec']
    if spec.get('replicas', 1) != 1 or spec.get('strategy', {}).get('type') != 'Recreate':
        raise DeployError('Expected replicas=1 and strategy=Recreate: ' + name)
    container(obj, name)
    if spec.get('paused'):
        raise DeployError('Deployment is paused: ' + name)
    status = obj.get('status', {})
    if status.get('observedGeneration', 0) < obj['metadata']['generation'] or status.get('updatedReplicas', 0) != 1 or status.get('readyReplicas', 0) != 1 or status.get('availableReplicas', 0) != 1:
        raise DeployError('Deployment must be stable and Ready before changing: ' + name)
    pod = spec['template']['spec']
    for volume in pod.get('volumes', []):
        if 'persistentVolumeClaim' in volume:
            pvc = kube.get('pvc', volume['persistentVolumeClaim']['claimName'])
            if pvc.get('status', {}).get('phase') != 'Bound':
                raise DeployError('PVC not Bound: ' + name)
        for field, kind in (('configMap', 'configmap'), ('secret', 'secret')):
            if field in volume:
                ref = volume[field]
                kube.run('get', kind, ref.get('name') or ref.get('secretName'), '-o', 'name')
    for c in pod.get('containers', []):
        for source in c.get('envFrom', []):
            for key, kind in (('configMapRef', 'configmap'), ('secretRef', 'secret')):
                if key in source:
                    kube.run('get', kind, source[key]['name'], '-o', 'name')
        for env in c.get('env', []):
            for key, kind in (('configMapKeyRef', 'configmap'), ('secretKeyRef', 'secret')):
                ref = env.get('valueFrom', {}).get(key)
                if ref:
                    kube.run('get', kind, ref['name'], '-o', 'name')
    return obj


def desired_template(obj, name, image):
    template = copy.deepcopy(obj['spec']['template'])
    target = container({'spec': {'template': template}}, name)
    target.update(image=image, command=['python', '-m', MODULES[name]], args=[])
    return template


def same_template(left, right):
    # Kubernetes omits empty args on read-back. Treat missing and [] as equivalent.
    def normalize(value):
        value = copy.deepcopy(value)
        for item in value['spec']['containers']:
            if not item.get('args'):
                item.pop('args', None)
        return value
    return normalize(left) == normalize(right)


def apply_one(kube, name, previous, target_template, timeout):
    # Keep live env, security settings, volumes and probes unchanged. Fail on concurrent edits.
    current = kube.get('deployment', name)
    if current['metadata']['resourceVersion'] != previous['metadata']['resourceVersion']:
        raise DeployError('Deployment changed since preflight; rerun plan: ' + name)
    target = container({'spec': {'template': target_template}}, name)
    patch = {'metadata': {'resourceVersion': current['metadata']['resourceVersion']},
             'spec': {'template': {'spec': {'containers': [{
                 'name': name, 'image': target['image'],
                 'command': target.get('command'), 'args': target.get('args')} ]}}}}
    kube.patch(name, patch)
    kube.rollout(name, timeout)


def write_private(path, data):
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        json.dump(data, output, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def load_backup(path):
    root = ROOT.resolve()
    target = Path(path).resolve()
    if target.parent != root:
        raise DeployError('Backup must be a direct child of ' + str(root))
    data = json.loads((target / 'snapshot.json').read_text(encoding='utf-8'))
    if data.get('namespace') != NAMESPACE or set(data.get('before', {})) != set(SERVICES):
        raise DeployError('Invalid backup')
    return target, data


def rollback(kube, directory, data, timeout):
    restored = []
    # Reverse order; restore only this run's image / command / args.
    for name in reversed(data.get('attempted', [])):
        current = kube.get('deployment', name)
        old = data['before'][name]
        original = old['spec']['template']
        live = current['spec']['template']
        if same_template(live, original):
            continue
        # Ignore Deployment controller's pod-template hash annotation, if any.
        expected = data['targets'][name]
        if not same_template(live, expected):
            raise DeployError('Concurrent template change; manual review required: ' + name)
        apply_one(kube, name, current, original, timeout)
        restored.append(name)
    data['restored'] = restored
    write_private(directory / 'snapshot.json', data)
    return restored


def execute(request, kube):
    mode = request.get('mode', 'plan')
    timeout = int(request.get('timeout', 180))
    if mode not in ('plan', 'apply', 'rollback') or not 30 <= timeout <= 1800:
        raise DeployError('Invalid mode or timeout')
    if mode == 'rollback':
        directory, data = load_backup(request.get('backup_dir', ''))
        restored = rollback(kube, directory, data, timeout)
        return {'changed': bool(restored), 'mode': mode, 'restored': restored, 'backup_dir': str(directory)}
    images = request.get('images', {})
    validate_images(images)
    # Do not compete with an autoscaler changing these three Deployments.
    hpas = kube.get('hpa', '')
    if any(h.get('spec', {}).get('scaleTargetRef', {}).get('name') in SERVICES
           and h.get('spec', {}).get('scaleTargetRef', {}).get('kind') == 'Deployment'
           for h in hpas.get('items', [])):
        raise DeployError('Facility app has HPA; coordinate scaling before deployment')
    before = {name: check_live(kube, name) for name in SERVICES}
    targets = {name: desired_template(before[name], name, images[name]) for name in SERVICES}
    changes = [name for name in SERVICES if not same_template(before[name]['spec']['template'], targets[name])]
    summary = {'mode': mode, 'changed': False, 'would_change': changes,
               'images': {name: {'before': container(before[name], name)['image'],
                                 'after': images[name]} for name in SERVICES}}
    if mode == 'plan' or not changes:
        return summary
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory = ROOT / (stamp + '-' + uuid.uuid4().hex[:8])
    directory.mkdir(mode=0o700, parents=True)
    os.chmod(directory, 0o700)
    data = {'namespace': NAMESPACE, 'before': before, 'targets': targets, 'attempted': []}
    write_private(directory / 'snapshot.json', data)
    try:
        for name in changes:
            data['attempted'].append(name)
            write_private(directory / 'snapshot.json', data)
            apply_one(kube, name, before[name], targets[name], timeout)
    except Exception:
        # Keep evidence on facility. Do not continue to the next service.
        try:
            rollback(kube, directory, data, timeout)
            outcome = 'rollback succeeded'
        except Exception:
            outcome = 'rollback incomplete; operator review required'
        raise DeployError('Deployment failed; ' + outcome + '; backup_dir=' + str(directory)) from None
    summary.update(changed=True, backup_dir=str(directory))
    return summary


def main():
    import fcntl  # facility runs Linux; imported here so unit tests also run on Windows.
    request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    os.umask(0o077)
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Refuse concurrent executions of this helper on the same facility.
    with (ROOT / '.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = execute(request, Kube(request.get('kubectl', ['/usr/local/bin/k3s', 'kubectl'])))
        except (DeployError, subprocess.TimeoutExpired, ValueError, OSError, KeyError) as exc:
            print(json.dumps({'changed': False, 'error': str(exc) if isinstance(exc, DeployError) else type(exc).__name__}), flush=True)
            return 1
    print(json.dumps(result), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
