#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ColdGuard 부하 시험 콘솔 (kt-load 서버)

정해 둔 프리셋만 버튼으로 실행한다. 숫자나 명령을 입력받지 않아 실수로 큰 부하가 나가거나 명령이 끼어들 수 없다.
한 번에 하나만 돌고, 시간이 끝나면 저절로 멈추며, 시험 중 시설 데이터가 늦어지면 자동으로 멈춘다.

접속과 인증
- 127.0.0.1에서만 듣는다. tailscale serve(https 443)로 tailnet에만 내보내므로 공인 IP로는 열리지 않는다.
- 로그인 대신 tailscale serve가 붙이는 사용자 헤더(Tailscale-User-Login/Name)를 쓴다. serve는 들어온 요청의 같은
  헤더를 지우고, 태그 장비가 보낸 요청에는 붙이지 않는다. 헤더가 없는 요청은 거부한다. 기록에는 표시 이름만 남긴다.
- 쓰기 요청(POST)은 전용 헤더·Sec-Fetch-Site·Origin을 확인해 다른 사이트에서 보낸 요청(CSRF)을 막는다.

시험 중 자동 중지 (모니터링 알림이 울리기 전에 멈춘다)
- 3초마다 통제 API로 냉동고 데이터 지연(age_sec)을 보고, 시작할 때보다 5초 넘게 늦은 게 두 번 연속이면 멈춘다.
- 통제 API에 세 번 연속 닿지 않아도 멈춘다(시설 상태를 확인할 수 없으므로).
- k6는 응답 p95 1초 초과나 오류율 5% 초과가 30초 이어지면 스스로 멈춘다(스크립트의 abortOnFail).

배포 (IaC Ansible)
- 파이썬 3.6 이상, 표준 라이브러리만 쓴다(Rocky 8의 /usr/libexec/platform-python 가능).
- /opt/coldguard-load/load_console.py, 서비스 계정 coldguard-load(홈 /var/lib/coldguard-load에 결과·로그를 쓴다)
- /etc/coldguard-load/api.key(통제 API 조회 키 kt-load), mqtt.pw(MQTT 계정 kt-load 비밀번호), mqtt-ca.crt(브로커 CA)
- systemd: User=coldguard-load, WorkingDirectory=/var/lib/coldguard-load, LimitNOFILE=65536, NoNewPrivileges=yes,
  Restart=on-failure. KillMode는 기본값(control-group) 그대로 둔다. 콘솔이 강제 종료돼도 남은 부하 프로세스를
  systemd가 함께 끄게 하기 위해서다(정상 종료 때는 콘솔이 부하를 먼저 멈추고 결과를 남긴다).
- tailscale serve: https 443 → http://127.0.0.1:8090, https 5665 → http://127.0.0.1:5665 (k6 대시보드, 시험 중에만 뜬다)
- 배포 확인: coldguard-load 계정으로 `load_console.py --check` → 모든 항목이 정상이면 종료 코드 0

환경변수 (모두 선택)
- LOAD_CONSOLE_PORT(8090), LOAD_DATA_DIR(/var/lib/coldguard-load), LOAD_SECRETS_DIR(/etc/coldguard-load)
- LOAD_K6_BIN(/usr/bin/k6), LOAD_EMQTT_BENCH_BIN(/opt/emqtt-bench/bin/emqtt_bench), LOAD_TAILSCALE_BIN(tailscale)
- LOAD_MQTT_HOST, LOAD_API_URL: 비우면 tailscale status의 MagicDNSSuffix로 coldguard-mqtt.<suffix>,
  https://control-api.<suffix>를 쓴다. 공개 저장소에 tailnet 이름을 넣지 않기 위해서다.

