"""No SSH, Kubernetes, AWS or production state is accessed."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('app_deploy', Path(__file__).parents[1] / 'files/app_deploy.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


def deployment(name):
    return {'metadata': {'resourceVersion': '1', 'generation': 1},
            'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'}, 'template': {
                'metadata': {'labels': {'app': name}}, 'spec': {
                    'securityContext': {'runAsUser': 10001, 'fsGroup': 10001},
                    'volumes': [{'name': 'state', 'persistentVolumeClaim': {'claimName': name + '-state'}}],
                    'containers': [{'name': name, 'image': 'ghcr.io/example/' + name + ':old',
                        'command': ['python', '-m', app.MODULES[name]],
                        'env': [{'name': 'STATE_DB', 'value': '/var/lib/coldguard/' + name + '.db'},
                                {'name': 'PASSWORD', 'valueFrom': {'secretKeyRef': {'name': 'existing', 'key': 'password'}}}],
                        'volumeMounts': [{'name': 'state', 'mountPath': '/var/lib/coldguard'}],
                        'readinessProbe': {'tcpSocket': {'port': 8080}}}]}}},
            'status': {'observedGeneration': 1, 'updatedReplicas': 1, 'readyReplicas': 1, 'availableReplicas': 1}}


class FakeKube:
    def __init__(self):
        self.items = {name: deployment(name) for name in app.SERVICES}
        self.patches = []
        self.failure = None
        self.hpas = []

    def get(self, kind, name):
        if kind == 'hpa':
            return {'items': self.hpas}
        if kind == 'pvc':
            return {'status': {'phase': 'Bound'}}
        return copy.deepcopy(self.items[name])

    def run(self, *args, **kwargs):
        return 'resource exists'

    def patch(self, name, body):
        live = self.items[name]
        if live['metadata']['resourceVersion'] != body['metadata']['resourceVersion']:
            raise app.DeployError('conflict')
        self.patches.append(name)
        target = app.container(live, name)
        changes = body['spec']['template']['spec']['containers'][0]
        for key in ('image', 'command', 'args'):
            if changes[key] is None or (key == 'args' and not changes[key]):
                target.pop(key, None)
            else:
                target[key] = changes[key]
        live['metadata']['resourceVersion'] = str(int(live['metadata']['resourceVersion']) + 1)
        return copy.deepcopy(live)

    def rollout(self, name, timeout):
        if self.failure == name:
            self.failure = None
            raise app.DeployError('rollout timed out')


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.kube = FakeKube()
        self.images = {s: '123456789012.dkr.ecr.ap-northeast-2.amazonaws.com/coldguard-prod-' + s + '@sha256:' + 'a' * 64 for s in app.SERVICES}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root_patch = patch.object(app, 'ROOT', Path(self.tmp.name))
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def request(self, mode='plan'):
        return {'mode': mode, 'images': self.images}

    def test_plan_never_patches_or_creates_snapshots(self):
        result = app.execute(self.request(), self.kube)
        self.assertFalse(result['changed'])
        self.assertEqual(result['would_change'], list(app.SERVICES))
        self.assertEqual(self.kube.patches, [])
        self.assertEqual(list(app.ROOT.iterdir()), [])

    def test_apply_preserves_runtime_settings_and_is_idempotent(self):
        before = copy.deepcopy(self.kube.items)
        result = app.execute(self.request('apply'), self.kube)
        self.assertTrue(result['changed'])
        self.assertEqual(self.kube.patches, list(app.SERVICES))
        for name in app.SERVICES:
            expected = app.desired_template(before[name], name, self.images[name])
            self.assertTrue(app.same_template(self.kube.items[name]['spec']['template'], expected))
            self.assertEqual(self.kube.items[name]['spec']['strategy'], before[name]['spec']['strategy'])
        self.assertFalse(app.execute(self.request('apply'), self.kube)['changed'])

    def test_failure_stops_later_service_and_restores_earlier_services(self):
        before = copy.deepcopy(self.kube.items)
        self.kube.failure = 'controller'
        with self.assertRaisesRegex(app.DeployError, 'rollback succeeded'):
            app.execute(self.request('apply'), self.kube)
        self.assertNotIn('field-web', self.kube.patches)
        for name in app.SERVICES:
            self.assertTrue(app.same_template(self.kube.items[name]['spec']['template'], before[name]['spec']['template']))

    def test_explicit_rollback_restores_previous_images(self):
        before = copy.deepcopy(self.kube.items)
        result = app.execute(self.request('apply'), self.kube)
        undone = app.execute({'mode': 'rollback', 'backup_dir': result['backup_dir']}, self.kube)
        self.assertTrue(undone['changed'])
        for name in app.SERVICES:
            self.assertTrue(app.same_template(self.kube.items[name]['spec']['template'], before[name]['spec']['template']))

    def test_rollback_refuses_unrelated_runtime_changes(self):
        result = app.execute(self.request('apply'), self.kube)
        app.container(self.kube.items['field-web'], 'field-web')['env'].append({'name': 'OTHER', 'value': 'new'})
        with self.assertRaisesRegex(app.DeployError, 'Concurrent template'):
            app.execute({'mode': 'rollback', 'backup_dir': result['backup_dir']}, self.kube)

    def test_wrong_repository_rejected_before_any_patch(self):
        self.images['collector'] = self.images['controller']
        with self.assertRaises(app.DeployError):
            app.execute(self.request('apply'), self.kube)
        self.assertEqual(self.kube.patches, [])

    def test_recreate_and_ready_are_required_before_any_patch(self):
        self.kube.items['controller']['spec']['strategy']['type'] = 'RollingUpdate'
        with self.assertRaises(app.DeployError):
            app.execute(self.request('apply'), self.kube)
        self.assertEqual(self.kube.patches, [])

    def test_hpa_conflict_is_rejected(self):
        self.kube.hpas = [{'spec': {'scaleTargetRef': {'name': 'collector', 'kind': 'Deployment'}}}]
        with self.assertRaises(app.DeployError):
            app.execute(self.request('apply'), self.kube)
        self.assertEqual(self.kube.patches, [])


if __name__ == '__main__':
    unittest.main()
