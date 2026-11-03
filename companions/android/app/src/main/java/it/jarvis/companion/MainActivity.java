package it.jarvis.companion;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override public void onCreate(android.os.Bundle state) {
        registerPlugin(JarvisNativePlugin.class);
        super.onCreate(state);
        android.content.Intent incoming = getIntent();
        new Thread(() -> SharedInbox.accept(this, incoming), "JarvisShare").start();
    }
    @Override protected void onNewIntent(android.content.Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        new Thread(() -> SharedInbox.accept(this, intent), "JarvisShare").start();
    }
}