알려 둔 한계
- emqtt-bench는 비밀번호를 명령줄로만 받는다. 같은 서버의 다른 계정이 ps로 볼 수 있지만, kt-load는 시험 전용 서버라 허용한다.
"""
import http.server
import json
import math
import os
import re
import shutil
import signal
import socketserver
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.header import decode_header, make_header

# ---------------------------------------------------------------------------
# 프리셋: 모니터링 담당과 합의한 수치는 여기서만 바꾼다. 시작할 때 아래 LIMITS를 넘으면 콘솔이 뜨지 않는다.
#   mqtt.sites    가상 시설 수 = MQTT 연결 수 (시설 1곳 = 연결 1개)
#   mqtt.every_ms 연결당 발행 간격(ms). 200이면 냉동고 5대가 1초마다 보내는 시설 1곳과 같다(초당 5건).
#   mqtt.qos      발행 QoS(0 또는 1, 기본 0). 실제 시설 브리지는 QoS 1이다. 수신 확인 구독은 늘 QoS 0이다.
#   api.rps       통제 API 초당 요청 수. 통제 UI가 15초마다 부르는 4개를 같은 비율로 부른다.
# ---------------------------------------------------------------------------
PRESETS = [
    {'id': 'mqtt-check', 'group': 'MQTT', 'label': 'MQTT 확인', 'sec': 60,
     'note': '경로·인증·TLS 점검, Tailscale 직접 연결 여부 확인', 'mqtt': {'sites': 10, 'every_ms': 200},
     'path_check': True},
    {'id': 'mqtt-100', 'group': 'MQTT', 'label': 'MQTT 100곳', 'sec': 300,
     'note': '지금 실제 부하(초당 5건)의 100배', 'mqtt': {'sites': 100, 'every_ms': 200}},
    {'id': 'mqtt-500', 'group': 'MQTT', 'label': 'MQTT 500곳', 'sec': 300,
     'note': '상한. 앞 단계가 통과했을 때만', 'mqtt': {'sites': 500, 'every_ms': 200}},
    {'id': 'mqtt-500-qos1', 'group': 'MQTT', 'label': 'MQTT 500곳 (QoS 1)', 'sec': 300,
     'note': '실제 시설 브리지와 같은 QoS 1. 500곳(QoS 0)이 통과했을 때만',
     'mqtt': {'sites': 500, 'every_ms': 200, 'qos': 1}},
    {'id': 'mqtt-conn-2000', 'group': 'MQTT', 'label': '동시 접속 2,000', 'sec': 300,
     'note': '연결 수 자체를 본다. 다 붙는 데 약 40초', 'mqtt': {'sites': 2000, 'every_ms': 10000}},
    {'id': 'api-check', 'group': 'API', 'label': 'API 확인', 'sec': 60,
     'note': '경로·키 점검', 'api': {'rps': 2}},
    {'id': 'api-10', 'group': 'API', 'label': 'API 초당 10건', 'sec': 180,
     'note': '통제 UI 약 40명분', 'api': {'rps': 10}},
    {'id': 'api-30', 'group': 'API', 'label': 'API 초당 30건', 'sec': 180,
     'note': '통제 UI 약 110명분. 앞 단계가 통과했을 때만', 'api': {'rps': 30}},
    {'id': 'demo-mix', 'group': '시연', 'label': '복합', 'sec': 180,
     'note': 'MQTT 100곳 + API 초당 10건', 'mqtt': {'sites': 100, 'every_ms': 200}, 'api': {'rps': 10}},
]
MQTT_PAYLOAD = 256        # 바이트. 실제 텔레메트리(약 180~200바이트)보다 조금 크게 잡았다.
MQTT_CONN_PER_SEC = 50    # 접속 속도. 브로커가 TLS 접속을 한꺼번에 받지 않게 나눠 붙인다.
MQTT_PASS_RATIO = 0.99    # 판정: 받은 건수 / 보낸 건수
# 상한: 프리셋을 고치다 실수해도 이 이상은 나가지 않는다(브로커 512Mi·1코어, 통제 API 알림 기준을 보고 정했다).
LIMITS = {'sites': 2000, 'msg_per_sec': 2500, 'rps': 30, 'sec': 600}
# 콘솔이 직접 볼 수 없어 사람이 Grafana에서 보는 중단 기준(모니터링 담당과 합의). 화면에 그대로 보여 준다.
MANUAL_STOP_RULES = [
    '중앙 브로커 메모리 400Mi (320Mi부터 주의, 상한 512Mi)',
    '시설→중앙 대기열(broker_store_messages_count, site01) 1,000건 2회 연속',
    '알림이 하나라도 오면',
]

# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------
PORT = int(os.environ.get('LOAD_CONSOLE_PORT', '8090'))
DATA_DIR = os.environ.get('LOAD_DATA_DIR', '/var/lib/coldguard-load')
SECRETS_DIR = os.environ.get('LOAD_SECRETS_DIR', '/etc/coldguard-load')
K6_BIN = os.environ.get('LOAD_K6_BIN', '/usr/bin/k6')
BENCH_BIN = os.environ.get('LOAD_EMQTT_BENCH_BIN', '/opt/emqtt-bench/bin/emqtt_bench')
TS_BIN = os.environ.get('LOAD_TAILSCALE_BIN', 'tailscale')
MQTT_HOST_ENV = os.environ.get('LOAD_MQTT_HOST', '').strip()
API_URL_ENV = os.environ.get('LOAD_API_URL', '').strip().rstrip('/')
RUNS_DIR = os.path.join(DATA_DIR, 'runs')
K6_SCRIPT_PATH = os.path.join(DATA_DIR, 'api_read.js')

MQTT_PORT = 8883
MQTT_USER = 'kt-load'
MQTT_TOPIC_PREFIX = 'loadtest'   # 브로커 ACL에서 kt-load는 loadtest/#만 쓸 수 있다.
K6_DASH_PORT = 5665

GUARD_EVERY_SEC = 3       # 시설 데이터 지연 확인 간격
GUARD_LATE_SEC = 5.0      # 시작할 때보다 이만큼 넘게 늦으면 한 번 센다
GUARD_STRIKES = 2         # 연속 이 횟수면 멈춘다
GUARD_MAX_ERRORS = 3      # 통제 API 조회가 연속 이 횟수 실패하면 멈춘다
GUARD_FRESH_SEC = 30.0    # 시작할 때 이보다 늦은 냉동고는 이미 문제가 있는 것으로 보고 감시에서 뺀다
GUARD_TIMEOUT_SEC = 3
SUB_WARMUP_SEC = 3        # 수신 확인 구독이 붙을 때까지 기다린 뒤 발행을 시작한다
SUB_DRAIN_SEC = 3         # 발행을 멈춘 뒤 남은 메시지를 다 받을 때까지 기다린다
K6_GRACE_SEC = 60         # k6 정리(진행 중 요청 최대 30초)와 보고서 저장 여유
STOP_WAIT_K6 = 20
STOP_WAIT_BENCH = 5
PATH_CHECK_SEC = 20
KEEP_RUNS = 60            # 결과는 최근 60회만 남긴다
HISTORY_SHOW = 20
TAIL_LINES = 14

SUMMARY_RE = re.compile(r'(\d{8}-\d{6}-[a-z0-9-]+)\.summary\.json')
RUN_FILE_RE = re.compile(r'\d{8}-\d{6}-[a-z0-9-]+(?:\.summary)?\.(?:log|html|json)')
PRESET_ID_RE = re.compile(r'[a-z0-9-]{1,30}')
CONTROL_RE = re.compile(r'[\x00-\x08\x0b-\x1f\x7f]')
ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
BENCH_TOTAL_RE = re.compile(
    r'\b(connect_succ|connect_fail|connected|pub_succ|pub_fail|sub_fail|pub|sent|recv)\b\S*\s*:?\s*total=(\d+)')

LOG_LOCK = threading.Lock()
SSL_CTX = ssl.create_default_context()
# 프록시 환경변수가 있어도 tailnet 주소로 바로 간다.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=SSL_CTX))


def out(text):
    """UTF-8로 그대로 쓴다. 파이썬 3.6은 로케일이 C이면 한글을 print하다 죽기 때문이다(systemd·Ansible 환경)."""
    with LOG_LOCK:
        sys.stdout.buffer.write((text + '\n').encode('utf-8'))
        sys.stdout.flush()


def log(event, **fields):
    """한 줄 JSON 로그(journald로 간다). 키·비밀번호·이메일은 남기지 않는다."""
    rec = {'at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z', 'event': event}
    rec.update(fields)
    out(json.dumps(rec, ensure_ascii=False))


def iso(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ---------------------------------------------------------------------------
# 프리셋 표시·검사
# ---------------------------------------------------------------------------
def msg_per_sec(m):
    return m['sites'] * 1000.0 / m['every_ms']


def dur_text(sec):
    return '{}분'.format(sec // 60) if sec % 60 == 0 else '{}초'.format(sec)


def load_text(p):
    parts = []
    m, a = p.get('mqtt'), p.get('api')
    if m:
        parts.append('MQTT 연결 {:,} · 초당 {:,}건 · QoS {}'.format(
            m['sites'], int(round(msg_per_sec(m))), m.get('qos', 0)))
    if a:
        parts.append('API 초당 {}건'.format(a['rps']))
    return ' + '.join(parts) + ' · ' + dur_text(p['sec'])


def validate_presets(presets):
    seen = set()
    for p in presets:
        pid = p.get('id', '')
        if not PRESET_ID_RE.fullmatch(pid) or pid in seen:
            raise ValueError('프리셋 id가 잘못됐거나 겹칩니다: {!r}'.format(pid))
        seen.add(pid)
        if not isinstance(p.get('sec'), int) or not 30 <= p['sec'] <= LIMITS['sec']:
            raise ValueError('{}: 시간은 30~{}초여야 합니다'.format(pid, LIMITS['sec']))
        m, a = p.get('mqtt'), p.get('api')
        if not m and not a:
            raise ValueError('{}: mqtt나 api 중 하나는 있어야 합니다'.format(pid))
        if m:
            if not isinstance(m.get('sites'), int) or not 1 <= m['sites'] <= LIMITS['sites']:
                raise ValueError('{}: 연결 수는 1~{}여야 합니다'.format(pid, LIMITS['sites']))
            if not isinstance(m.get('every_ms'), int) or m['every_ms'] < 100:
                raise ValueError('{}: 발행 간격은 100ms 이상이어야 합니다'.format(pid))
            if msg_per_sec(m) > LIMITS['msg_per_sec']:
                raise ValueError('{}: 초당 {}건을 넘습니다'.format(pid, LIMITS['msg_per_sec']))
            if m.get('qos', 0) not in (0, 1):
                raise ValueError('{}: QoS는 0이나 1이어야 합니다'.format(pid))
        if a and (not isinstance(a.get('rps'), int) or not 1 <= a['rps'] <= LIMITS['rps']):
            raise ValueError('{}: API 초당 요청은 1~{}여야 합니다'.format(pid, LIMITS['rps']))


# ---------------------------------------------------------------------------
# Tailscale·주소·환경 점검
# ---------------------------------------------------------------------------
class Net(object):
    """tailscale status --json 결과를 잠깐 기억해 둔다(화면이 2초마다 묻기 때문)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.at = 0.0
        self.value = None

    def get(self, max_age=10):
        with self.lock:
            if self.value is None or time.monotonic() - self.at > max_age:
                self.value = self.probe()
                self.at = time.monotonic()
            return dict(self.value)

    @staticmethod
    def probe():
        info = {'ok': False, 'state': '', 'suffix': '', 'error': ''}
        try:
            # 바이트로 받아 UTF-8로 푼다(사용자 표시 이름에 한글이 있어도 로케일과 상관없이 읽히게).
            res = subprocess.run([TS_BIN, 'status', '--json'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 stdin=subprocess.DEVNULL, timeout=5)
            st = json.loads(res.stdout.decode('utf-8', 'replace') or '{}')
            suffix = st.get('MagicDNSSuffix') or (st.get('CurrentTailnet') or {}).get('MagicDNSSuffix') or ''
            info['state'] = str(st.get('BackendState') or '')
            info['suffix'] = str(suffix).strip('.')
            info['ok'] = info['state'] == 'Running'
        except subprocess.TimeoutExpired:
            info['error'] = '응답 시간 초과'
        except (OSError, ValueError) as exc:
            info['error'] = type(exc).__name__
        return info


NET = Net()


def endpoints(net):
    suffix = net.get('suffix', '')
    mqtt = MQTT_HOST_ENV or ('coldguard-mqtt.' + suffix if suffix else '')
    api = API_URL_ENV or ('https://control-api.' + suffix if suffix else '')
    return mqtt, api


def short_host(host, suffix):
    """화면에는 tailnet 이름을 빼고 보여 준다(캡처가 문서에 들어가도 tailnet 이름이 남지 않게)."""
    if '://' in host:
        host = urllib.parse.urlsplit(host).hostname or host
    if suffix and host.endswith('.' + suffix):
        return host[:-(len(suffix) + 1)]
    return host


def secret_path(name):
    return os.path.join(SECRETS_DIR, name)


def readable(path):
    try:
        return os.path.isfile(path) and os.access(path, os.R_OK) and os.path.getsize(path) > 0
    except OSError:
        return False


def is_exec(path):
    if os.sep in path:
        return os.path.isfile(path) and os.access(path, os.X_OK)
    return shutil.which(path) is not None


def read_secret(name):
    with open(secret_path(name), 'r', encoding='utf-8') as f:
        value = f.read().strip()
    if not value:
        raise ValueError(name + ' 비어 있음')
    return value


def check_env(net):
    mqtt, api = endpoints(net)
    suffix = net.get('suffix', '')
    items = []

    def add(key, label, ok, detail=''):
        items.append({'key': key, 'label': label, 'ok': bool(ok), 'detail': detail})

    add('tailscale', 'Tailscale', net.get('ok'), net.get('state') or net.get('error') or '응답 없음')
    add('mqtt_host', 'MQTT 주소', mqtt, short_host(mqtt, suffix) if mqtt else '알 수 없음')
    add('api_url', '통제 API 주소', api, short_host(api, suffix) if api else '알 수 없음')
    add('k6', 'k6', is_exec(K6_BIN), K6_BIN)
    add('bench', 'emqtt-bench', is_exec(BENCH_BIN), BENCH_BIN)
    add('api_key', '통제 API 키 (api.key)', readable(secret_path('api.key')))
    add('mqtt_pw', 'MQTT 비밀번호 (mqtt.pw)', readable(secret_path('mqtt.pw')))
    add('mqtt_ca', '브로커 CA (mqtt-ca.crt)', readable(secret_path('mqtt-ca.crt')))
    return items


def blocked_reasons(p, env):
    need = ['tailscale', 'api_url', 'api_key']          # 시설 데이터 감시는 모든 시험에 필요하다
    if p.get('mqtt'):
        need += ['mqtt_host', 'bench', 'mqtt_pw', 'mqtt_ca']
    if p.get('api'):
        need += ['k6']
    return [env[k]['label'] for k in need if k in env and not env[k]['ok']]


# ---------------------------------------------------------------------------
# 시설 데이터 감시 (통제 API 조회)
# ---------------------------------------------------------------------------
def fetch_ages(api_url, key):
    """냉동고별 데이터 지연(초). 통제 API /api/v1/devices의 age_sec."""
    req = urllib.request.Request(api_url + '/api/v1/devices', headers={
        'Authorization': 'Bearer ' + key, 'User-Agent': 'coldguard-load-console', 'Accept': 'application/json'})
    with OPENER.open(req, timeout=GUARD_TIMEOUT_SEC) as res:
        data = json.loads(res.read(1 << 20).decode('utf-8'))
    ages = {}
    for d in data.get('devices') or []:
        age = d.get('age_sec') if isinstance(d, dict) else None
        if isinstance(age, (int, float)) and not isinstance(age, bool) and math.isfinite(age):
            ages['{}/{}'.format(d.get('site_id'), d.get('device_id'))] = float(age)
    return ages


def describe_error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return '키가 거부됨(HTTP {})'.format(exc.code)
        return 'HTTP {}'.format(exc.code)
    if isinstance(exc, urllib.error.URLError):
        return '연결 실패({})'.format(type(exc.reason).__name__)
    if isinstance(exc, OSError) and 'timed out' in str(exc):
        return '시간 초과'
    return type(exc).__name__


# ---------------------------------------------------------------------------
# k6 스크립트 (콘솔이 시작할 때 DATA_DIR/api_read.js로 쓴다)
# ---------------------------------------------------------------------------
K6_SCRIPT = r"""// ColdGuard 부하 시험: 통제 API 조회만 한다. load_console.py가 시작할 때마다 다시 쓴다(직접 고치지 않는다).
import http from 'k6/http';
import exec from 'k6/execution';

const API = __ENV.LOAD_API_URL;
const KEY = open(__ENV.LOAD_API_KEY_FILE).trim();
const RPS = parseInt(__ENV.LOAD_RPS, 10);

// 통제 UI가 15초마다 부르는 4개를 같은 비율로 부른다.
const PATHS = ['/readyz', '/api/v1/me', '/api/v1/devices', '/api/v1/commands?limit=50'];

export const options = {
  scenarios: {
    ui_like: {
      executor: 'constant-arrival-rate',
      rate: RPS,
      timeUnit: '1s',
      duration: __ENV.LOAD_DURATION,
      preAllocatedVUs: Math.max(5, RPS),
      maxVUs: Math.max(20, RPS * 4),
    },
  },
  thresholds: {
    // 첫 기준: 넘으면 30초 지켜본 뒤 자동 중단(모니터링 알림보다 먼저 멈춘다). 둘째 기준: 판정용.
    http_req_failed: [{ threshold: 'rate<0.05', abortOnFail: true, delayAbortEval: '30s' }, 'rate<0.01'],
    http_req_duration: [{ threshold: 'p(95)<1000', abortOnFail: true, delayAbortEval: '30s' }, 'p(95)<500'],
  },
  summaryTrendStats: ['avg', 'p(90)', 'p(95)', 'p(99)', 'max'],
  userAgent: 'coldguard-load-console',
};

export default function () {
  const path = PATHS[exec.scenario.iterationInTest % PATHS.length];
  const headers = path === '/readyz' ? {} : { Authorization: 'Bearer ' + KEY };
  http.get(API + path, { headers: headers, tags: { name: path.split('?')[0] } });
}

export function handleSummary(data) {
  const m = data.metrics;
  const val = (name, key) => (m[name] && m[name].values && m[name].values[key] !== undefined ? m[name].values[key] : null);
  const thresholds = {};
  Object.keys(m).forEach((name) => {
    const t = m[name].thresholds;
    if (t) Object.keys(t).forEach((expr) => { thresholds[name + ' ' + expr] = t[expr].ok; });
  });
  const out = {
    reqs: val('http_reqs', 'count'),
    rps: val('http_reqs', 'rate'),
    failed_rate: val('http_req_failed', 'rate'),
    avg_ms: val('http_req_duration', 'avg'),
    p95_ms: val('http_req_duration', 'p(95)'),
    p99_ms: val('http_req_duration', 'p(99)'),
    thresholds: thresholds,
  };
  const num = (x, d) => (x === null ? '-' : Number(x).toFixed(d));
  const lines = [
    '요청 ' + num(out.reqs, 0) + '건 (초당 ' + num(out.rps, 1) + ')',
    '실패율 ' + (out.failed_rate === null ? '-' : (out.failed_rate * 100).toFixed(2)) + '%',
    '응답 평균 ' + num(out.avg_ms, 0) + 'ms, p95 ' + num(out.p95_ms, 0) + 'ms, p99 ' + num(out.p99_ms, 0) + 'ms',
  ];
  Object.keys(thresholds).forEach((k) => lines.push((thresholds[k] ? '통과  ' : '미달  ') + k));
  const result = { stdout: lines.join('\n') + '\n' };
  result[__ENV.LOAD_SUMMARY_FILE] = JSON.stringify(out, null, 2);
  return result;
}
"""


# ---------------------------------------------------------------------------
# 시험 실행
# ---------------------------------------------------------------------------
def run_path(name):
    return os.path.join(RUNS_DIR, name)


def base_env():
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TZ') if k in os.environ}
    env.setdefault('PATH', '/usr/local/bin:/usr/bin:/bin')
    env.setdefault('HOME', DATA_DIR)   # emqtt-bench(Erlang)는 HOME이 있어야 뜬다
    return env


def bench_common(ctx):
    # -S(TLS)는 공식 예시처럼 맨 뒤에 둔다. 비밀번호는 명령줄로만 받는다(모듈 설명의 "알려 둔 한계").
    return ['-h', ctx['mqtt_host'], '-p', str(MQTT_PORT), '-u', MQTT_USER, '-P', ctx['mqtt_pw'],
            '--cacertfile', ctx['ca'], '-S']


def bench_sub_args(ctx):
    return [BENCH_BIN, 'sub', '-c', '1', '-t', MQTT_TOPIC_PREFIX + '/#', '-q', '0'] + bench_common(ctx)


def bench_pub_args(ctx, m):
    return [BENCH_BIN, 'pub', '-c', str(m['sites']), '-i', str(1000 // MQTT_CONN_PER_SEC), '-I', str(m['every_ms']),
            '-t', MQTT_TOPIC_PREFIX + '/%i', '-s', str(MQTT_PAYLOAD), '-q', str(m.get('qos', 0))] + bench_common(ctx)


def shown_args(args):
    """로그에 남길 명령. 비밀번호 자리는 가린다."""
    out, hide = [], False
    for a in args:
        out.append('***' if hide else a)
        hide = a == '-P'
    return ' '.join(out)


def k6_env(run, a):
    env = base_env()
    env.update({
        'LOAD_API_URL': run.ctx['api_url'],
        'LOAD_API_KEY_FILE': secret_path('api.key'),   # 키는 환경변수가 아니라 파일로 넘긴다
        'LOAD_RPS': str(a['rps']),
        'LOAD_DURATION': '{}s'.format(run.preset['sec']),
        'LOAD_SUMMARY_FILE': run.files['k6-summary'],
        'K6_WEB_DASHBOARD': 'true',
        'K6_WEB_DASHBOARD_HOST': '127.0.0.1',
        'K6_WEB_DASHBOARD_PORT': str(K6_DASH_PORT),
        'K6_WEB_DASHBOARD_PERIOD': '5s',
        'K6_WEB_DASHBOARD_EXPORT': run.files['k6-report'],
        'K6_NO_USAGE_REPORT': 'true',
    })
    return env


class Run(object):
    STATE_TEXT = {'starting': '준비 중', 'running': '실행 중', 'stopping': '멈추는 중', 'finished': '끝남'}

    def __init__(self, preset, by, ctx):
        self.preset = preset
        self.by = by
        self.ctx = ctx
        self.created = time.time()
        self.id = time.strftime('%Y%m%d-%H%M%S', time.gmtime(self.created)) + '-' + preset['id']
        self.load_started = None
        self.ended = None
        self.state = 'starting'
        self.stop_event = threading.Event()
        self.stopped_by = None
        self.service_stop = False   # 콘솔 서비스가 멈춰 함께 멈춘 경우(판정하지 않는다)
        self.auto_reason = None
        self.fail_reason = None
        self.procs = {}
        self.codes = {}
        self.mqtt_stopped = False
        self.path = None
        self.guard_text = '시작 전 확인 정상'
        self.guard_strikes = 0
        self.guard_errors = 0
        self.max_late = 0.0
        self.files = {'console': run_path(self.id + '.log')}
        if preset.get('api'):
            self.files['k6-summary'] = run_path(self.id + '-k6.json')
            self.files['k6-report'] = run_path(self.id + '-k6.html')
        self.console_lock = threading.Lock()

    def console(self, text):
        line = '[{}] {}\n'.format(time.strftime('%H:%M:%S'), text)
        with self.console_lock, open(self.files['console'], 'a', encoding='utf-8') as f:
            f.write(line)

    def view(self):
        p = self.preset
        elapsed = time.time() - self.load_started if self.load_started else 0
        tails = {}
        for name in ('console', 'pub', 'sub', 'k6'):
            if name in self.files:
                tails[name] = tail_lines(self.files[name], TAIL_LINES)
        return {
            'id': self.id, 'preset': p['id'], 'label': p['label'], 'load': load_text(p), 'by': self.by,
            'state': self.state, 'state_text': self.STATE_TEXT.get(self.state, self.state),
            'started': iso(self.created), 'elapsed': int(elapsed), 'sec': p['sec'],
            'guard': self.guard_text, 'path': path_text(self.path),
            'k6': 'k6' in self.procs and 'k6' not in self.codes, 'tails': tails,
        }


def path_text(path):
    return {'direct': '직접 연결',
            'derp': '중계(DERP): 높은 단계에서는 시스템 대신 중계 서버 한계를 재게 됩니다',
            'unknown': '확인 불가(콘솔 로그 참고)'}.get(path, '')


def tail_lines(path, n):
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 16384))
            raw = f.read()
    except OSError:
        return []
    text = ANSI_RE.sub('', raw.decode('utf-8', 'replace')).replace('\r', '\n')
    lines = [CONTROL_RE.sub('', l).rstrip() for l in text.split('\n')]
    return [l for l in lines if l.strip()][-n:]


