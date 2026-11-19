"""Generate per-service assets below a private, disposable parent directory."""

import secrets
import subprocess
from pathlib import Path


def properties(values):
    return ''.join(f'{key}={value}\n' for key, value in values.items())


def generate(root: Path):
    def ssl(*args, data=None):
        subprocess.run(['openssl', *args], cwd=root, input=data, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True, timeout=10)

    ssl('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj', '/CN=trial-ca',
        '-keyout', 'ca.key', '-out', 'ca.pem')
    (root / 'ca.key').chmod(0o600)
    store = secrets.token_hex(24)
    role = 'reader_' + secrets.token_hex(6)
    password = secrets.token_hex(24)
    for name in ('pg', 'broker', 'worker'):
        directory = root / name
        directory.mkdir()
        ssl('req', '-newkey', 'rsa:2048', '-nodes', '-subj', f'/CN={name}', '-keyout',
            f'{name}/key.pem', '-out', 'leaf.csr')
        (root / 'extensions').write_text(f'subjectAltName=DNS:{name}\nextendedKeyUsage=serverAuth,clientAuth\n')
        ssl('x509', '-req', '-in', 'leaf.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key', '-CAcreateserial',
            '-days', '1', '-extfile', 'extensions', '-out', f'{name}/cert.pem')
        (directory / 'ca.pem').write_bytes((root / 'ca.pem').read_bytes())
        if name != 'pg':
            ssl('pkcs12', '-export', '-in', f'{name}/cert.pem', '-inkey', f'{name}/key.pem',
                '-certfile', 'ca.pem', '-out', f'{name}/identity.p12', '-passout', 'stdin', data=store.encode()+b'\n')
    tls = {'ssl.keystore.type': 'PKCS12', 'ssl.keystore.location': '/trial/identity.p12',
           'ssl.keystore.password': store, 'ssl.key.password': store, 'ssl.truststore.type': 'PEM',
           'ssl.truststore.location': '/trial/ca.pem'}
    client = {'security.protocol': 'SSL', **tls}
    broker = {'process.roles': 'broker,controller', 'node.id': 1, 'controller.quorum.voters': '1@broker:9093',
              'controller.listener.names': 'CTRL', 'listeners': 'SSL://:9092,CTRL://:9093',
              'advertised.listeners': 'SSL://broker:9092', 'listener.security.protocol.map': 'SSL:SSL,CTRL:SSL',
              'inter.broker.listener.name': 'SSL', 'ssl.client.auth': 'required', **tls,
              'log.dirs': '/var/lib/kafka/data', 'num.partitions': 1, 'offsets.topic.replication.factor': 1,
              'offsets.topic.num.partitions': 1, 'log.retention.bytes': 16777216, 'log.retention.hours': 1,
              'log.segment.bytes': 8388608, 'log.flush.interval.messages': 1}
    worker = {'bootstrap.servers': 'broker:9092', 'group.id': 'trial', 'config.storage.topic': 'configs',
              'offset.storage.topic': 'offsets', 'status.storage.topic': 'status', 'plugin.path': '/kafka/connect',
              'plugin.discovery': 'service_load',
              'listeners': 'https://0.0.0.0:8083', 'rest.advertised.host.name': 'worker', 'ssl.client.auth': 'required',
              'key.converter': 'org.apache.kafka.connect.json.JsonConverter', 'key.converter.schemas.enable': 'false',
              'value.converter': 'org.apache.kafka.connect.json.JsonConverter', 'value.converter.schemas.enable': 'false',
              'config.providers': 'file', 'config.providers.file.class': 'org.apache.kafka.common.config.provider.FileConfigProvider',
              'config.providers.file.param.allowed.paths': '/trial/credentials', 'offset.flush.interval.ms': 1000,
              'producer.acks': 'all', **client, **{'producer.'+k: v for k, v in client.items()},
              **{f'{p}.storage.replication.factor': 1 for p in ('offset','config','status')},
              'status.storage.partitions': 1, 'offset.storage.partitions': 1,
              'rest.advertised.listener': 'https', 'rest.advertised.port': 8083,
              **{'listeners.https.'+k: v for k, v in tls.items()},
              'listeners.https.ssl.client.auth': 'required',
              'listeners.https.ssl.truststore.type': 'PKCS12',
              'listeners.https.ssl.truststore.location': '/tmp/rest-trust.p12',
              'listeners.https.ssl.truststore.password': store}
    (root/'worker/store-password').write_text(store)
    (root/'broker/server').write_text(properties(broker))
    (root/'broker/client').write_text(properties(client))
    (root/'worker/config').write_text(properties(worker))
    (root/'worker/log4j2.properties').write_text(properties({
        'rootLogger.level': 'INFO',
        'rootLogger.appenderRef.console.ref': 'Console',
        'appender.console.type': 'Console',
        'appender.console.name': 'Console',
        'appender.console.layout.type': 'PatternLayout',
        'appender.console.layout.pattern': '%level %logger %msg%n%throwable',
    }))
    (root/'worker/credentials').write_text(properties({'user': role, 'password': password}))
    (root/'pg/bootstrap').write_text(secrets.token_hex(32))
    (root/'pg/hba').write_text(f'local all postgres peer\nhostssl postgres {role} all scram-sha-256\n')
    # Only these service-specific directories cross the container boundary; the host parent is 0700.
    for directory in (root/'pg', root/'broker', root/'worker'):
        directory.chmod(0o755)
        for asset in directory.iterdir():
            asset.chmod(0o444)
    return (f"CREATE ROLE {role} LOGIN REPLICATION PASSWORD '{password}'; "
            "CREATE TABLE items(id int PRIMARY KEY,value text); ALTER TABLE items REPLICA IDENTITY FULL; "
            f"GRANT SELECT ON items TO {role}; CREATE PUBLICATION trial FOR TABLE items;")
