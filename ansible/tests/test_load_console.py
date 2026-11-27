"""load_console.py 시험. 실제 tailscale·emqtt-bench·k6·통제 API 대신 임시 폴더에 만든 가짜로 돌린다.

실제 서버, MQTT 브로커, 통제 API, tailnet에는 접속하지 않는다. 실행 흐름 시험은 리눅스에서만 돈다(콘솔이 리눅스 전용).
실행: ansible 폴더에서 python3 -m unittest discover -s tests -p 'test_load_console.py' -v
"""
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from email.header import Header
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

CONSOLE = Path(__file__).parents[1] / 'files/load_console.py'
KEY = 'test-api-key'
MQTT_PW = 'test-mqtt-password'
SUFFIX = 'tailtest.ts.net'
NAME = '김시험'


def load(env):
    """환경변수를 정한 뒤 콘솔 모듈을 새로 읽는다(모듈이 읽을 때 환경변수를 본다)."""
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_file_location('load_console_under_test', str(CONSOLE))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# 가짜 도구 (콘솔은 자식 프로세스에 환경변수를 거의 넘기지 않으므로 상태 폴더 경로를 스크립트에 박아 둔다)
# ---------------------------------------------------------------------------
FAKE_TAILSCALE = r"""#!/bin/sh
S="@STATE@"
case "$1" in
  status)
    printf '%s' '{"BackendState":"Running","MagicDNSSuffix":"@SUFFIX@","User":{"1":{"DisplayName":"한글 이름"}}}'
    ;;
  ping)
    echo "ping $*" >> "$S/args.log"
    if [ -f "$S/derp" ]; then
      echo "pong from coldguard-mqtt.@SUFFIX@ (100.64.0.5) via DERP(tok) in 41ms"
      echo "direct connection not established"
    else
      echo "pong from coldguard-mqtt.@SUFFIX@ (100.64.0.5) via 203.0.113.5:41641 in 12ms"
    fi
    ;;
esac
"""

FAKE_BENCH = r"""#!/bin/sh
S="@STATE@"
mode="$1"; shift
echo "$mode $*" >> "$S/args.log"
c=1; I=1000; prev=""
for a in "$@"; do
  case "$prev" in -c) c="$a";; -I) I="$a";; esac
  prev="$a"
done
if [ "$mode" = "pub" ]; then
  if [ -f "$S/pub_fail" ]; then sleep 1; echo "connect_fail total=$c rate=0"; exit 3; fi
  echo "1s connect_succ total=$c rate=$c.00/sec"
  echo 0 > "$S/pub_total"; total=0; t=0
  trap 'echo "${t}s pub total=$total rate=0"; exit 0' TERM
  while true; do
    sleep 1 & wait $!
    t=$((t+1)); total=$((total + c * 1000 / I)); echo $total > "$S/pub_total"
    echo "${t}s pub total=$total rate=$((c * 1000 / I)).00/sec"
  done
else
  echo "1s connect_succ total=1 rate=1.00/sec"; t=0
  trap 'p=$(cat "$S/pub_total" 2>/dev/null || echo 0); echo "${t}s recv total=$p rate=0"; exit 0' TERM
  while true; do
    sleep 1 & wait $!
    t=$((t+1)); p=$(cat "$S/pub_total" 2>/dev/null || echo 0); echo "${t}s recv total=$p rate=0"
  done
fi
"""

FAKE_K6 = r"""#!/bin/sh
S="@STATE@"
env | grep -E '^(LOAD_|K6_)' | sort > "$S/k6_env.log"
dur=$(echo "$LOAD_DURATION" | tr -d s)
finish() {
  printf '{"reqs": %s, "rps": %s, "failed_rate": 0.0, "p95_ms": 120.5, "thresholds": {}}' "$((dur * LOAD_RPS))" "$LOAD_RPS" > "$LOAD_SUMMARY_FILE"
  echo "<html><body>report</body></html>" > "$K6_WEB_DASHBOARD_EXPORT"
}
trap 'finish; exit 105' INT
t=0
while [ $t -lt $dur ]; do
  if [ -f "$S/k6_abort" ] && [ $t -ge 1 ]; then
    echo 'level=error msg="thresholds were crossed; at least one has abortOnFail enabled, stopping test prematurely"'
    finish; exit 99
  fi
  sleep 1 & wait $!
  t=$((t+1)); echo "running (${t}s)"
done
finish
exit 0
"""

API_STATE = {'late': 0.0, 'status': 200}