def read_text(path, limit=4 << 20):
    if not path:
        return ''
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - limit))
            return f.read().decode('utf-8', 'replace')
    except OSError:
        return ''


def read_json_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def start_proc(run, name, args, env):
    path = run_path('{}-{}.log'.format(run.id, name))
    run.files[name] = path
    f = open(path, 'ab')
    try:
        proc = subprocess.Popen(args, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                cwd=DATA_DIR, env=env, start_new_session=True)
    finally:
        f.close()   # 자식이 파일을 물려받았으므로 부모 쪽은 닫는다
    run.procs[name] = proc
    run.console('{} 시작: {}'.format(name, shown_args(args)))


def stop_proc(run, name, sig, wait):
    proc = run.procs.get(name)
    if proc is None:
        return
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            run.console('{}가 {}초 안에 끝나지 않아 강제로 멈춤'.format(name, wait))
    run.codes.setdefault(name, proc.returncode)


def stop_mqtt(run):
    """정상 종료: 발행을 먼저 멈추고, 남은 메시지를 받은 뒤 구독을 멈춘다."""
    run.mqtt_stopped = True
    stop_proc(run, 'pub', signal.SIGTERM, STOP_WAIT_BENCH)
    if 'sub' in run.procs and 'sub' not in run.codes:
        time.sleep(SUB_DRAIN_SEC)
    stop_proc(run, 'sub', signal.SIGTERM, STOP_WAIT_BENCH)


