package com.nana.phone;

import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Environment;
import android.os.StatFs;
import android.provider.Settings;

import org.json.JSONObject;

final class DeviceController {
    private DeviceController() {}

    static JSONObject execute(Context context, JSONObject request) throws Exception {
        String action = request.optString("action", "").trim();
        JSONObject args = request.optJSONObject("args");
        if (args == null) args = new JSONObject();
        switch (action) {
            case "battery": return battery(context);
            case "device_info": return deviceInfo();
            case "network": return network(context);
            case "storage": return storage();
            case "ui_snapshot": return NanaAccessibilityService.snapshot();
            case "launch_app": return launchApp(context, args.optString("target", ""));
            case "open_settings": return openSettings(context, args.optString("screen", "general"));
            case "global_action": return NanaAccessibilityService.global(args.optString("name", ""));
            case "click_text": return NanaAccessibilityService.clickText(args.optString("text", ""));
            case "input_text": return NanaAccessibilityService.inputText(args.optString("text", ""));
            case "swipe": return NanaAccessibilityService.swipe(
                    args.optInt("x1"), args.optInt("y1"), args.optInt("x2"), args.optInt("y2"),
                    args.optLong("durationMs", 450));
            default: throw new IllegalArgumentException("不支持的动作: " + action);
        }
    }

    private static JSONObject battery(Context context) throws Exception {
        Intent state = context.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        if (state == null) throw new IllegalStateException("系统没有返回电池状态");
        int level = state.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
        int scale = state.getIntExtra(BatteryManager.EXTRA_SCALE, 100);
        int status = state.getIntExtra(BatteryManager.EXTRA_STATUS, -1);
        int percent = level >= 0 && scale > 0 ? Math.round(level * 100f / scale) : -1;
        boolean charging = status == BatteryManager.BATTERY_STATUS_CHARGING
                || status == BatteryManager.BATTERY_STATUS_FULL;
        return new JSONObject()
                .put("percent", percent)
                .put("charging", charging)
                .put("temperatureC", state.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0) / 10.0);
    }

    private static JSONObject deviceInfo() throws Exception {
        return new JSONObject()
                .put("manufacturer", Build.MANUFACTURER)
                .put("brand", Build.BRAND)
                .put("model", Build.MODEL)
                .put("device", Build.DEVICE)
                .put("androidVersion", Build.VERSION.RELEASE)
                .put("sdk", Build.VERSION.SDK_INT);
    }

    private static JSONObject network(Context context) throws Exception {
        ConnectivityManager manager = (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
        Network active = manager.getActiveNetwork();
        NetworkCapabilities caps = active == null ? null : manager.getNetworkCapabilities(active);
        String transport = "none";
        if (caps != null) {
            if (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) transport = "wifi";
            else if (caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)) transport = "cellular";
            else if (caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) transport = "vpn";
            else if (caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)) transport = "ethernet";
        }
        return new JSONObject()
                .put("connected", caps != null && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET))
                .put("validated", caps != null && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED))
                .put("transport", transport);
    }

    private static JSONObject storage() throws Exception {
        StatFs stat = new StatFs(Environment.getDataDirectory().getAbsolutePath());
        return new JSONObject()
                .put("totalBytes", stat.getTotalBytes())
                .put("availableBytes", stat.getAvailableBytes())
                .put("usedBytes", stat.getTotalBytes() - stat.getAvailableBytes());
    }

    private static JSONObject launchApp(Context context, String target) throws Exception {
        String wanted = target == null ? "" : target.trim();
        if (wanted.isEmpty()) throw new IllegalArgumentException("没有提供应用名称或包名");
        PackageManager pm = context.getPackageManager();
        String packageName = wanted;
        Intent launch = pm.getLaunchIntentForPackage(packageName);
        if (launch == null) {
            for (ApplicationInfo info : pm.getInstalledApplications(0)) {
                String label = String.valueOf(pm.getApplicationLabel(info));
                if (label.equalsIgnoreCase(wanted) || label.contains(wanted)) {
                    packageName = info.packageName;
                    launch = pm.getLaunchIntentForPackage(packageName);
                    if (launch != null) break;
                }
            }
        }
        if (launch == null) throw new IllegalArgumentException("没有找到可启动的应用: " + wanted);
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        startVisibleActivity(context, launch);
        Thread.sleep(900);
        String foreground = NanaAccessibilityService.currentPackageName();
        return new JSONObject()
                .put("launched", packageName.equals(foreground))
                .put("requestedPackage", packageName)
                .put("foregroundPackage", foreground);
    }

    private static JSONObject openSettings(Context context, String screen) throws Exception {
        String action;
        switch (screen) {
            case "battery": action = Settings.ACTION_BATTERY_SAVER_SETTINGS; break;
            case "accessibility": action = Settings.ACTION_ACCESSIBILITY_SETTINGS; break;
            default: action = Settings.ACTION_SETTINGS;
        }
        Intent intent = new Intent(action).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        startVisibleActivity(context, intent);
        Thread.sleep(900);
        String foreground = NanaAccessibilityService.currentPackageName();
        return new JSONObject()
                .put("opened", "com.android.settings".equals(foreground))
                .put("screen", screen)
                .put("foregroundPackage", foreground);
    }

    private static void startVisibleActivity(Context context, Intent intent) {
        if (NanaAccessibilityService.isConnected()) {
            NanaAccessibilityService.launch(intent);
        } else {
            context.startActivity(intent);
        }
    }
}
