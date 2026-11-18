"""Offline checks for the disposable CDC harness; never contact a daemon."""

import importlib
import json
import subprocess

import pytest

from backend.tests.cdc.assets import generate
from backend.tests.cdc.trial import Trial, disposable_profile


def test_timeout_does_not_expose_credentials(monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1, output='private-password', stderr='private-key')

    monkeypatch.setattr(subprocess, 'run', timeout)
    with pytest.raises(RuntimeError, match='timed out') as failure:
        Trial(tmp_path).docker('exec', 'private-password')
    assert 'private-password' not in str(failure.value)
    assert 'private-key' not in str(failure.value)
    assert failure.value.__suppress_context__


def test_cleanup_attempts_all_owned_resources_after_failure(monkeypatch, tmp_path):
    trial = Trial(tmp_path)
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        if args[:2] == ('container', 'rm'):
            raise RuntimeError('container removal failed')
        return 'owned-id' if args[1] == 'ls' else ''

    monkeypatch.setattr(trial, 'docker', docker)
    with pytest.raises(RuntimeError, match='cleanup incomplete'):
        trial.clean()
    assert {call[0] for call in calls if call[1] == 'rm'} == {'container', 'volume', 'network'}
    assert '-v' in next(call for call in calls if call[:2] == ('container', 'rm'))
    assert all('label=' + trial.label in call for call in calls if call[1] == 'ls')


def test_worker_config_separates_rest_tls_and_kafka_tls(tmp_path):
    tmp_path.chmod(0o700)
    generate(tmp_path)
    config = dict(line.split('=', 1) for line in (tmp_path / 'worker/config').read_text().splitlines())
    assert config['listeners.https.ssl.client.auth'] == 'required'
    assert config['listeners.https.ssl.truststore.type'] == 'PKCS12'
    assert config['listeners.https.ssl.truststore.location'] == '/tmp/rest-trust.p12'
    assert config['ssl.truststore.type'] == 'PEM'
    assert config['producer.acks'] == 'all'
    assert config['config.providers.file.param.allowed.paths'] == '/trial/credentials'
    assert config['config.storage.topic'] == 'configs'
    assert config['offset.storage.topic'] == 'offsets'
    assert config['status.storage.topic'] == 'status'
    broker = dict(line.split('=', 1) for line in (tmp_path / 'broker/server').read_text().splitlines())
    assert broker['ssl.client.auth'] == 'required'
    assert broker['listener.security.protocol.map'] == 'SSL:SSL,CTRL:SSL'
    assert broker['log.retention.bytes'] == '16777216'
    assert broker['log.segment.bytes'] == '8388608'
    assert broker['log.flush.interval.messages'] == '1'
    assert broker['num.partitions'] == '1'
    credentials = dict(line.split('=', 1) for line in (tmp_path / 'worker/credentials').read_text().splitlines())
    assert credentials['password'] not in (tmp_path / 'worker/config').read_text()
    assert not (tmp_path / 'worker/ca.key').exists()
    assert 'ssl.endpoint.identification.algorithm' not in config or config['ssl.endpoint.identification.algorithm'] == 'https'
    assert (tmp_path / 'ca.key').stat().st_mode & 0o077 == 0
    assert tmp_path.stat().st_mode & 0o077 == 0


def test_consume_preserves_full_key(monkeypatch, tmp_path):
    trial = Trial(tmp_path)
    event = {'op': 'c', 'before': None, 'after': {'id': 7, 'value': 'first'}}
    monkeypatch.setattr(trial, 'exe', lambda *args, **kwargs: 'Offset:0\t{"id":7}\t' + json.dumps(event))
    assert trial.consume(1) == [(0, {'id': 7}, 'c', None, {'id': 7, 'value': 'first'})]


