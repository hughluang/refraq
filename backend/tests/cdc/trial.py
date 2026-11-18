import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from backend.tests.cdc.assets import generate

PINS = {
    'pg': 'postgres@sha256:f1ea2a1a4fb7b68d4836be1fdcb8a6466a89b072158bf9d97663600538c294c5',
    'broker': 'apache/kafka@sha256:77e3df9054047a88b520d0cc46e16696d3b22022e1d580aeccd2632df6532837',
    'worker': 'quay.io/debezium/connect@sha256:a5b18259ee94139299fe64d6bbe8c59de5da7dab4c3dd7f50f2bc43f2f9be830',
}
DATA = {'pg': '/var/lib/postgresql', 'broker': '/var/lib/kafka/data'}
# Keep only fixed classifications, never raw JVM output (including REST/task traces).
STARTUP_FILTER = """awk '
function mark(value) { if (!seen[value]++) { print value; fflush() } }
/Starting Kafka Connect/                { mark("connect-start") }
/Starting REST server/                  { mark("rest-start") }
/NoSuchAlgorithmException/              { mark("NoSuchAlgorithmException") }
/KeyStoreException/                     { mark("KeyStoreException") }
/UnrecoverableKeyException/             { mark("UnrecoverableKeyException") }
/SSLHandshakeException/                { mark("SSLHandshakeException") }
/ConfigException/                       { mark("ConfigException") }
/ConnectException/                      { mark("ConnectException") }
/BindException/                         { mark("BindException") }
/Permission denied|Read-only file/      { mark("filesystem-access") }
/Exception in thread|ERROR|FATAL/       { mark("startup-error") }
'"""
STARTUP_MARKERS = frozenset({
    'connect-start', 'rest-start', 'NoSuchAlgorithmException', 'KeyStoreException',
    'UnrecoverableKeyException', 'SSLHandshakeException', 'ConfigException',
    'ConnectException', 'BindException', 'filesystem-access', 'startup-error',
})


