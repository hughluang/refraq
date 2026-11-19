import ipaddress
import json
import re
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from backend.tests.cdc.assets import properties
from backend.tests.cdc.eos_kafka import KafkaProbe
from backend.tests.cdc.trial import DATA, Trial

WORKER = {
    'exactly.once.source.support': 'enabled',
    'connector.client.config.override.policy': 'None',
    'producer.transaction.timeout.ms': 60000,
    'producer.interceptor.classes': 'CrashOnAck',
}
CONNECTOR = {'exactly.once.support': 'required', 'transaction.boundary': 'poll', 'errors.tolerance': 'none'}
BROKER = {
    'listeners': 'SSL://:9092,CTRL://:9093,PROBE://:9094',
    'listener.security.protocol.map': 'SSL:SSL,CTRL:SSL,PROBE:SSL',
    'transaction.state.log.replication.factor': 1,
    'transaction.state.log.min.isr': 1,
    'transaction.state.log.num.partitions': 1,
    'transaction.max.timeout.ms': 120000,
    'min.insync.replicas': 1,
    'log.cleanup.policy': 'delete',
    'log.retention.ms': -1,
    'log.retention.bytes': -1,
}
BATCH = re.compile(r'^baseOffset: (\d+) lastOffset: (\d+) .* isTransactional: (true|false) isControl: (true|false) ')
MARKER = re.compile(r' endTxnMarker: (COMMIT|ABORT) ')


def override_properties(path, options):
    previous = [line for line in path.read_text().splitlines() if line.partition('=')[0] not in options]
    staged = path.with_name(path.name + '.eos')
    staged.touch(mode=0o600)
    staged.write_text('\n'.join(previous) + '\n' + properties(options))
    staged.chmod(0o444)
    staged.replace(path)