def test_checkpoint_requires_both_durable_offset_and_source_feedback(monkeypatch, tmp_path):
    trial = Trial(tmp_path)
    polls = []
    checkpoints = iter([(10, {'lsn': 11}), (11, {'lsn': 10}), (11, {'lsn': 11})])
    current = [None]

    def wait(name, probe):
        for checkpoint in checkpoints:
            current[0] = checkpoint
            polls.append(checkpoint)
            if probe():
                return
        pytest.fail('checkpoint did not advance')

    monkeypatch.setattr(trial, 'wait', wait)
    monkeypatch.setattr(trial, 'confirmed_lsn', lambda: current[0][0], raising=False)
    monkeypatch.setattr(trial, 'source_offset', lambda: current[0][1], raising=False)
    assert trial.await_checkpoint(10, {'lsn': 10}) == (11, {'lsn': 11})
    assert len(polls) == 3


@pytest.mark.parametrize('platform', [('linux', 'arm64'), ('windows', 'amd64')])
def test_setup_rejects_wrong_platform_before_provisioning(monkeypatch, tmp_path, platform):
    trial = Trial(tmp_path)
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        return json.dumps({'Id': 'sha256:' + 'a' * 64, 'Os': platform[0], 'Architecture': platform[1], 'RepoDigests': [args[-1]]})

    monkeypatch.setattr(trial, 'docker', docker)
    with pytest.raises(RuntimeError, match='image identity'):
        trial.setup()
    assert all(call[:2] == ('image', 'inspect') for call in calls)


def test_worker_version_is_discovered_not_inferred_from_broker(monkeypatch, tmp_path):
    trial = Trial(tmp_path)
    calls = []

    def exe(*args, **kwargs):
        calls.append(args)
        return '/kafka/libs/connect-runtime-4.2.0.jar'

    monkeypatch.setattr(trial, 'exe', exe)
    assert trial.connect_version() == '4.2.0'
    assert calls[0][0] == 'worker'


@pytest.mark.parametrize('opt_in', [None, '', 'true', '0', '1'])
def test_integration_gate_requires_exact_explicit_opt_in(monkeypatch, opt_in):
    if opt_in is None:
        monkeypatch.delenv('REFRAQ_CDC_TRIAL', raising=False)
    else:
        monkeypatch.setenv('REFRAQ_CDC_TRIAL', opt_in)
    module = importlib.import_module('backend.tests.test_source_capture_cdc_integration')
    module = importlib.reload(module)
    marker = next(mark for mark in module.test_keyed_changes_replay_across_worker_restart.pytestmark if mark.name == 'skipif')
    assert marker.args[0] is (opt_in != '1')


def test_docker_is_local_bounded_and_does_not_inherit_credentials(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setenv('DOCKER_HOST', 'tcp://production:2375')
    monkeypatch.setenv('SOURCE_PASSWORD', 'private-password')

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout='ok', stderr='')

    monkeypatch.setattr(subprocess, 'run', run)
    trial = Trial(tmp_path)
    trial.images['pg'] = 'sha256:' + 'a' * 64
    trial.start('pg', 'exec postgres')
    command, options = calls[0]
    assert command[:3] == ['docker', '--host', 'unix:///var/run/docker.sock']
    assert 0 < options['timeout'] <= 40
    assert set(options['env']) == {'PATH', 'HOME'}
    for flag in ('--pull=never', '--read-only', '--cpus=1', '--memory=1536m', '--pids-limit=256', '--log-driver=none'):
        assert flag in command
    assert '--publish' not in command and '-p' not in command
    assert command[command.index('--network') + 1] == trial.prefix
    assert command[command.index('--label') + 1] == trial.label
    trial.deadline = 0
    with pytest.raises(RuntimeError, match='deadline'):
        trial.docker('version')
    assert len(calls) == 1


def test_context_cleans_partial_setup_failure(monkeypatch):
    cleaned = []

    def fail(self):
        raise RuntimeError('setup failed')

    monkeypatch.setattr(Trial, 'setup', fail)
    monkeypatch.setattr(Trial, 'clean', lambda self: cleaned.append(self.root))
    with pytest.raises(RuntimeError, match='setup failed'):
        with disposable_profile():
            pytest.fail('partial setup was yielded')
    assert len(cleaned) == 1
    assert not cleaned[0].exists()