class Trial:
    def __init__(self, root):
        self.root = root
        self.prefix = 'refraq-' + uuid.uuid4().hex
        self.label = 'refraq.cdc=' + self.prefix
        self.deadline = time.monotonic() + 300
        self.images = {}
        self.running = set()
        self.markers = root / 'worker-startup'

    def docker(self, *args, data=None, check=True):
        seconds = self.deadline - time.monotonic()
        if seconds <= 0:
            raise RuntimeError('Trial deadline exceeded')
        try:
            result = subprocess.run(['docker', '--host', 'unix:///var/run/docker.sock', *args],
                                    input=data, capture_output=True, text=True, timeout=min(40, seconds),
                                    env={'PATH': os.defpath + ':/usr/local/bin', 'HOME': str(self.root)})
        except subprocess.TimeoutExpired:
            raise RuntimeError('Docker command timed out; raw output withheld') from None
        except OSError:
            raise RuntimeError('Docker command unavailable; raw output withheld') from None
        if check and result.returncode:
            raise RuntimeError(f'Docker {args[0]} failed ({result.returncode}); raw output withheld')
        return result.stdout.strip() if not result.returncode else None

    def clean(self):
        self.deadline = time.monotonic() + 90
        failed = []
        for kind in ('container', 'volume', 'network'):
            try:
                ids = self.docker(kind, 'ls', *(['-a'] if kind == 'container' else []), '-q', '--filter', 'label='+self.label)
                if ids:
                    self.docker(kind, 'rm', *(['-f', '-v'] if kind == 'container' else []), *ids.splitlines())
            except RuntimeError:
                failed.append(kind)
        if failed:
            raise RuntimeError('Trial cleanup incomplete: ' + ','.join(failed))

    def start(self, name, script, *flags):
        self.docker('run', '-d', '--pull=never', '--read-only', '--name', self.prefix+name,
                    '--label', self.label, '--network', self.prefix, '--network-alias', name,
                    '--cpus=1', '--memory=1536m', '--memory-swap=1536m', '--pids-limit=256',
                    '--log-driver=none', '--tmpfs', '/tmp:size=32m,mode=1777',
                    '--mount', f'type=bind,src={self.root/name},dst=/trial,readonly',
                    *flags, '--entrypoint', 'bash', self.images[name], '-ec', script)
        self.running.add(name)

    def exe(self, name, *args, **kwargs):
        return self.docker('exec', '-i', self.prefix+name, *args, **kwargs)

    def wait(self, name, probe):
        end = time.monotonic() + 75
        while time.monotonic() < end:
            state = self.docker('inspect', '-f', '{{.State.Running}} {{.State.ExitCode}} {{.State.OOMKilled}}',
                                self.prefix+name).split()
            if state[0] != 'true':
                raise RuntimeError(f'{name} stopped during readiness (exit={int(state[1])}, '
                                   f'oom={state[2] == "true"}){self.startup_evidence(name)}')
            self.check_storage()
            if probe():
                return
            time.sleep(1)
        raise RuntimeError(f'{name} readiness timeout{self.startup_evidence(name)}')

    def startup_evidence(self, name):
        if name != 'worker' or not self.markers.exists():
            return ''
        markers = STARTUP_MARKERS.intersection(self.markers.read_text().splitlines())
        return '; startup=' + (','.join(sorted(markers)) or 'no-markers')

    def sql(self, statement, check=True):
        return self.exe('pg', 'gosu', 'postgres', 'psql', '-XAtq', '-v', 'ON_ERROR_STOP=1',
                        data=statement+'\n', check=check)

    def rest(self, path, *opts, **kwargs):
        return self.exe('worker', 'curl', '--silent', '--fail', '--max-time', '5', '--cacert',
                        '/trial/ca.pem', '--key', '/trial/key.pem', '--cert', '/trial/cert.pem',
                        'https://worker:8083/'+path, *opts, **kwargs)

    def setup(self):
        assert shutil.disk_usage(self.root).free >= 2*1024**3
        for name, pin in PINS.items():
            image = json.loads(self.docker('image', 'inspect', '-f', '{{json .}}', pin))
            if (image.get('Os'), image.get('Architecture')) != ('linux', 'amd64') or not re.fullmatch(
                r'sha256:[0-9a-f]{64}', image.get('Id', '')
            ) or pin not in image.get('RepoDigests', []):
                raise RuntimeError('Unexpected local image identity or platform')
            self.images[name] = image['Id']
        ddl = generate(self.root)
        self.docker('network', 'create', '--internal', '--label', self.label, self.prefix)
        for name in DATA:
            self.docker('volume', 'create', '--label', self.label, self.prefix+name)
        self.start('pg', 'install -m600 -o postgres /trial/key.pem /tmp/pg.key; '
                   'exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/trial/cert.pem '
                   '-c ssl_key_file=/tmp/pg.key -c hba_file=/trial/hba -c wal_level=logical '
                   '-c max_slot_wal_keep_size=64MB', '-v', self.prefix+'pg:'+DATA['pg'],
                   '--tmpfs', '/var/run/postgresql:size=2m', '-e', 'POSTGRES_PASSWORD_FILE=/trial/bootstrap')
        self.wait('pg', lambda: self.sql('SHOW server_version_num;', False) == '180006' and
                  self.exe('pg', 'pg_isready', '-h', '127.0.0.1', check=False) is not None)
        self.sql(ddl)
        self.sql("SELECT pg_create_logical_replication_slot('trial','pgoutput');")
        self.start('broker', 'cd /opt/kafka/bin; test -f ../libs/kafka_2.13-4.3.1.jar || exit 61; '
                   'cluster_id=$(./kafka-storage.sh random-uuid) || exit 62; '
                   './kafka-storage.sh format -t "$cluster_id" -c /trial/server >/tmp/format 2>&1 || exit 63; '
                   'exec ./kafka-server-start.sh /trial/server >/tmp/bootstrap 2>&1',
                   '-v', self.prefix+'broker:'+DATA['broker'], '--tmpfs', '/etc/kafka/secrets:size=1m',
                   '--tmpfs', '/mnt/shared/config:size=1m', '-e', 'LOG_DIR=/tmp',
                   '-e', 'KAFKA_HEAP_OPTS=-Xms192m -Xmx384m')
        self.wait('broker', lambda: self.exe(
            'broker', '/opt/kafka/bin/kafka-topics.sh', '--bootstrap-server', 'broker:9092',
            '--command-config', '/trial/client', '--list', check=False) is not None)
        self.markers.touch(mode=0o666)
        self.markers.chmod(0o666)  # Different container UID, protected by the private parent.
        self.start('worker', 'set -- /kafka/libs/connect-runtime-*.jar; '
                   'test "$#" = 1 && test -f "$1" || exit 64; '
                   'test -f /kafka/connect/debezium-connector-postgres/debezium-connector-postgres-3.7.1.Final.jar || exit 65; '
                   'command -v curl >/dev/null || exit 66; '
                   'if [ ! -f /tmp/rest-trust.p12 ]; then '
                   'keytool -importcert -noprompt -alias trial-ca -file /trial/ca.pem '
                   '-keystore /tmp/rest-trust.p12 -storetype PKCS12 '
                   '-storepass:file /trial/store-password >/dev/null 2>&1 || exit 67; fi; '
                   'exec /kafka/bin/connect-distributed.sh /trial/config '
                   f'> >({STARTUP_FILTER} > /trial-startup) 2>&1',
                   '--mount', f'type=bind,src={self.markers},dst=/trial-startup',
                   '--tmpfs', '/kafka/config:size=4m', '--tmpfs', '/kafka/data:size=4m',
                   '--tmpfs', '/kafka/logs:size=8m,mode=1777', '-e', 'LOG_DIR=/tmp',
                   '-e', 'KAFKA_HEAP_OPTS=-Xms192m -Xmx384m')
        self.wait('worker', lambda: self.rest('', check=False))
        self.worker_version = self.connect_version()
        assert json.loads(self.rest(''))['version'] == self.worker_version
        assert any(p['class'].endswith('.PostgresConnector') and p['version'] == '3.7.1.Final'
                   for p in json.loads(self.rest('connector-plugins')))
        config = {'connector.class': 'io.debezium.connector.postgresql.PostgresConnector', 'tasks.max': '1',
                  'database.hostname': 'pg', 'database.dbname': 'postgres', 'database.port': '5432',
                  'database.sslmode': 'verify-full', 'database.sslrootcert': '/trial/ca.pem',
                  'database.user': '${file:/trial/credentials:user}', 'database.password': '${file:/trial/credentials:password}',
                  'topic.prefix': 'trial', 'plugin.name': 'pgoutput', 'publication.name': 'trial',
                  'publication.autocreate.mode': 'disabled', 'slot.name': 'trial', 'table.include.list': 'public.items',
                  'snapshot.mode': 'no_data', 'tombstones.on.delete': 'false'}
        self.rest('connectors/trial/config', '-X', 'PUT', '-H', 'Content-Type: application/json',
                  '--data-binary', '@-', data=json.dumps(config))

    def connect_version(self):
        jars = self.exe('worker', 'bash', '-ec', 'printf "%s\\n" /kafka/libs/connect-runtime-*.jar')
        match = re.fullmatch(r'/kafka/libs/connect-runtime-(\d+\.\d+\.\d+)\.jar', jars)
        if not match:
            raise RuntimeError('Unknown installed Connect runtime version')
        return match[1]

    def await_stream(self):
        self.wait('worker', lambda: self.sql("SELECT active FROM pg_replication_slots WHERE slot_name='trial'") == 't')
        self.check_storage()

    def check_storage(self):
        if shutil.disk_usage(self.root).free < 2*1024**3:
            raise RuntimeError('Trial host storage limit reached')
        for name, path in DATA.items():
            if name not in self.running:
                continue
            usage = self.exe(name, 'du', '-sk', path)
            if int(usage.split()[0]) >= 512*1024:
                raise RuntimeError('Trial volume storage limit reached')
            if int(self.exe(name, 'df', '-Pk', path).splitlines()[-1].split()[3]) <= 2*1024**2:
                raise RuntimeError('Trial volume free storage limit reached')

    def confirmed_lsn(self):
        value = self.sql("SELECT confirmed_flush_lsn FROM pg_replication_slots WHERE slot_name='trial'")
        high, low = value.split('/')
        return (int(high, 16) << 32) + int(low, 16)

    def source_offset(self):
        offsets = json.loads(self.rest('connectors/trial/offsets'))['offsets']
        if not offsets:
            return None
        if len(offsets) != 1 or offsets[0]['partition'] != {'server': 'trial'}:
            raise RuntimeError('Unexpected source offset partition')
        return offsets[0]['offset']

    def await_checkpoint(self, previous_lsn, previous_offset=None):
        checkpoint = None

        def advanced():
            nonlocal checkpoint
            lsn, offset = self.confirmed_lsn(), self.source_offset()
            if lsn > previous_lsn and offset and offset.get('lsn', 0) > (previous_offset or {}).get('lsn', 0):
                checkpoint = lsn, offset
                return True
            return False

        self.wait('worker', advanced)
        return checkpoint

    def partition_end(self):
        result = self.exe('broker', '/opt/kafka/bin/kafka-get-offsets.sh',
                          '--bootstrap-server', 'broker:9092', '--command-config', '/trial/client',
                          '--topic', 'trial.public.items', '--time', 'latest')
        topic, partition, offset = result.split(':')
        if topic != 'trial.public.items' or partition != '0':
            raise RuntimeError('Unexpected event partition')
        return int(offset)

    def slot_identity(self):
        return self.exe('pg', 'sh', '-ec', 'stat -c %d:%i "$PGDATA/pg_replslot/trial"')

    def restart_worker(self):
        self.docker('restart', '--time', '15', self.prefix+'worker')
        self.wait('worker', lambda: self.rest('', check=False))
        self.await_stream()

    def consume(self, count):
        raw = self.exe('broker', '/opt/kafka/bin/kafka-console-consumer.sh', '--bootstrap-server', 'broker:9092',
                       '--consumer.config', '/trial/client', '--topic', 'trial.public.items', '--partition', '0',
                       '--offset', 'earliest', '--max-messages', str(count), '--timeout-ms', '20000',
                       '--formatter-property', 'print.offset=true', '--formatter-property', 'print.key=true')
        events = []
        for line in raw.splitlines():
            offset, key, value = line.split('\t')
            envelope = json.loads(value)
            events.append((int(offset.removeprefix('Offset:')), json.loads(key), envelope['op'],
                           envelope['before'], envelope['after']))
        return events


@contextmanager
def disposable_profile():
    with tempfile.TemporaryDirectory(prefix='refraq-cdc-') as tmp:
        trial = Trial(Path(tmp))
        try:
            trial.setup()
            yield trial
        finally:
            trial.clean()
