package it.jarvis.companion;

import android.Manifest;
import android.content.Context;
import android.media.MediaRecorder;
import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;
import java.io.File;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

@CapacitorPlugin(name = "JarvisNative", permissions = {
    @Permission(alias = "microphone", strings = { Manifest.permission.RECORD_AUDIO })
})
public class JarvisNativePlugin extends Plugin {
    private static final String ALIAS = "JarvisCompanionCredentials";
    private MediaRecorder recorder;
    private File recordingFile;
    private boolean stopped;
    private long started;

    @PluginMethod public void shared(PluginCall call) {
        try { JSObject result = new JSObject(); result.put("items", SharedInbox.list(getContext())); call.resolve(result); }
        catch (Exception error) { call.reject("Condivisione non disponibile."); }
    }
    @PluginMethod public void removeShared(PluginCall call) {
        try { SharedInbox.remove(getContext(), call.getString("id")); call.resolve(); }
        catch (Exception error) { call.reject("Identificativo non valido."); }
    }

    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (store.containsAlias(ALIAS)) return (SecretKey) store.getKey(ALIAS, null);
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        KeyGenParameterSpec.Builder spec = new KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE);
        if (Build.VERSION.SDK_INT >= 28) spec.setUnlockedDeviceRequired(true);
        generator.init(spec.build()); return generator.generateKey();
    }

    @PluginMethod public void load(PluginCall call) {
        try {
            String stored = getContext().getSharedPreferences("jarvis-vault", Context.MODE_PRIVATE).getString("credentials", null);
            if (stored == null) { call.resolve(new JSObject()); return; }
            byte[] bytes = Base64.decode(stored, Base64.NO_WRAP);
            if (bytes.length < 29 || bytes.length > 20000) throw new Exception();
            byte[] iv = new byte[12]; System.arraycopy(bytes, 0, iv, 0, 12);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, iv));
            byte[] plain = cipher.doFinal(bytes, 12, bytes.length - 12);
            JSObject result = new JSObject(); result.put("value", new String(plain, StandardCharsets.UTF_8)); call.resolve(result);
        } catch (Exception error) { call.reject("Sblocca il dispositivo o abbinalo nuovamente per accedere alle credenziali."); }
    }

    @PluginMethod public void save(PluginCall call) {
        try {
            String value = call.getString("value");
            if (value == null || value.getBytes(StandardCharsets.UTF_8).length > 8192) throw new Exception();
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key());
            byte[] encrypted = cipher.doFinal(value.getBytes(StandardCharsets.UTF_8));
            byte[] bytes = ByteBuffer.allocate(12 + encrypted.length).put(cipher.getIV()).put(encrypted).array();
            boolean saved = getContext().getSharedPreferences("jarvis-vault", Context.MODE_PRIVATE).edit()
                .putString("credentials", Base64.encodeToString(bytes, Base64.NO_WRAP)).commit();
            if (!saved) throw new Exception(); call.resolve();
        } catch (Exception error) { call.reject("Salvataggio nel deposito protetto non riuscito."); }
    }

    @PluginMethod public void clear(PluginCall call) {
        boolean cleared = getContext().getSharedPreferences("jarvis-vault", Context.MODE_PRIVATE).edit().remove("credentials").commit();
        if (cleared) call.resolve(); else call.reject("Rimozione credenziali non riuscita.");
    }

    @PluginMethod public void startRecording(PluginCall call) {
        if (getPermissionState("microphone") != PermissionState.GRANTED) {
            requestPermissionForAlias("microphone", call, "microphonePermission"); return;
        }
        beginRecording(call);
    }

    @PermissionCallback private void microphonePermission(PluginCall call) {
        if (getPermissionState("microphone") == PermissionState.GRANTED) beginRecording(call);
        else call.reject("Permesso microfono non concesso.");
    }

    private synchronized void beginRecording(PluginCall call) {
        try {
            if (recorder != null) { call.reject("Una registrazione è già attiva."); return; }
            File[] old = getContext().getCacheDir().listFiles((dir, name) -> name.startsWith("jarvis-recording-"));
            if (old != null) for (File file : old) file.delete();
            recordingFile = File.createTempFile("jarvis-recording-", ".m4a", getContext().getCacheDir());
            recorder = Build.VERSION.SDK_INT >= 31 ? new MediaRecorder(getContext()) : new MediaRecorder();
            recorder.setAudioSource(MediaRecorder.AudioSource.MIC);
            recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
            recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
            recorder.setAudioChannels(1); recorder.setAudioSamplingRate(16000); recorder.setAudioEncodingBitRate(48000);
            recorder.setMaxDuration(60000); recorder.setMaxFileSize(2000000); recorder.setOutputFile(recordingFile.getAbsolutePath());
            stopped = false;
            recorder.setOnInfoListener((r, what, extra) -> {
                if (what == MediaRecorder.MEDIA_RECORDER_INFO_MAX_DURATION_REACHED || what == MediaRecorder.MEDIA_RECORDER_INFO_MAX_FILESIZE_REACHED) {
                    synchronized (this) { try { r.stop(); } catch (Exception ignored) {} stopped = true; }
                }
            });
            recorder.prepare(); recorder.start(); started = System.currentTimeMillis(); call.resolve();
        } catch (Exception error) { cleanup(); call.reject("Impossibile avviare la registrazione."); }
    }

    @PluginMethod public synchronized void stopRecording(PluginCall call) {
        try {
            if (recorder == null || recordingFile == null) { call.reject("Nessuna registrazione attiva."); return; }
            if (!stopped) recorder.stop();
            if (recordingFile.length() > 3000000) throw new Exception();
            byte[] content = Files.readAllBytes(recordingFile.toPath());
            JSObject result = new JSObject(); result.put("content", Base64.encodeToString(content, Base64.NO_WRAP));
            result.put("mime", "audio/mp4"); result.put("seconds", Math.min(60, (System.currentTimeMillis() - started) / 1000.0));
            call.resolve(result);
        } catch (Exception error) { call.reject("Registrazione non disponibile."); }
        finally { cleanup(); }
    }

    private void cleanup() {
        if (recorder != null) { try { recorder.release(); } catch (Exception ignored) {} recorder = null; }
        if (recordingFile != null) { recordingFile.delete(); recordingFile = null; }
    }

    @Override protected void handleOnDestroy() { cleanup(); }
}
