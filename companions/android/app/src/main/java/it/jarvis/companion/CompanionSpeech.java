package it.jarvis.companion;

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import com.getcapacitor.JSObject;
import java.util.ArrayList;
import java.util.Locale;
import java.util.UUID;
import java.util.function.Consumer;

// Never fall back to a network recognizer for ambient wake listening.
final class CompanionSpeech {
    private final Context context;
    private final Consumer<JSObject> emit;
    private final Handler main = new Handler(Looper.getMainLooper());
    private SpeechRecognizer recognizer;
    private TextToSpeech tts;
    private boolean enabled, ttsReady;
    private int generation, failures;
    private String language = "it-IT";
    private Attempt attempt;
    private Consumer<String> spoken;

    CompanionSpeech(Context context, Consumer<JSObject> emit) {
        this.context = context; this.emit = emit;
        tts = new TextToSpeech(context, status -> ttsReady = status == TextToSpeech.SUCCESS);
        tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
            @Override public void onStart(String id) {}
            @Override public void onDone(String id) { main.post(() -> finishSpeech(null)); }
            @Override public void onError(String id) { main.post(() -> finishSpeech("System speech is unavailable.")); }
        });
    }

    String start(String language) {
        stop();
        if (Build.VERSION.SDK_INT < 31 || !SpeechRecognizer.isOnDeviceRecognitionAvailable(context))
            return "On-device speech recognition is unavailable. Install a supported speech service or use manual recording.";
        this.language = language;
        enabled = true; failures = 0;
        try {
            recognizer = SpeechRecognizer.createOnDeviceSpeechRecognizer(context);
            listen();
            return null;
        } catch (Exception error) { stop(); return "Could not start on-device speech recognition."; }
    }

    private void listen() {
        if (!enabled || recognizer == null) return;
        Attempt next = new Attempt();
        attempt = next;
        recognizer.setRecognitionListener(next);
        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, language);
        intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
        intent.putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true);
        try { recognizer.startListening(intent); }
        catch (Exception error) { next.onError(SpeechRecognizer.ERROR_CLIENT); }
    }

    private void restart(long delayMs) {
        final int current = generation;
        attempt = null;
        main.postDelayed(() -> { if (enabled && generation == current) listen(); }, delayMs);
    }

    void stop() {
        enabled = false; generation++; attempt = null;
        if (recognizer != null) { recognizer.cancel(); recognizer.destroy(); recognizer = null; }
        if (tts != null) tts.stop();
        finishSpeech("Speech stopped.");
    }

    void speak(String text, String language, Consumer<String> completion) {
        stop();
        if (!ttsReady) { completion.accept("System speech is not ready."); return; }
        int result = tts.setLanguage(Locale.forLanguageTag(language));
        if (result < 0) { completion.accept("Install a system voice for this language."); return; }
        spoken = completion;
        if (tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, UUID.randomUUID().toString()) == TextToSpeech.ERROR)
            finishSpeech("System speech is unavailable.");
    }

    private void finishSpeech(String error) { Consumer<String> done = spoken; spoken = null; if (done != null) done.accept(error); }
    void destroy() { stop(); tts.shutdown(); }
    private void event(String type) {
        JSObject value = new JSObject(); value.put("type", type); emit.accept(value);
    }
    private void speaking(boolean active) {
        JSObject value = new JSObject(); value.put("type", "speech"); value.put("active", active); emit.accept(value);
    }

    private final class Attempt implements RecognitionListener {
        private final String segment = UUID.randomUUID().toString();
        private boolean speaking;

        private boolean current() { return enabled && attempt == this; }

        private void transcript(Bundle results, boolean isFinal) {
            ArrayList<String> texts = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
            if (texts != null && !texts.isEmpty()) {
                failures = 0;
                JSObject value = new JSObject(); value.put("type", "transcript"); value.put("text", texts.get(0));
                value.put("final", isFinal); value.put("segment", segment); emit.accept(value);
            }
        }

        private void endSpeech() {
            if (speaking) {
                speaking = false;
                speaking(false);
            }
        }

        @Override public void onReadyForSpeech(Bundle params) { if (current()) event("ready"); }
        @Override public void onBeginningOfSpeech() {
            if (!current()) return;
            speaking = true;
            speaking(true);
        }
        @Override public void onRmsChanged(float rmsdB) {}
        @Override public void onBufferReceived(byte[] buffer) {}
        @Override public void onEndOfSpeech() {
            // Allow a delayed final hypothesis to revise the last words.
            main.postDelayed(() -> { if (current()) endSpeech(); }, 1200);
        }
        @Override public void onError(int error) {
            if (!current()) return;
            endSpeech();
            if (error == SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS || error == SpeechRecognizer.ERROR_LANGUAGE_NOT_SUPPORTED || error == SpeechRecognizer.ERROR_LANGUAGE_UNAVAILABLE) {
                stop();
                JSObject value = new JSObject(); value.put("type", "error");
                value.put("message", "Allow microphone access and install on-device recognition for the selected language."); emit.accept(value);
                return;
            }
            boolean quiet = error == SpeechRecognizer.ERROR_NO_MATCH || error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT;
            if (!quiet) failures = Math.min(6, failures + 1);
            event("recovering");
            restart(quiet ? 150 : 300L << failures);
        }
        @Override public void onResults(Bundle results) {
            if (!current()) return;
            transcript(results, true);
            endSpeech();
            restart(0);
        }
        @Override public void onPartialResults(Bundle results) {
            if (current()) transcript(results, false);
        }
        @Override public void onEvent(int eventType, Bundle params) {}
    }
}