class FakeApi(BaseHTTPRequestHandler):
    """통제 API /api/v1/devices 흉내. 냉동고 5대는 정상, fz09는 처음부터 늦은 장비."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.headers.get('Authorization') != 'Bearer ' + KEY:
            code, body = 401, b''
        elif API_STATE['status'] != 200:
            code, body = API_STATE['status'], b''
        else:
            devs = [{'site_id': 'site01', 'device_id': 'fz0%d' % i, 'age_sec': 0.8 + API_STATE['late']}
                    for i in range(1, 6)]
            devs.append({'site_id': 'site01', 'device_id': 'fz09', 'age_sec': 900.0})
            code, body = 200, json.dumps({'devices': devs}).encode()
        self.send_response(code)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class UnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lc = load({})

    def test_real_presets_within_limits(self):
        self.lc.validate_presets(self.lc.PRESETS)
        ids = [p['id'] for p in self.lc.PRESETS]
        self.assertIn('mqtt-500-qos1', ids)

    def test_presets_over_limits_rejected(self):
        bad = [{'id': 'x', 'sec': 60, 'mqtt': {'sites': 3000, 'every_ms': 1000}},
               {'id': 'x', 'sec': 60, 'mqtt': {'sites': 1000, 'every_ms': 200}},        # 초당 5,000건
               {'id': 'x', 'sec': 60, 'mqtt': {'sites': 10, 'every_ms': 200, 'qos': 2}},
               {'id': 'x', 'sec': 60, 'api': {'rps': 50}},
               {'id': 'x', 'sec': 1000, 'api': {'rps': 5}},
               {'id': 'X Y', 'sec': 60, 'api': {'rps': 5}}]
        for p in bad:
            with self.assertRaises(ValueError, msg=p):
                self.lc.validate_presets([p])

    def test_load_text_shows_qos(self):
        mix = next(p for p in self.lc.PRESETS if p['id'] == 'demo-mix')
        self.assertEqual(self.lc.load_text(mix), 'MQTT 연결 100 · 초당 500건 · QoS 0 + API 초당 10건 · 3분')

    def test_pub_args_and_password_masking(self):
        ctx = {'mqtt_host': 'h', 'mqtt_pw': 'pw', 'ca': 'ca.crt'}
        args = self.lc.bench_pub_args(ctx, {'sites': 500, 'every_ms': 200, 'qos': 1})
        self.assertEqual(args[-1], '-S')
        self.assertIn('-q 1 ', ' '.join(args))
        self.assertNotIn('pw', self.lc.shown_args(args).split())

    def test_parse_bench_formats(self):
        old = 'sent(1001): total=2000, rate=1000(msg/sec)\nrecv(2): total=1990, rate=9(msg/sec)\nconnected(10): total=10, rate=1'
        self.assertEqual(self.lc.parse_bench(old), {'sent': 2000, 'recv': 1990, 'connected': 10})
        new = '1s connect_succ total=10 rate=10/sec\n2s pub total=50 rate=50/sec\n2s pub_succ total=48 rate=48/sec\n2s pub_fail total=2'
        self.assertEqual(self.lc.parse_bench(new), {'sent': 50, 'acked': 48, 'connected': 10,
                                                    'failures': {'pub_fail': 2}})

    def test_decode_name(self):
        self.assertEqual(self.lc.decode_name(Header(NAME, 'utf-8').encode()), NAME)
        self.assertEqual(self.lc.decode_name(NAME.encode('utf-8').decode('latin-1')), NAME)
        self.assertEqual(self.lc.decode_name('Alice'), 'Alice')


@unittest.skipUnless(os.name == 'posix' and shutil.which('sh'), '실행 흐름 시험은 리눅스에서만 돈다')
class ConsoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='load-console-test-')
        cls.state = os.path.join(cls.tmp, 'state')
        bindir = os.path.join(cls.tmp, 'bin')
        secrets = os.path.join(cls.tmp, 'secrets')
        for d in (cls.state, bindir, secrets):
            os.makedirs(d)
        for name, body in (('tailscale', FAKE_TAILSCALE), ('emqtt_bench', FAKE_BENCH), ('k6', FAKE_K6)):
            path = os.path.join(bindir, name)
            with open(path, 'w') as f:
                f.write(body.replace('@STATE@', cls.state).replace('@SUFFIX@', SUFFIX))
            os.chmod(path, 0o755)
        for name, value in (('api.key', KEY), ('mqtt.pw', MQTT_PW), ('mqtt-ca.crt', 'test-ca')):
            with open(os.path.join(secrets, name), 'w') as f:
                f.write(value + '\n')
        cls.api = HTTPServer(('127.0.0.1', 0), FakeApi)
        threading.Thread(target=cls.api.serve_forever, daemon=True).start()
        cls.port = free_port()
        cls.env = {
            'LOAD_DATA_DIR': os.path.join(cls.tmp, 'data'), 'LOAD_SECRETS_DIR': secrets,
            'LOAD_CONSOLE_PORT': str(cls.port), 'LOAD_K6_BIN': os.path.join(bindir, 'k6'),
            'LOAD_EMQTT_BENCH_BIN': os.path.join(bindir, 'emqtt_bench'),
            'LOAD_TAILSCALE_BIN': os.path.join(bindir, 'tailscale'),
            'LOAD_API_URL': 'http://127.0.0.1:%d' % cls.api.server_address[1],
        }
        lc = cls.lc = load(cls.env)
        lc.log = lambda event, **fields: None   # 시험 출력에 콘솔 이벤트 로그를 섞지 않는다
        # 시험용으로 짧게
        lc.GUARD_EVERY_SEC, lc.SUB_WARMUP_SEC, lc.SUB_DRAIN_SEC = 1, 0.5, 1.0
        lc.K6_GRACE_SEC, lc.STOP_WAIT_K6, lc.STOP_WAIT_BENCH = 8, 5, 3
        lc.PRESETS = [
            {'id': 'mqtt-check', 'group': 'MQTT', 'label': 'MQTT 확인', 'sec': 3,
             'mqtt': {'sites': 10, 'every_ms': 200}, 'path_check': True},
            {'id': 'mqtt-long', 'group': 'MQTT', 'label': 'MQTT 길게', 'sec': 30, 'mqtt': {'sites': 2, 'every_ms': 500}},
            {'id': 'api-small', 'group': 'API', 'label': 'API 작게', 'sec': 3, 'api': {'rps': 2}},
        ]
        lc.prepare_dirs()
        cls.server = lc.Server(('127.0.0.1', cls.port), lc.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.api.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.wait_idle()
        for n in os.listdir(self.state):
            os.remove(os.path.join(self.state, n))
        API_STATE.update(late=0.0, status=200)

    # ----- 도우미 -----
    def req(self, method, path, body=None, headers=None, ident=True):
        h = {}
        if ident:
            h.update({'Tailscale-User-Login': 'tester@example.com', 'Tailscale-User-Name': Header(NAME, 'utf-8').encode()})
        if method == 'POST':
            h.update({'X-Requested-With': 'load-console', 'Content-Type': 'application/json',
                      'Origin': 'http://127.0.0.1:%d' % self.port, 'Sec-Fetch-Site': 'same-origin'})
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        data = json.dumps(body if body is not None else {}).encode() if method == 'POST' else None
        r = urllib.request.Request('http://127.0.0.1:%d%s' % (self.port, path), data=data, headers=h, method=method)
        try:
            res = self.opener.open(r, timeout=30)
            code, hdrs, raw = res.status, res.headers, res.read()
        except urllib.error.HTTPError as e:
            code, hdrs, raw = e.code, e.headers, e.read()
        try:
            return code, hdrs, json.loads(raw.decode('utf-8'))
        except ValueError:
            return code, hdrs, raw.decode('utf-8', 'replace')

    def wait_idle(self, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            if self.lc.RUNNER.current() is None:
                return
            time.sleep(0.2)
        self.fail('시험이 끝나지 않음')

    def run_preset(self, preset, during=None):
        code, _, body = self.req('POST', '/api/start', {'preset': preset})
        self.assertEqual(code, 202, body)
        if during:
            during()
        self.wait_idle()
        _, _, st = self.req('GET', '/api/state')
        rid = st['history'][0]['id']
        with open(os.path.join(self.env['LOAD_DATA_DIR'], 'runs', rid + '.summary.json'), encoding='utf-8') as f:
            return json.load(f)

    def runs_file(self, name):
        with open(os.path.join(self.env['LOAD_DATA_DIR'], 'runs', name), encoding='utf-8') as f:
            return f.read()

    # ----- 접속·인증 -----
    def test_healthz_needs_no_identity(self):
        self.assertEqual(self.req('GET', '/healthz', ident=False)[0], 200)

    def test_identity_required(self):
        self.assertEqual(self.req('GET', '/', ident=False)[0], 403)
        self.assertEqual(self.req('POST', '/api/start', {'preset': 'mqtt-check'}, ident=False)[0], 403)

    def test_page_headers_and_state(self):
        code, hdrs, _ = self.req('GET', '/')
        self.assertEqual(code, 200)
        self.assertIn("default-src 'self'", hdrs['Content-Security-Policy'])
        code, _, st = self.req('GET', '/api/state')
        self.assertEqual(st['me'], NAME)
        self.assertTrue(all(i['ok'] for i in st['env']), st['env'])
        self.assertFalse(any(SUFFIX in (i['detail'] or '') for i in st['env']))   # 화면에 tailnet 이름을 안 보인다

    def test_csrf_rejected(self):
        cases = [{'X-Requested-With': None}, {'Sec-Fetch-Site': 'cross-site'}, {'Origin': 'https://evil.example'}]
        for headers in cases:
            self.assertEqual(self.req('POST', '/api/start', {'preset': 'mqtt-check'}, headers=headers)[0], 403, headers)
        self.assertEqual(self.req('POST', '/api/start', {'preset': 'mqtt-check'},
                                  headers={'Content-Type': 'text/plain'})[0], 415)

    def test_run_files_cannot_escape(self):
        for p in ('/runs/..%2F..%2Fsecrets%2Fapi.key', '/runs/../../etc/passwd', '/runs/a.log'):
            self.assertEqual(self.req('GET', p)[0], 404, p)

    # ----- 실행 -----
    def test_mqtt_run_passes(self):
        s = self.run_preset('mqtt-check')
        self.assertEqual((s['outcome'], s['verdict']), ('완료', '통과'), s)
        self.assertEqual(s['path'], 'direct')
        self.assertEqual(s['mqtt']['ratio'], 1.0)
        with open(os.path.join(self.state, 'args.log')) as f:
            args = f.read()
        self.assertIn('pub -c 10 -i 20 -I 200 -t loadtest/%i -s 256 -q 0 -h coldguard-mqtt.' + SUFFIX, args)
        self.assertIn('sub -c 1 -t loadtest/# -q 0', args)
        log = self.runs_file(s['id'] + '.log')
        self.assertNotIn(MQTT_PW, log)        # 콘솔 로그에 비밀번호를 남기지 않는다
        self.assertIn('fz09', log)            # 처음부터 늦은 장비는 감시에서 뺐다고 남긴다

    def test_stop_and_busy(self):
        def during():
            time.sleep(1.5)
            self.assertEqual(self.req('POST', '/api/start', {'preset': 'api-small'})[0], 409)
            self.assertEqual(self.req('POST', '/api/stop')[0], 202)
        s = self.run_preset('mqtt-long', during)
        self.assertEqual((s['outcome'], s['reason']), ('중지', NAME + '님이 멈춤'))

    def test_guard_stops_on_facility_delay(self):
        def during():
            time.sleep(1.5)
            API_STATE['late'] = 10.0
        s = self.run_preset('mqtt-long', during)
        self.assertEqual(s['outcome'], '자동 중지')
        self.assertIn('시설 데이터 지연', s['reason'])

    def test_guard_stops_when_api_unreachable(self):
        def during():
            time.sleep(1.5)
            API_STATE['status'] = 503
        s = self.run_preset('mqtt-long', during)
        self.assertEqual(s['outcome'], '자동 중지')
        self.assertIn('통제 API', s['reason'])

    def test_precheck_refuses_bad_key(self):
        API_STATE['status'] = 401
        code, _, body = self.req('POST', '/api/start', {'preset': 'mqtt-check'})
        self.assertEqual(code, 412)
        self.assertIn('키가 거부됨', body['message'])

    def test_pub_early_exit_is_error(self):
        open(os.path.join(self.state, 'pub_fail'), 'w').close()
        s = self.run_preset('mqtt-check')
        self.assertEqual(s['outcome'], '오류')
        self.assertIn('pub', s['reason'])

    def test_api_run_passes(self):
        s = self.run_preset('api-small')
        self.assertEqual((s['outcome'], s['verdict']), ('완료', '통과'), s)
        with open(os.path.join(self.state, 'k6_env.log')) as f:
            env = f.read()
        self.assertIn('LOAD_API_KEY_FILE=', env)
        self.assertNotIn(KEY, env)            # 키는 환경변수가 아니라 파일로 넘긴다
        self.assertIn('K6_WEB_DASHBOARD_HOST=127.0.0.1', env)
        code, hdrs, _ = self.req('GET', '/runs/' + s['id'] + '-k6.html')
        self.assertEqual(code, 200)
        self.assertTrue(hdrs['Content-Security-Policy'].startswith('sandbox'))   # 보고서는 다른 출처로 연다

    def test_k6_abort_is_auto_stop(self):
        open(os.path.join(self.state, 'k6_abort'), 'w').close()
        s = self.run_preset('api-small')
        self.assertEqual(s['outcome'], '자동 중지')
        self.assertIn('k6 기준', s['reason'])

    def test_check_cli(self):
        env = dict(os.environ, **self.env)
        env['PYTHONIOENCODING'] = 'ascii'     # 한글을 그대로 print하면 죽는 환경에서도 출력되는지
        res = subprocess.run([sys.executable, str(CONSOLE), '--check'], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, env=env, timeout=30)
        self.assertEqual(res.returncode, 0, res.stdout.decode('utf-8', 'replace'))
        env['LOAD_K6_BIN'] = os.path.join(self.tmp, 'missing-k6')
        res = subprocess.run([sys.executable, str(CONSOLE), '--check'], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, env=env, timeout=30)
        self.assertEqual(res.returncode, 1)


if __name__ == '__main__':
    unittest.main()