class EosTrial(Trial):
    def wait(self, name, probe):
        return super().wait(name, self.kafka.ready if name == 'broker' else probe)

    def start(self, name, script, *flags):
        if name == 'worker':
            directory = self.root / name
            tls = dict(line.split('=', 1) for line in (self.root / 'broker/client').read_text().splitlines())
            override_properties(directory / 'config', {
                **WORKER, **{f'consumer.{key}': value for key, value in tls.items()},
            })
            (directory / 'CrashOnAck.java').write_bytes(Path(__file__).with_name('CrashOnAck.java').read_bytes())
            script = ('mkdir -p /tmp/eos-classes; rm -f /tmp/eos-ack-blocked; '
                      'java -m jdk.compiler/com.sun.tools.javac.Main -cp /kafka/libs/kafka-clients-4.3.1.jar '
                      '-d /tmp/eos-classes /trial/CrashOnAck.java >/dev/null 2>&1 || exit 68; '
                      'export CLASSPATH=/tmp/eos-classes; ' + script)
        if name != 'broker':
            super().start(name, script, *flags)
            return
        super().start(name, 'for attempt in {1..100}; do '
                      'if [ -f /trial/probe-ready ]; then break; fi; sleep 0.1; done; '
                      'test -f /trial/probe-ready; ' + script, *flags)
        self.configure_broker_probe()

    def configure_broker_probe(self):
        output = self.docker('inspect', '-f', '{{json .NetworkSettings.Networks}}', self.prefix+'broker')
        address = ipaddress.IPv4Address(json.loads(output)[self.prefix]['IPAddress'])
        (self.root / 'extensions').write_text(
            f'subjectAltName=DNS:broker,IP:{address}\nextendedKeyUsage=serverAuth,clientAuth\n'
        )
        self.openssl('req', '-new', '-key', 'broker/key.pem', '-out', 'broker.csr', '-subj', '/CN=broker')
        self.openssl('x509', '-req', '-in', 'broker.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key', '-CAcreateserial',
                     '-days', '1', '-extfile', 'extensions', '-out', 'probe.pem')
        self.openssl('pkcs12', '-export', '-in', 'probe.pem', '-inkey', 'broker/key.pem',
                     '-certfile', 'ca.pem', '-out', 'probe.p12', '-passout', 'file:worker/store-password')
        identity = self.root / 'probe.p12'
        identity.chmod(0o444)
        identity.replace(self.root / 'broker/identity.p12')
        override_properties(self.root / 'broker/server', {
            **BROKER, 'advertised.listeners': f'SSL://broker:9092,PROBE://{address}:9094',
        })
        self.kafka = KafkaProbe(self.root, address)
        (self.root / 'broker/probe-ready').touch()

    def openssl(self, *args):
        try:
            subprocess.run(['openssl', *args], cwd=self.root, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=True, timeout=4)
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError('EOS listener certificate setup failed') from None

    def rest(self, path, *opts, **kwargs):
        if path == 'connectors/trial/config' and '-X' in opts:
            kwargs['data'] = json.dumps({**json.loads(kwargs['data']), **CONNECTOR})
        return super().rest(path, *opts, **kwargs)

    def setup(self):
        super().setup()
        assert self.worker_version == '4.3.1'
        config = json.loads(self.rest('connectors/trial/config'))
        assert all(config.get(key) == value for key, value in CONNECTOR.items()), 'Unexpected Connect EOS configuration'
        assert config.get('tasks.max') == '1' and not any(
            key == 'transforms' or key.startswith('producer.override.') for key in config
        ), 'Unexpected task fanout or connector override'
        self.await_stream()

    @contextmanager
    def arm_crash(self):
        trigger = self.root / 'worker/crash-arm'
        trigger.touch()
        try:
            yield
        finally:
            trigger.unlink()
            trigger.with_name('crash-release').unlink(missing_ok=True)

    def await_crash_boundary(self):
        self.wait('worker', lambda: self.exe('worker', 'test', '-f', '/tmp/eos-ack-blocked', check=False) is not None)

    def release_crash_boundary(self):
        (self.root / 'worker/crash-release').touch()

    def kill_worker(self):
        name = self.prefix + 'worker'
        self.docker('kill', '--signal', 'KILL', name)
        assert self.docker('wait', name) == '137'

    def resume_worker(self):
        self.docker('start', self.prefix + 'worker')
        self.wait('worker', lambda: self.rest('', check=False))
        self.await_stream()

    def disconnect_postgres(self):
        name = self.prefix + 'pg'
        self.docker('network', 'disconnect', self.prefix, name)
        assert self.docker('inspect', '-f', '{{len .NetworkSettings.Networks}}', name) == '0'

    def reconnect_postgres(self):
        terminated = self.sql("SELECT pg_terminate_backend(active_pid, 5000) FROM pg_replication_slots "
                              "WHERE slot_name='trial' AND active;")
        assert terminated in ('', 't'), 'Old replication sender did not exit'
        self.docker('network', 'connect', '--alias', 'pg', self.prefix, self.prefix + 'pg')

    def crash_postgres(self):
        assert self.exe('pg', 'sh', '-ec', 'head -n 1 "$PGDATA/postmaster.pid"') == '1'
        name = self.prefix + 'pg'
        self.docker('kill', '--signal', 'QUIT', name)
        assert self.docker('wait', name) == '0'

    def resume_postgres(self):
        self.docker('start', self.prefix + 'pg')
        self.wait('pg', lambda: self.sql('SELECT NOT pg_is_in_recovery();', check=False) == 't' and
                  self.exe('pg', 'pg_isready', '-h', '127.0.0.1', check=False) is not None)

    def slot_lsns(self, *, active):
        row = self.sql("SELECT active, restart_lsn - '0/0'::pg_lsn, confirmed_flush_lsn - '0/0'::pg_lsn "
                       "FROM pg_replication_slots WHERE slot_name='trial';")
        status, restart, confirmed = row.split('|')
        assert (status == 't') == active, f'Unexpected slot state: {row}'
        assert 0 < int(restart) <= int(confirmed), f'Unexpected slot LSNs: {row}'
        return int(restart), int(confirmed)

    def source_lineage(self):
        postgres = self.sql('SELECT system_identifier FROM pg_control_system();')
        timeline = self.sql('SELECT timeline_id FROM pg_control_checkpoint();')
        slot = self.sql("SELECT plugin, database, wal_status, coalesce(invalidation_reason,'ok'), failover, synced "
                        "FROM pg_replication_slots WHERE slot_name='trial';")
        assert slot == 'pgoutput|postgres|reserved|ok|f|f'
        return postgres, timeline, self.slot_identity()

    def committed_source_offset(self):
        records, end = self.kafka.scan('offsets', committed=True)
        start, stable, _ = self.kafka.bounds('offsets').positions
        assert start == 0 and end == stable, 'Incomplete Connect offset-topic scan'
        assert records, 'Missing committed Connect source offset'
        for _, key, _ in records:
            assert json.loads(key) == ['trial', {'server': 'trial'}], 'Unexpected Connect offset key'
        position, _, value = records[-1]
        assert value is not None, 'Connect source offset was deleted'
        checkpoint = json.loads(value)
        assert isinstance(checkpoint['lsn'], int) and checkpoint['lsn'] > 0
        return position, checkpoint

    def log_batches(self, topic):
        assert re.fullmatch(r'[a-zA-Z0-9_.-]+', topic)
        raw = self.exe('broker', 'bash', '-ec',
                       'shopt -s nullglob; files=("$1"/*.log); test "${#files[@]}" = 1; '
                       'exec /opt/kafka/bin/kafka-dump-log.sh --deep-iteration --files "${files[0]}"',
                       'dump', f'{DATA["broker"]}/{topic}-0')
        batches = []
        for line in raw.splitlines():
            batch = BATCH.match(line)
            marker = MARKER.search(line)
            if batch:
                first, last, transactional, control = batch.groups()
                assert transactional == 'true', f'Nontransactional batch at offset {first} in {topic}'
                batches.append((int(first), int(last), 'CONTROL' if control == 'true' else 'DATA'))
            if marker:
                first, last, kind = batches[-1]
                assert kind == 'CONTROL' and first == last
                batches[-1] = (first, last, marker[1])
        assert batches and all(kind != 'CONTROL' for _, _, kind in batches)
        return batches

    def clean(self):
        super().clean()
        for kind in ('container', 'volume', 'network'):
            flags = ['-a'] if kind == 'container' else []
            assert not self.docker(kind, 'ls', *flags, '-q', '--filter', 'label='+self.label)


@contextmanager
def disposable_eos_profile():
    with tempfile.TemporaryDirectory(prefix='refraq-cdc-eos-') as tmp:
        trial = EosTrial(Path(tmp))
        try:
            trial.setup()
            yield trial
        finally:
            trial.clean()
    assert not trial.root.exists()
