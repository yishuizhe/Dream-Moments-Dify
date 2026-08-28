package com.nana.phone;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.IBinder;
import android.util.Log;

import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

public class PhoneServerService extends Service {
    static final String ACTION_START = "com.nana.phone.START";
    private static final String TAG = "NanaPhone";
    private static final String CHANNEL = "nana_phone_server";
    private static final int NOTIFICATION_ID = 8765;
    private static volatile boolean running;

    private final ExecutorService clients = Executors.newFixedThreadPool(4);
    private final Map<String, Long> recentNonces = new LinkedHashMap<>();
    private volatile ServerSocket server;
    private Thread acceptThread;

    static boolean isRunning() { return running; }

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(NOTIFICATION_ID, notification("监听端口 " + PhoneSettings.port(this)));
        restartServer();
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        stopServer();
        clients.shutdownNow();
        running = false;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }

    private synchronized void restartServer() {
        stopServer();
        acceptThread = new Thread(() -> {
            ServerSocket listening = null;
            try {
                listening = new ServerSocket(PhoneSettings.port(this), 20);
                server = listening;
                running = true;
                while (!listening.isClosed()) {
                    Socket client = listening.accept();
                    clients.submit(() -> handle(client));
                }
            } catch (Exception error) {
                if (running) Log.e(TAG, "Server stopped unexpectedly", error);
            } finally {
                try { if (listening != null) listening.close(); } catch (Exception ignored) {}
                if (server == listening) {
                    server = null;
                    running = false;
                }
            }
        }, "nana-phone-server");
        acceptThread.start();
    }

    private synchronized void stopServer() {
        running = false;
        try { if (server != null) server.close(); } catch (Exception ignored) {}
        server = null;
    }

    private void handle(Socket socket) {
        try (Socket client = socket) {
            try {
                client.setSoTimeout(10_000);
                HttpRequest request = HttpRequest.read(client);
                if (!authenticate(request)) {
                    write(client, 401, jsonError("认证失败"));
                    return;
                }
                if ("GET".equals(request.method) && "/api/v1/health".equals(request.path)) {
                    JSONObject data = new JSONObject()
                            .put("service", "NanaPhone")
                            .put("version", "0.1.1")
                            .put("accessibility", NanaAccessibilityService.isConnected())
                            .put("port", PhoneSettings.port(this));
                    write(client, 200, envelope(data));
                    return;
                }
                if ("POST".equals(request.method) && "/api/v1/action".equals(request.path)) {
                    JSONObject data = DeviceController.execute(this, new JSONObject(request.body));
                    write(client, 200, envelope(data));
                    return;
                }
                write(client, 404, jsonError("接口不存在"));
            } catch (IllegalArgumentException | IllegalStateException expected) {
                write(client, 400, jsonError(expected.getMessage()));
            } catch (Exception error) {
                Log.e(TAG, "Request failed", error);
                write(client, 500, jsonError("手机端处理失败"));
            }
        } catch (Exception error) {
            Log.e(TAG, "Connection failed", error);
        }
    }

    private boolean authenticate(HttpRequest request) throws Exception {
        String timestamp = request.headers.getOrDefault("x-nana-timestamp", "");
        String nonce = request.headers.getOrDefault("x-nana-nonce", "");
        String signature = request.headers.getOrDefault("x-nana-signature", "");
        long ts;
        try { ts = Long.parseLong(timestamp); } catch (Exception ignored) { return false; }
        long now = System.currentTimeMillis() / 1000L;
        if (Math.abs(now - ts) > 120 || nonce.length() < 16 || signature.length() != 64) return false;
        synchronized (recentNonces) {
            Iterator<Map.Entry<String, Long>> it = recentNonces.entrySet().iterator();
            while (it.hasNext()) if (now - it.next().getValue() > 300) it.remove();
            if (recentNonces.containsKey(nonce)) return false;
        }
        String payload = timestamp + "\n" + nonce + "\n" + request.method + "\n"
                + request.path + "\n" + request.body;
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(PhoneSettings.token(this).getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        String expected = hex(mac.doFinal(payload.getBytes(StandardCharsets.UTF_8)));
        if (!MessageDigest.isEqual(expected.getBytes(StandardCharsets.US_ASCII),
                signature.toLowerCase(Locale.ROOT).getBytes(StandardCharsets.US_ASCII))) return false;
        synchronized (recentNonces) { recentNonces.put(nonce, now); }
        return true;
    }

    private JSONObject envelope(JSONObject data) throws Exception {
        return new JSONObject().put("success", true).put("data", data);
    }

    private JSONObject jsonError(String message) {
        try { return new JSONObject().put("success", false).put("error", String.valueOf(message)); }
        catch (Exception impossible) { return new JSONObject(); }
    }

    private void write(Socket socket, int status, JSONObject payload) throws Exception {
        byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);
        String reason = status == 200 ? "OK" : status == 400 ? "Bad Request"
                : status == 401 ? "Unauthorized" : status == 404 ? "Not Found" : "Server Error";
        String headers = "HTTP/1.1 " + status + " " + reason + "\r\n"
                + "Content-Type: application/json; charset=utf-8\r\n"
                + "Content-Length: " + body.length + "\r\n"
                + "Connection: close\r\n\r\n";
        OutputStream out = socket.getOutputStream();
        out.write(headers.getBytes(StandardCharsets.US_ASCII));
        out.write(body);
        out.flush();
    }

    private String hex(byte[] bytes) {
        StringBuilder out = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) out.append(String.format(Locale.ROOT, "%02x", value));
        return out.toString();
    }

    private void createChannel() {
        NotificationChannel channel = new NotificationChannel(
                CHANNEL, "娜娜手机连接", NotificationManager.IMPORTANCE_LOW);
        channel.setDescription("保持娜娜手机端可以接受已认证的本地请求");
        getSystemService(NotificationManager.class).createNotificationChannel(channel);
    }

    private Notification notification(String text) {
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent pending = PendingIntent.getActivity(this, 0, open,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Builder(this, CHANNEL)
                .setContentTitle("娜娜手机端正在运行")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
                .setContentIntent(pending)
                .setOngoing(true)
                .build();
    }

    private static final class HttpRequest {
        final String method;
        final String path;
        final Map<String, String> headers;
        final String body;

        private HttpRequest(String method, String path, Map<String, String> headers, String body) {
            this.method = method;
            this.path = path;
            this.headers = headers;
            this.body = body;
        }

        static HttpRequest read(Socket socket) throws Exception {
            BufferedInputStream in = new BufferedInputStream(socket.getInputStream());
            ByteArrayOutputStream head = new ByteArrayOutputStream();
            int matched = 0;
            while (head.size() < 32_768) {
                int value = in.read();
                if (value < 0) throw new IllegalArgumentException("请求不完整");
                head.write(value);
                int[] end = {'\r', '\n', '\r', '\n'};
                if (value == end[matched]) matched++; else matched = value == '\r' ? 1 : 0;
                if (matched == 4) break;
            }
            if (matched != 4) throw new IllegalArgumentException("请求头过大");
            String[] lines = new String(head.toByteArray(), StandardCharsets.US_ASCII).split("\\r\\n");
            String[] first = lines[0].split(" ", 3);
            if (first.length < 2) throw new IllegalArgumentException("请求行无效");
            String method = first[0].toUpperCase(Locale.ROOT);
            String path = first[1].split("\\?", 2)[0];
            Map<String, String> headers = new LinkedHashMap<>();
            for (int i = 1; i < lines.length; i++) {
                int colon = lines[i].indexOf(':');
                if (colon > 0) headers.put(lines[i].substring(0, colon).trim().toLowerCase(Locale.ROOT),
                        lines[i].substring(colon + 1).trim());
            }
            int length;
            try { length = Integer.parseInt(headers.getOrDefault("content-length", "0")); }
            catch (Exception ignored) { throw new IllegalArgumentException("Content-Length 无效"); }
            if (length < 0 || length > 65_536) throw new IllegalArgumentException("请求体过大");
            byte[] body = new byte[length];
            int offset = 0;
            while (offset < length) {
                int read = in.read(body, offset, length - offset);
                if (read < 0) throw new IllegalArgumentException("请求体不完整");
                offset += read;
            }
            return new HttpRequest(method, path, headers, new String(body, StandardCharsets.UTF_8));
        }
    }
}