def stop_all(run):
    """중지·자동 중지: 부하(발행·k6)를 먼저 끊는다. k6는 SIGINT로 멈춰야 요약과 보고서를 남긴다."""
    run.mqtt_stopped = True
    stop_proc(run, 'pub', signal.SIGTERM, STOP_WAIT_BENCH)
    stop_proc(run, 'k6', signal.SIGINT, STOP_WAIT_K6)
    if 'sub' in run.procs and 'sub' not in run.codes:
        time.sleep(SUB_DRAIN_SEC)
    stop_proc(run, 'sub', signal.SIGTERM, STOP_WAIT_BENCH)


def path_check(run, host):
    """Tailscale 경로가 직접 연결인지 중계(DERP)인지 본다. 중지 버튼에 바로 반응하도록 기다리면서 확인한다."""
    run.console('Tailscale 경로 확인: tailscale ping -c 5 ' + short_host(host, run.ctx.get('suffix', '')))
    try:
        proc = subprocess.Popen([TS_BIN, 'ping', '-c', '5', host], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    except OSError as exc:
        run.console('tailscale ping 실행 실패: ' + type(exc).__name__)
        return 'unknown'
    deadline = time.time() + PATH_CHECK_SEC
    while proc.poll() is None and time.time() < deadline and not run.stop_event.is_set():
        time.sleep(0.2)
    if proc.poll() is None:
        proc.kill()
    text = (proc.communicate()[0] or b'').decode('utf-8', 'replace')
    suffix = run.ctx.get('suffix', '')
    for line in text.strip().splitlines()[-6:]:
        run.console('  ' + (line.replace('.' + suffix, '') if suffix else line))
    pongs = [l for l in text.splitlines() if 'pong' in l]
    if not pongs:
        return 'unknown'
    return 'derp' if 'DERP' in pongs[-1] else 'direct'


def k6_aborted(run):
    return 'abortOnFail' in read_text(run.files.get('k6'), 1 << 20)


def watch_exits(run, load_end):
    for name, proc in list(run.procs.items()):
        if name in run.codes:
            continue
        code = proc.poll()
        if code is None:
            continue
        run.codes[name] = code
        if name == 'k6':
            if k6_aborted(run):
                run.auto_reason = 'k6 기준 초과(응답 p95 1초 또는 오류율 5%)로 자동 중단'
                run.stop_event.set()
            elif time.time() < load_end - 2:
                run.fail_reason = 'k6가 일찍 끝남(종료 코드 {}), k6 로그를 확인해 주세요'.format(code)
                run.stop_event.set()
        elif not run.mqtt_stopped:
            run.fail_reason = 'emqtt-bench {0}가 일찍 끝남(종료 코드 {1}), {0} 로그를 확인해 주세요'.format(name, code)
            run.stop_event.set()


def guard_check(run):
    ctx = run.ctx
    try:
        ages = fetch_ages(ctx['api_url'], ctx['api_key'])
    except Exception as exc:  # 어떤 실패든 시설 상태를 모르는 것으로 본다
        run.guard_errors += 1
        run.guard_text = '통제 API 조회 실패 {}회 연속({})'.format(run.guard_errors, describe_error(exc))
        if run.guard_errors >= GUARD_MAX_ERRORS and not run.stop_event.is_set():
            run.auto_reason = '통제 API에 {}번 연속 닿지 않아(시설 상태 확인 불가) 자동 중지'.format(run.guard_errors)
            run.stop_event.set()
        return
    run.guard_errors = 0
    deltas = {dev: ages[dev] - base for dev, base in ctx['baseline'].items() if dev in ages}
    worst_dev, worst = (max(deltas.items(), key=lambda kv: kv[1]) if deltas else (None, 0.0))
    run.max_late = max(run.max_late, worst)
    if worst > GUARD_LATE_SEC:
        run.guard_strikes += 1
        run.guard_text = '{} 시작 때보다 {:.1f}초 늦음({}회 연속)'.format(worst_dev, worst, run.guard_strikes)
        run.console('감시: ' + run.guard_text)
        if run.guard_strikes >= GUARD_STRIKES and not run.stop_event.is_set():
            run.auto_reason = '시설 데이터 지연({} +{:.1f}초)으로 자동 중지'.format(worst_dev, worst)
            run.stop_event.set()
    else:
        run.guard_strikes = 0
        run.guard_text = '시설 데이터 정상(냉동고 {}대, 시작 때보다 최대 {:+.1f}초)'.format(len(deltas), worst)


def supervise(run):
    p = run.preset
    m, a = p.get('mqtt'), p.get('api')
    try:
        run.console('시험 시작: {} ({}), 시작한 사람: {}'.format(p['label'], load_text(p), run.by))
        run.console('감시 대상 냉동고 {}대: {}'.format(len(run.ctx['baseline']), ', '.join(sorted(run.ctx['baseline']))))
        if run.ctx['excluded']:
            run.console('시작 전부터 {}초 넘게 늦어 감시에서 뺀 냉동고: {}'.format(
                int(GUARD_FRESH_SEC), ', '.join(run.ctx['excluded'])))
        if m and p.get('path_check'):
            run.path = path_check(run, run.ctx['mqtt_host'])
            run.console('경로 판정: ' + path_text(run.path))
        if m and not run.stop_event.is_set():
            start_proc(run, 'sub', bench_sub_args(run.ctx), base_env())
            run.stop_event.wait(SUB_WARMUP_SEC)
            if not run.stop_event.is_set():
                start_proc(run, 'pub', bench_pub_args(run.ctx, m), base_env())
        if a and not run.stop_event.is_set():
            start_proc(run, 'k6', [K6_BIN, 'run', '--no-color', K6_SCRIPT_PATH], k6_env(run, a))
        run.load_started = time.time()
        run.state = 'running'
        log('load_run_start', run=run.id, preset=p['id'], by=run.by)
        load_end = run.load_started + p['sec']
        hard_end = load_end + K6_GRACE_SEC
        next_guard = time.time() + GUARD_EVERY_SEC
        while not run.stop_event.is_set():
            watch_exits(run, load_end)
            if run.stop_event.is_set():
                break
            now = time.time()
            if m and not run.mqtt_stopped and now >= load_end:
                run.console('정해진 시간이 끝나 MQTT 부하를 멈춤')
                stop_mqtt(run)
            if all(name in run.codes for name in run.procs):
                break
            if now >= hard_end:
                run.fail_reason = 'k6가 정해진 시간보다 {}초 넘게 끝나지 않아 멈춤'.format(K6_GRACE_SEC)
                break
            if now >= next_guard:
                guard_check(run)
                next_guard = time.time() + GUARD_EVERY_SEC
            time.sleep(0.5)
    except Exception as exc:  # 예상 못 한 오류에도 부하는 반드시 멈춘다
        run.fail_reason = '콘솔 내부 오류({})'.format(type(exc).__name__)
        log('load_console_error', run=run.id, error=type(exc).__name__, detail=str(exc)[:200])
    finally:
        run.state = 'stopping'
        try:
            stop_all(run)
        except Exception as exc:
            log('load_console_error', run=run.id, step='stop', error=type(exc).__name__, detail=str(exc)[:200])
        try:
            finalize(run)
        except Exception as exc:
            log('load_console_error', run=run.id, step='finalize', error=type(exc).__name__, detail=str(exc)[:200])
        finally:
            run.state = 'finished'
            RUNNER.finished(run)   # 정리 중 오류가 나도 다음 시험을 막지 않는다
            cleanup_runs()


def parse_bench(text):
    """emqtt-bench 출력에서 마지막 누적값을 뽑는다. 판 형식(sent(…): total=… / 1s pub total=…)을 모두 받는다."""
    out, fails = {}, {}
    for mt in BENCH_TOTAL_RE.finditer(text or ''):
        key, n = mt.group(1), int(mt.group(2))
        if key in ('pub', 'sent'):
            out['sent'] = n
        elif key == 'pub_succ':
            out['acked'] = n      # QoS 1에서 브로커가 확인 응답(PUBACK)한 건수
        elif key == 'recv':
            out['recv'] = n
        elif key in ('connect_succ', 'connected'):
            out['connected'] = n
        else:
            fails[key] = n
    if fails:
        out['failures'] = fails
    return out


def finalize(run):
    run.ended = time.time()
    p = run.preset
    m, a = p.get('mqtt'), p.get('api')
    s = {'id': run.id, 'preset': p['id'], 'label': p['label'], 'load': load_text(p), 'by': run.by,
         'started': iso(run.created), 'ended': iso(run.ended),
         'load_sec': round(run.ended - run.load_started, 1) if run.load_started else 0,
         'path': run.path, 'max_late_sec': round(run.max_late, 1)}
    checks = []
    if m:
        pub = parse_bench(read_text(run.files.get('pub')))
        sub = parse_bench(read_text(run.files.get('sub')))
        sent, recv, conn = pub.get('sent'), sub.get('recv'), pub.get('connected')
        ratio = (float(recv) / sent) if (sent and recv is not None) else None
        s['mqtt'] = {'sites': m['sites'], 'msg_per_sec': msg_per_sec(m), 'qos': m.get('qos', 0), 'sent': sent,
                     'acked': pub.get('acked'), 'received': recv,
                     'ratio': round(ratio, 4) if ratio is not None else None, 'connected': conn,
                     'failures': pub.get('failures', {})}
        checks.append(None if ratio is None else (ratio >= MQTT_PASS_RATIO and (conn is None or conn >= m['sites'])))
    if a:
        k6s = read_json_file(run.files.get('k6-summary'))
        code = run.codes.get('k6')
        s['api'] = {'rps': a['rps'], 'exit_code': code, 'reqs': k6s.get('reqs'), 'failed_rate': k6s.get('failed_rate'),
                    'p95_ms': k6s.get('p95_ms'), 'thresholds': k6s.get('thresholds')}
        checks.append(True if code == 0 else False if code == 99 else None)
    if run.stopped_by:
        outcome, verdict, reason = '중지', None, '{}님이 멈춤'.format(run.stopped_by)
    elif run.service_stop:
        outcome, verdict, reason = '중지', None, '콘솔 서비스가 멈춰 함께 멈춤'
    elif run.fail_reason:
        outcome, verdict, reason = '오류', None, run.fail_reason
    elif run.auto_reason:
        outcome, verdict, reason = '자동 중지', '기준 미달', run.auto_reason
    else:
        outcome, reason = '완료', ''
        verdict = '판정 불가' if (not checks or None in checks) else ('통과' if all(checks) else '기준 미달')
    s.update(outcome=outcome, verdict=verdict, reason=reason)
    try:
        s['files'] = sorted(n for n in os.listdir(RUNS_DIR)
                            if (n.startswith(run.id + '.') or n.startswith(run.id + '-')) and RUN_FILE_RE.fullmatch(n))
    except OSError:
        s['files'] = []
    s['files'].append(run.id + '.summary.json')
    tmp = run_path(run.id + '.summary.json.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    os.replace(tmp, run_path(run.id + '.summary.json'))
    run.console('끝: {}{}{}'.format(outcome, ' · ' + verdict if verdict else '', ' · ' + reason if reason else ''))
    log('load_run_end', run=run.id, preset=p['id'], by=run.by, outcome=outcome, verdict=verdict, reason=reason,
        load_sec=s['load_sec'])


class Runner(object):
    def __init__(self):
        self.lock = threading.Lock()
        self.run = None
        self.starting = False

    def current(self):
        with self.lock:
            return self.run

    def start(self, preset, by):
        with self.lock:
            if self.run is not None:
                return 409, {'error': 'busy', 'message': '이미 시험이 돌고 있습니다: {} ({}님)'.format(
                    self.run.preset['label'], self.run.by)}
            if self.starting:
                return 409, {'error': 'busy', 'message': '다른 시작 요청을 확인하는 중입니다. 잠시 뒤 다시 해 주세요.'}
            self.starting = True
        # 시작 전 점검(통제 API 조회 등 몇 초 걸림)은 잠금 밖에서 해 화면 갱신이 멈추지 않게 한다.
        try:
            ctx, problem = build_ctx(preset)
        except Exception as exc:
            ctx, problem = None, '시작 전 점검 중 오류({})'.format(type(exc).__name__)
        with self.lock:
            self.starting = False
            if problem:
                log('load_run_refused', preset=preset['id'], by=by, reason=problem)
                return 412, {'error': 'precheck', 'message': problem}
            run = Run(preset, by, ctx)
            self.run = run
        threading.Thread(target=supervise, args=(run,), name='run-' + run.id, daemon=True).start()
        return 202, {'ok': True, 'run': run.id}

    def stop(self, by):
        run = self.current()
        if run is None:
            return 409, {'error': 'idle', 'message': '실행 중인 시험이 없습니다.'}
        if not run.stop_event.is_set():
            run.stopped_by = by
            run.stop_event.set()
            log('load_run_stop_request', run=run.id, by=by)
        return 202, {'ok': True}

    def finished(self, run):
        with self.lock:
            if self.run is run:
                self.run = None


RUNNER = Runner()


def build_ctx(preset):
    """시작 전 점검. 하나라도 안 되면 시작하지 않는다."""
    net = NET.get(max_age=0)
    mqtt, api = endpoints(net)
    env = {i['key']: i for i in check_env(net)}
    blocked = blocked_reasons(preset, env)
    if blocked:
        return None, '준비되지 않은 항목이 있어 시작하지 않습니다: ' + ', '.join(blocked)
    try:
        api_key = read_secret('api.key')
        mqtt_pw = read_secret('mqtt.pw') if preset.get('mqtt') else None
    except (OSError, ValueError) as exc:
        return None, '키 파일을 읽지 못했습니다({})'.format(type(exc).__name__)
    try:
        ages = fetch_ages(api, api_key)
    except Exception as exc:
        return None, '통제 API에 닿지 않아 시설 상태를 확인할 수 없어 시작하지 않습니다({})'.format(describe_error(exc))
    baseline = {k: v for k, v in ages.items() if v <= GUARD_FRESH_SEC}
    if not baseline:
        return None, '시설 데이터가 모두 {}초 넘게 늦어 시작하지 않습니다. 부하와 무관한 문제부터 확인해 주세요.'.format(
            int(GUARD_FRESH_SEC))
    return {'mqtt_host': mqtt, 'api_url': api, 'api_key': api_key, 'mqtt_pw': mqtt_pw,
            'ca': secret_path('mqtt-ca.crt'), 'suffix': net.get('suffix', ''), 'baseline': baseline,
            'excluded': sorted(k for k in ages if k not in baseline)}, None


# ---------------------------------------------------------------------------
# 결과 목록
# ---------------------------------------------------------------------------
FILE_LABELS = [('.summary.json', '요약'), ('-k6.html', 'k6 보고서'), ('-k6.json', 'k6 요약'), ('-k6.log', 'k6 로그'),
               ('-pub.log', '발행 로그'), ('-sub.log', '수신 로그'), ('.log', '콘솔 로그')]


def file_label(name):
    for suffix, label in FILE_LABELS:
        if name.endswith(suffix):
            return label
    return name


def summary_text(s):
    parts = []
    mq = s.get('mqtt') or {}
    if mq.get('sent') is not None:
        recv = mq.get('received')
        parts.append('MQTT 보냄 {:,} · 받음 {}{}'.format(
            mq['sent'], '{:,}'.format(recv) if recv is not None else '확인 불가',
            ' ({:.2%})'.format(mq['ratio']) if mq.get('ratio') is not None else ''))
        if mq.get('acked') is not None:
            parts.append('확인 응답 {:,}'.format(mq['acked']))
        if mq.get('connected') is not None:
            parts.append('연결 {:,}/{:,}'.format(mq['connected'], mq['sites']))
    ap = s.get('api') or {}
    if ap.get('p95_ms') is not None:
        parts.append('API 요청 {:,} · p95 {:.0f}ms · 실패 {:.2%}'.format(
            int(ap.get('reqs') or 0), ap['p95_ms'], ap.get('failed_rate') or 0))
    if s.get('path'):
        parts.append('경로 ' + {'direct': '직접', 'derp': '중계(DERP)'}.get(s['path'], '확인 불가'))
    if s.get('max_late_sec') is not None and s.get('load_sec'):
        parts.append('시설 지연 최대 {:+.1f}초'.format(s['max_late_sec']))
    return ' · '.join(parts)


def history(limit):
    try:
        names = os.listdir(RUNS_DIR)
    except OSError:
        return []
    ids = sorted((mt.group(1) for mt in (SUMMARY_RE.fullmatch(n) for n in names) if mt), reverse=True)[:limit]
    items = []
    for rid in ids:
        s = read_json_file(run_path(rid + '.summary.json'))
        if not s:
            continue
        files = [f for f in s.get('files', []) if isinstance(f, str) and RUN_FILE_RE.fullmatch(f)]
        items.append({'id': rid, 'label': s.get('label', ''), 'load': s.get('load', ''), 'by': s.get('by', ''),
                      'started': s.get('started'), 'outcome': s.get('outcome', ''), 'verdict': s.get('verdict'),
                      'reason': s.get('reason', ''), 'text': summary_text(s),
                      'files': [{'name': f, 'label': file_label(f)} for f in files]})
    return items


def cleanup_runs():
    try:
        names = os.listdir(RUNS_DIR)
    except OSError:
        return
    ids = sorted({mt.group(1) for mt in (SUMMARY_RE.fullmatch(n) for n in names) if mt}, reverse=True)
    old = set(ids[KEEP_RUNS:])
    if not old:
        return
    for n in names:
        rid = n.split('.', 1)[0]
        for cand in (rid, rid.rsplit('-', 1)[0]):
            if cand in old:
                try:
                    os.remove(run_path(n))
                except OSError:
                    pass
                break


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
SEC_HEADERS = [('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer'),
               ('X-Frame-Options', 'DENY'), ('Cross-Origin-Opener-Policy', 'same-origin'),
               ('Cache-Control', 'no-store')]
CSP_APP = "default-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
# k6 보고서는 스크립트가 들어 있는 HTML이라 콘솔과 다른 출처(sandbox)로 열어 콘솔 API에 손대지 못하게 한다.
CSP_REPORT = ("sandbox allow-scripts allow-popups; default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval'; "
              "style-src 'unsafe-inline'; img-src data: blob:; font-src data:")


def decode_name(value):
    """Tailscale-User-Name. 한글 이름은 RFC 2047로 오거나, UTF-8 바이트가 latin-1로 읽혀 올 수 있어 둘 다 푼다."""
    value = value or ''
    try:
        name = str(make_header(decode_header(value)))
    except Exception:
        name = value
    try:
        name = name.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    name = CONTROL_RE.sub('', name).strip()
    return name[:40]


def norm_host(host, scheme):
    host = (host or '').split(',')[0].strip().lower()
    default = ':443' if scheme == 'https' else ':80'
    return host[:-len(default)] if host.endswith(default) else host


def state_for(user):
    net = NET.get()
    env_items = check_env(net)
    env = {i['key']: i for i in env_items}
    run = RUNNER.current()
    presets = [{'id': p['id'], 'group': p['group'], 'label': p['label'], 'note': p.get('note', ''),
                'load': load_text(p), 'sec': p['sec'], 'blocked': blocked_reasons(p, env)} for p in PRESETS]
    return {'me': user, 'env': [{k: i[k] for k in ('label', 'ok', 'detail')} for i in env_items],
            'presets': presets, 'run': run.view() if run else None, 'history': history(HISTORY_SHOW),
            'k6_port': K6_DASH_PORT, 'manual_rules': MANUAL_STOP_RULES}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'coldguard-load-console'
    sys_version = ''
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass  # 요청마다 남기지 않는다(시험 시작·끝·거부만 log()로 남긴다)

    # ----- 응답 -----
    def send_body(self, code, body, ctype, csp=CSP_APP, extra=()):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        for k, v in SEC_HEADERS:
            self.send_header(k, v)
        self.send_header('Content-Security-Policy', csp)
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def send_json(self, code, data):
        self.send_body(code, json.dumps(data, ensure_ascii=False), 'application/json; charset=utf-8')

    def reject(self, code, reason, message):
        self.close_connection = True   # 읽지 않은 본문이 다음 요청에 섞이지 않게 연결을 닫는다
        log('load_console_rejected', reason=reason, method=self.command, path=self.url_path())
        self.send_json(code, {'error': reason, 'message': message})

    def url_path(self):
        return urllib.parse.urlsplit(self.path).path

    # ----- 인증·CSRF -----
    def identity(self):
        """tailscale serve가 붙이는 사용자 헤더. 로그인 이름(이메일)은 확인만 하고 어디에도 남기지 않는다."""
        if not self.headers.get('Tailscale-User-Login', '').strip():
            self.reject(403, 'no_identity', 'tailnet 사용자로만 접속할 수 있습니다(tailscale serve 주소로 접속해 주세요).')
            return None
        return decode_name(self.headers.get('Tailscale-User-Name', '')) or '이름 없음'

    def same_site(self):
        if self.headers.get('X-Requested-With') != 'load-console':
            self.reject(403, 'csrf', '콘솔 화면에서만 요청할 수 있습니다.')
            return False
        site = self.headers.get('Sec-Fetch-Site')
        if site and site != 'same-origin':
            self.reject(403, 'csrf', '다른 사이트에서 보낸 요청은 받지 않습니다.')
            return False
        origin = self.headers.get('Origin')
        if origin:
            parts = urllib.parse.urlsplit(origin)
            hosts = {norm_host(self.headers.get(h), parts.scheme) for h in ('Host', 'X-Forwarded-Host')}
            if parts.scheme not in ('https', 'http') or norm_host(parts.netloc, parts.scheme) not in hosts - {''}:
                self.reject(403, 'csrf', '다른 사이트에서 보낸 요청은 받지 않습니다.')
                return False
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            self.reject(415, 'json_required', 'JSON 요청만 받습니다.')
            return False
        return True

    def read_json(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= 1024:
            self.reject(413, 'too_large', '요청이 너무 큽니다.')
            return None
        raw = self.rfile.read(length) if length else b''
        try:
            data = json.loads(raw.decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            self.reject(400, 'invalid_json', 'JSON 형식이 아닙니다.')
            return None
        if not isinstance(data, dict):
            self.reject(400, 'invalid_json', 'JSON 객체여야 합니다.')
            return None
        return data

    # ----- 라우팅 -----
    def do_GET(self):
        path = self.url_path()
        if path == '/healthz':
            return self.send_json(200, {'status': 'ok'})
        user = self.identity()
        if user is None:
            return None
        if path == '/':
            return self.send_body(200, INDEX_HTML, 'text/html; charset=utf-8')
        if path == '/app.js':
            return self.send_body(200, APP_JS, 'text/javascript; charset=utf-8')
        if path == '/app.css':
            return self.send_body(200, APP_CSS, 'text/css; charset=utf-8')
        if path == '/api/state':
            return self.send_json(200, state_for(user))
        if path.startswith('/runs/'):
            return self.send_run_file(urllib.parse.unquote(path[len('/runs/'):]))
        return self.send_json(404, {'error': 'not_found'})

    def do_POST(self):
        path = self.url_path()
        user = self.identity()
        if user is None or not self.same_site():
            return None
        data = self.read_json()
        if data is None:
            return None
        if path == '/api/start':
            preset = next((p for p in PRESETS if p['id'] == data.get('preset')), None)
            if preset is None:
                return self.send_json(400, {'error': 'unknown_preset', 'message': '없는 프리셋입니다.'})
            code, body = RUNNER.start(preset, user)
            return self.send_json(code, body)
        if path == '/api/stop':
            code, body = RUNNER.stop(user)
            return self.send_json(code, body)
        return self.send_json(404, {'error': 'not_found'})

    def send_run_file(self, name):
        if not RUN_FILE_RE.fullmatch(name):
            return self.send_json(404, {'error': 'not_found'})
        try:
            with open(run_path(name), 'rb') as f:
                body = f.read(32 << 20)
        except OSError:
            return self.send_json(404, {'error': 'not_found'})
        if name.endswith('.html'):
            return self.send_body(200, body, 'text/html; charset=utf-8', csp=CSP_REPORT)
        if name.endswith('.json'):
            return self.send_body(200, body, 'application/json; charset=utf-8')
        return self.send_body(200, body, 'text/plain; charset=utf-8')


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------
INDEX_HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ColdGuard 부하 시험 콘솔</title>
<link rel="stylesheet" href="/app.css">
<script src="/app.js" defer></script>
</head>
<body>
<header>
  <h1>ColdGuard 부하 시험 콘솔</h1>
  <div id="me"></div>
</header>
<main>
  <div id="msg" class="msg" role="status"></div>
  <section class="card">
    <h2>지금 시험</h2>
    <div id="run-body"><p class="muted">불러오는 중…</p></div>
  </section>
  <section class="card">
    <h2>프리셋</h2>
    <p class="rules">시험 전 디스코드에 시간을 남기고, 아래 단계부터 진행합니다. MQTT는 따로 적지 않으면 QoS 0 기준입니다.
      시설 데이터가 시작 때보다 5초 넘게 늦어지거나(두 번 연속) k6 기준(p95 1초, 오류율 5%)을 넘으면 콘솔이 자동으로 멈춥니다.</p>
    <p class="rules">사람이 Grafana에서 보고 멈출 기준: <span id="manual-rules"></span></p>
    <div id="preset-groups"></div>
  </section>
  <section class="card">
    <h2>환경 점검</h2>
    <ul id="env-list" class="env"></ul>
  </section>
  <section class="card">
    <h2>지난 결과</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>시각</th><th>프리셋</th><th>시작한 사람</th><th>결과</th><th>요약</th><th>파일</th></tr></thead>
        <tbody id="history-body"></tbody>
      </table>
    </div>
  </section>
</main>
</body>
</html>
"""

APP_CSS = """
:root { --bg: #f5f6f4; --card: #fff; --ink: #1f2a24; --muted: #66706a; --line: #d8ddd8;
  --accent: #2f6b4f; --bad: #b3261e; --warn: #9a6700; --good: #1e7a46; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 15px/1.5 -apple-system, "Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif; }
header { display: flex; justify-content: space-between; align-items: baseline; padding: 16px 24px;
  background: var(--accent); color: #fff; }
header h1 { margin: 0; font-size: 20px; }
main { max-width: 1180px; margin: 0 auto; padding: 16px 24px 48px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 16px 20px; margin: 16px 0; }
.card h2 { margin: 0 0 12px; font-size: 17px; }
h3 { margin: 16px 0 8px; font-size: 14px; color: var(--muted); }
.muted { color: var(--muted); }
.small { font-size: 13px; }
.bad { color: var(--bad); }
.msg { min-height: 22px; font-weight: 600; color: var(--accent); }
.msg.bad { color: var(--bad); }
.rules { margin: 0 0 8px; color: var(--muted); font-size: 14px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
.preset { border: 1px solid var(--line); border-radius: 8px; padding: 12px; display: flex; flex-direction: column; gap: 4px; }
.preset .load { font-size: 14px; }
.preset button { margin-top: 8px; align-self: flex-start; }
button, a.button { font: inherit; border: 0; border-radius: 6px; padding: 7px 16px; cursor: pointer;
  background: var(--accent); color: #fff; text-decoration: none; display: inline-block; }
button:disabled { background: #b9c2bc; cursor: not-allowed; }
button.danger { background: var(--bad); }
.actions { display: flex; gap: 8px; margin: 10px 0; }
.bar { height: 8px; background: #e6eae6; border-radius: 4px; overflow: hidden; margin: 6px 0 10px; }
.bar .fill { height: 100%; background: var(--accent); }
.guard { font-weight: 600; }
pre.tail { background: #111a15; color: #d5e4da; padding: 10px; border-radius: 6px; overflow-x: auto;
  font: 12px/1.45 ui-monospace, Consolas, monospace; max-height: 260px; margin: 0; white-space: pre-wrap; }
.env { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 6px 16px; }
.env li { display: flex; gap: 8px; align-items: baseline; }
.env .mark { font-size: 12px; font-weight: 700; padding: 1px 6px; border-radius: 4px; color: #fff; background: var(--good); }
.env li.bad .mark { background: var(--bad); }
.env .detail { color: var(--muted); font-size: 13px; word-break: break-all; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th, td { text-align: left; padding: 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; white-space: nowrap; }
td.outcome.good { color: var(--good); font-weight: 600; }
td.outcome.bad { color: var(--bad); font-weight: 600; }
td.outcome.warn { color: var(--warn); font-weight: 600; }
td.files a { display: inline-block; margin: 0 8px 4px 0; color: var(--accent); }
"""

APP_JS = r"""'use strict';
(function () {
  var REFRESH_MS = 2000;
  var TAIL_LABEL = { console: '콘솔', pub: '발행 (emqtt-bench pub)', sub: '수신 확인 (emqtt-bench sub)', k6: 'k6' };
  var state = null;
  var sending = false;

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function fmtTime(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
      second: '2-digit', hour12: false });
  }
  function fmtSec(s) {
    s = Math.max(0, Math.round(s));
    var m = Math.floor(s / 60), r = s % 60;
    return m ? (m + '분 ' + (r < 10 ? '0' : '') + r + '초') : (r + '초');
  }
  function msg(text, bad) {
    var m = $('msg');
    m.textContent = text || '';
    m.className = bad ? 'msg bad' : 'msg';
  }
  function call(method, path, body) {
    var opt = { method: method, headers: { 'X-Requested-With': 'load-console' }, cache: 'no-store',
      credentials: 'same-origin' };
    if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    return fetch(path, opt).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        return { ok: r.ok, status: r.status, data: data || {} };
      });
    });
  }

  function refresh() {
    return call('GET', '/api/state').then(function (res) {
      if (!res.ok) { msg((res.data && res.data.message) || ('상태를 불러오지 못했습니다 (' + res.status + ')'), true); return; }
      state = res.data;
      render();
    }).catch(function () { msg('콘솔에 연결할 수 없습니다.', true); });
  }

  function render() {
    if (!state) return;
    $('me').textContent = state.me ? ('접속: ' + state.me) : '';
    $('manual-rules').textContent = (state.manual_rules || []).join(' · ');
    renderRun();
    renderPresets();
    renderEnv();
    renderHistory();
  }

  function renderRun() {
    var box = $('run-body');
    clear(box);
    var r = state.run;
    if (!r) { box.appendChild(el('p', 'muted', '실행 중인 시험이 없습니다.')); return; }
    var head = el('p');
    head.appendChild(el('strong', null, r.label));
    head.appendChild(el('span', 'muted', '  ' + r.load));
    box.appendChild(head);
    box.appendChild(el('p', null, '시작한 사람 ' + r.by + ' · ' + r.state_text + ' · 경과 ' + fmtSec(r.elapsed) +
      ' / ' + fmtSec(r.sec)));
    var bar = el('div', 'bar');
    var fill = el('div', 'fill');
    fill.style.width = Math.min(100, Math.round(100 * r.elapsed / r.sec)) + '%';
    bar.appendChild(fill);
    box.appendChild(bar);
    if (r.guard) box.appendChild(el('p', 'guard', '감시: ' + r.guard));
    if (state.manual_rules && state.manual_rules.length) {
      box.appendChild(el('p', 'muted small', 'Grafana에서 볼 중단 기준: ' + state.manual_rules.join(' · ')));
    }
    if (r.path) box.appendChild(el('p', null, 'Tailscale 경로: ' + r.path));
    var actions = el('div', 'actions');
    var stop = el('button', 'danger', r.state === 'stopping' ? '멈추는 중…' : '중지');
    stop.disabled = sending || r.state === 'stopping';
    stop.addEventListener('click', onStop);
    actions.appendChild(stop);
    if (r.k6) {
      var a = el('a', 'button', 'k6 대시보드 열기');
      a.href = 'https://' + location.hostname + ':' + state.k6_port + '/';
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      actions.appendChild(a);
    }
    box.appendChild(actions);
    ['console', 'pub', 'sub', 'k6'].forEach(function (name) {
      var lines = r.tails[name];
      if (!lines || !lines.length) return;
      box.appendChild(el('h3', null, TAIL_LABEL[name]));
      box.appendChild(el('pre', 'tail', lines.join('\n')));
    });
  }

  function renderPresets() {
    var root = $('preset-groups');
    clear(root);
    var running = !!state.run;
    var groups = [];
    state.presets.forEach(function (p) { if (groups.indexOf(p.group) < 0) groups.push(p.group); });
    groups.forEach(function (g) {
      root.appendChild(el('h3', null, g));
      var grid = el('div', 'grid');
      state.presets.filter(function (p) { return p.group === g; }).forEach(function (p) {
        var card = el('div', 'preset');
        card.appendChild(el('strong', null, p.label));
        card.appendChild(el('div', 'load', p.load));
        if (p.note) card.appendChild(el('div', 'muted small', p.note));
        if (p.blocked.length) card.appendChild(el('div', 'bad small', '준비 안 됨: ' + p.blocked.join(', ')));
        var b = el('button', null, '시작');
        b.disabled = running || sending || p.blocked.length > 0;
        b.addEventListener('click', function () { onStart(p); });
        card.appendChild(b);
        grid.appendChild(card);
      });
      root.appendChild(grid);
    });
  }

  function renderEnv() {
    var ul = $('env-list');
    clear(ul);
    state.env.forEach(function (it) {
      var li = el('li', it.ok ? 'ok' : 'bad');
      li.appendChild(el('span', 'mark', it.ok ? '정상' : '문제'));
      li.appendChild(el('span', null, it.label));
      if (it.detail) li.appendChild(el('span', 'detail', it.detail));
      ul.appendChild(li);
    });
  }

  function outcomeClass(h) {
    if (h.verdict === '통과') return 'good';
    if (h.outcome === '중지') return '';
    if (h.verdict === '판정 불가') return 'warn';
    return 'bad';
  }

  function renderHistory() {
    var tb = $('history-body');
    clear(tb);
    if (!state.history.length) {
      var tr0 = el('tr');
      var td0 = el('td', 'muted', '아직 결과가 없습니다.');
      td0.colSpan = 6;
      tr0.appendChild(td0);
      tb.appendChild(tr0);
      return;
    }
    state.history.forEach(function (h) {
      var tr = el('tr');
      tr.appendChild(el('td', null, fmtTime(h.started)));
      var t = el('td');
      t.appendChild(el('div', null, h.label));
      t.appendChild(el('div', 'muted small', h.load));
      tr.appendChild(t);
      tr.appendChild(el('td', null, h.by));
      var o = el('td', 'outcome ' + outcomeClass(h));
      o.appendChild(el('div', null, h.outcome + (h.verdict ? ' · ' + h.verdict : '')));
      if (h.reason) o.appendChild(el('div', 'muted small', h.reason));
      tr.appendChild(o);
      tr.appendChild(el('td', 'small', h.text));
      var f = el('td', 'files');
      h.files.forEach(function (x) {
        var a = el('a', null, x.label);
        a.href = '/runs/' + encodeURIComponent(x.name);
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        f.appendChild(a);
      });
      tr.appendChild(f);
      tb.appendChild(tr);
    });
  }

  function onStart(p) {
    if (!window.confirm(p.label + ' (' + p.load + ')을 시작할까요?\n\n시험 전에 디스코드에 시간을 알렸는지 확인해 주세요.')) return;
    sending = true;
    render();
    msg('시작 요청 중…');
    call('POST', '/api/start', { preset: p.id }).then(function (res) {
      sending = false;
      if (res.ok) msg('시작했습니다: ' + p.label);
      else msg(res.data.message || ('시작하지 못했습니다 (' + res.status + ')'), true);
      return refresh();
    }).catch(function () { sending = false; msg('요청을 보내지 못했습니다.', true); render(); });
  }

  function onStop() {
    if (!window.confirm('지금 시험을 멈출까요?')) return;
    sending = true;
    render();
    msg('중지 요청 중…');
    call('POST', '/api/stop', {}).then(function (res) {
      sending = false;
      if (res.ok) msg('멈추는 중입니다. 정리까지 몇 초 걸립니다.');
      else msg(res.data.message || ('멈추지 못했습니다 (' + res.status + ')'), true);
      return refresh();
    }).catch(function () { sending = false; msg('요청을 보내지 못했습니다.', true); render(); });
  }

  refresh();
  setInterval(function () { if (!document.hidden && !sending) refresh(); }, REFRESH_MS);
})();
"""


# ---------------------------------------------------------------------------
# 시작
# ---------------------------------------------------------------------------
def prepare_dirs():
    os.makedirs(RUNS_DIR, exist_ok=True)
    tmp = K6_SCRIPT_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(K6_SCRIPT)
    os.replace(tmp, K6_SCRIPT_PATH)


def cli_check():
    """배포 확인용: 환경 점검과 통제 API 조회를 한 번 해 보고 결과를 출력한다."""
    ok = True
    try:
        validate_presets(PRESETS)
        out('정상  프리셋 {}개(상한 이내)'.format(len(PRESETS)))
    except ValueError as exc:
        out('문제  프리셋: {}'.format(exc))
        ok = False
    net = NET.get(max_age=0)
    for item in check_env(net):
        out('{}  {}{}'.format('정상' if item['ok'] else '문제', item['label'],
                              ' ({})'.format(item['detail']) if item['detail'] else ''))
        ok = ok and item['ok']
    _, api = endpoints(net)
    if api and readable(secret_path('api.key')):
        try:
            ages = fetch_ages(api, read_secret('api.key'))
            fresh = [k for k, v in ages.items() if v <= GUARD_FRESH_SEC]
            out('{}  통제 API 조회 (냉동고 {}대, 정상 데이터 {}대)'.format('정상' if fresh else '문제', len(ages), len(fresh)))
            ok = ok and bool(fresh)
        except Exception as exc:
            out('문제  통제 API 조회 ({})'.format(describe_error(exc)))
            ok = False
    try:
        prepare_dirs()
        out('정상  결과 폴더 쓰기 ({})'.format(RUNS_DIR))
    except OSError as exc:
        out('문제  결과 폴더 쓰기 ({})'.format(type(exc).__name__))
        ok = False
    out('모두 정상' if ok else '문제가 있습니다')
    return 0 if ok else 1


def main(argv):
    if '--check' in argv:
        return cli_check()
    validate_presets(PRESETS)
    prepare_dirs()
    cleanup_runs()
    server = Server(('127.0.0.1', PORT), Handler)

    def shutdown():
        run = RUNNER.current()
        if run is not None and not run.stop_event.is_set():
            run.service_stop = True
            run.stop_event.set()
        deadline = time.time() + 45
        while RUNNER.current() is not None and time.time() < deadline:
            time.sleep(0.2)
        server.shutdown()

    def on_signal(signum, frame):
        threading.Thread(target=shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    log('load_console_start', port=PORT, presets=[p['id'] for p in PRESETS])
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        log('load_console_stop')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