def test_setup_readiness_accepts_successful_empty_pg_probe(monkeypatch, tmp_path):
    trial = Trial(tmp_path)
    scripts = {}

    def docker(*args, **kwargs):
        if args[:2] == ('image', 'inspect'):
            return json.dumps({'Id': 'sha256:' + 'a' * 64, 'Os': 'linux', 'Architecture': 'amd64', 'RepoDigests': [args[-1]]})
        return ''

    monkeypatch.setattr(trial, 'docker', docker)
    monkeypatch.setattr('backend.tests.cdc.trial.generate', lambda root: 'DDL')
    monkeypatch.setattr(trial, 'start', lambda name, script, *flags: scripts.update({name: script}))
    monkeypatch.setattr(trial, 'sql', lambda sql, *args: '180006' if sql.startswith('SHOW') else '')
    monkeypatch.setattr(trial, 'exe', lambda *args, **kwargs: '')
    monkeypatch.setattr(trial, 'connect_version', lambda: '4.2.0')
    monkeypatch.setattr(trial, 'rest', lambda path, *args, **kwargs: json.dumps(
        [{'class': 'io.debezium.connector.postgresql.PostgresConnector', 'version': '3.7.1.Final'}]
        if path == 'connector-plugins' else {'version': '4.2.0'}
    ))

    def wait(name, probe):
        assert probe(), name + ' readiness must accept a successful probe'

    monkeypatch.setattr(trial, 'wait', wait)
    trial.setup()
    assert 'if [ ! -f /tmp/rest-trust.p12 ]' in scripts['worker']
    assert 'connect-runtime-4.3.1.jar' not in scripts['worker']


def test_wait_checks_storage_before_probe(monkeypatch, tmp_path):
    trial = Trial(tmp_path)
    checked = []
    monkeypatch.setattr(trial, 'docker', lambda *args, **kwargs: 'true 0 false')
    monkeypatch.setattr(trial, 'check_storage', lambda: checked.append(True), raising=False)
    trial.wait('worker', lambda: True)
    assert checked == [True]


def test_storage_limit_aborts_at_limit(monkeypatch, tmp_path):
    trial = Trial(tmp_path)
    trial.running = {'pg'}
    monkeypatch.setattr(trial, 'exe', lambda *args, **kwargs: '524288\t/var/lib/postgresql')
    with pytest.raises(RuntimeError, match='storage limit'):
        trial.check_storage()


def test_restart_waits_for_rest_before_stream(monkeypatch, tmp_path):
    trial = Trial(tmp_path)
    calls = []
    monkeypatch.setattr(trial, 'docker', lambda *args, **kwargs: calls.append('restart'))
    monkeypatch.setattr(trial, 'rest', lambda *args, **kwargs: calls.append('rest') or '{}')
    monkeypatch.setattr(trial, 'wait', lambda name, probe: probe())
    monkeypatch.setattr(trial, 'await_stream', lambda: calls.append('stream'))
    trial.restart_worker()
    assert calls == ['restart', 'rest', 'stream']


def test_source_offset_rejects_unrelated_partition(monkeypatch, tmp_path):
    trial = Trial(tmp_path)
    monkeypatch.setattr(trial, 'rest', lambda *args: json.dumps({'offsets': [
        {'partition': {'server': 'different'}, 'offset': {'lsn': 12}}
    ]}))
    with pytest.raises(RuntimeError, match='offset partition'):
        trial.source_offset()


def test_pg_lsn_uses_high_and_low_words(monkeypatch, tmp_path):
    trial = Trial(tmp_path)
    monkeypatch.setattr(trial, 'sql', lambda *args: '1/0000000F')
    assert trial.confirmed_lsn() == 4294967311


def test_startup_evidence_only_emits_allowlisted_markers(tmp_path):
    trial = Trial(tmp_path)
    trial.markers.write_text('private-password\nSSLHandshakeException\nprivate-key\n')
    assert trial.startup_evidence('worker') == '; startup=SSLHandshakeException'
    assert trial.startup_evidence('pg') == ''
