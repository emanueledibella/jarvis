package it.jarvis.companion;

import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;
import android.util.Base64;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Locale;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;

final class SharedInbox {
    static File directory(Context context) { return new File(context.getCacheDir(), "jarvis-shared"); }
    static synchronized void accept(Context context, Intent intent) {
        if (intent == null || !(Intent.ACTION_SEND.equals(intent.getAction()) || Intent.ACTION_SEND_MULTIPLE.equals(intent.getAction()))) return;
        try {
            File directory = directory(context); directory.mkdirs();
            list(context);
            File[] existing = directory.listFiles();
            if (existing != null && existing.length >= 5) return;
            int available = 5 - (existing == null ? 0 : existing.length);
            ArrayList<JSONObject> items = new ArrayList<>();
            CharSequence text = intent.getCharSequenceExtra(Intent.EXTRA_TEXT);
            if (text != null && text.length() <= 100000) items.add(new JSONObject().put("text", text.toString()));
            ArrayList<Uri> uris = new ArrayList<>();
            if (Intent.ACTION_SEND_MULTIPLE.equals(intent.getAction())) {
                ArrayList<Uri> values = intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
                if (values != null) uris.addAll(values.subList(0, Math.min(5, values.size())));
            } else {
                Uri uri = intent.getParcelableExtra(Intent.EXTRA_STREAM);
                if (uri != null) uris.add(uri);
            }
            for (Uri uri : uris) {
                if (!"content".equals(uri.getScheme()) || items.size() >= 5) continue;
                String name = "document.txt";
                try (Cursor cursor = context.getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
                    if (cursor != null && cursor.moveToFirst()) name = cursor.getString(0);
                }
                name = name.replaceAll("[\\\\/\\p{Cntrl}]", "_");
                if (name.length() > 180 || !name.toLowerCase(Locale.ROOT).matches(".*\\.(pdf|docx|txt|md|csv|png|jpe?g)$")) continue;
                try (InputStream input = context.getContentResolver().openInputStream(uri); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
                    if (input == null) continue;
                    byte[] chunk = new byte[8192]; int count;
                    while ((count = input.read(chunk)) != -1) { output.write(chunk, 0, count); if (output.size() > 3000000) break; }
                    if (output.size() == 0 || output.size() > 3000000) continue;
                    items.add(new JSONObject().put("name", name).put("content", Base64.encodeToString(output.toByteArray(), Base64.NO_WRAP)));
                }
            }
            for (JSONObject value : items) {
                if (available-- <= 0) break;
                String id = UUID.randomUUID().toString();
                value.put("id", id).put("created", System.currentTimeMillis());
                Files.write(new File(directory, id + ".json").toPath(), value.toString().getBytes(StandardCharsets.UTF_8));
            }
        } catch (Exception ignored) { /* Invalid third-party shares never become commands. */ }
    }
    static synchronized JSONArray list(Context context) throws Exception {
        JSONArray values = new JSONArray();
        File[] files = directory(context).listFiles();
        if (files == null) return values;
        for (File file : files) {
            if (System.currentTimeMillis() - file.lastModified() > 900000 || file.length() > 4100000 || values.length() >= 5) { file.delete(); continue; }
            values.put(new JSONObject(new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8)));
        }
        return values;
    }
    static synchronized void remove(Context context, String id) {
        UUID.fromString(id);
        new File(directory(context), id + ".json").delete();
    }
}
