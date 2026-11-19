import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import org.apache.kafka.clients.producer.ProducerInterceptor;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.clients.producer.RecordMetadata;

public final class CrashOnAck implements ProducerInterceptor<byte[], byte[]> {
    @Override
    public ProducerRecord<byte[], byte[]> onSend(ProducerRecord<byte[], byte[]> record) {
        return record;
    }

    @Override
    public void onAcknowledgement(RecordMetadata record, Exception error) {
        Path release = Path.of("/trial/crash-release");
        if (error != null || record == null || !record.topic().equals("trial.public.items")
                || !Files.exists(Path.of("/trial/crash-arm")) || Files.exists(release)) {
            return;
        }
        try {
            Files.createFile(Path.of("/tmp/eos-ack-blocked"));
            long deadline = System.nanoTime() + 45_000_000_000L;
            while (System.nanoTime() - deadline < 0) {
                if (Files.exists(release)) {
                    return;
                }
                Thread.sleep(100);
            }
        } catch (IOException | InterruptedException failure) {
            Runtime.getRuntime().halt(72);
        }
        Runtime.getRuntime().halt(73);
    }

    @Override
    public void configure(Map<String, ?> config) {}

    @Override
    public void close() {}
}
