package com.nana.phone;

import android.Manifest;
import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.text.InputType;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.net.Inet4Address;
import java.net.NetworkInterface;
import java.util.Collections;

public class MainActivity extends Activity {
    private TextView status;
    private TextView endpoint;
    private TextView tokenView;
    private EditText portInput;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 100);
        }
        setContentView(buildUi());
        refresh();
    }

    @Override
    protected void onResume() {
        super.onResume();
        refresh();
    }

    private ScrollView buildUi() {
        int pad = dp(20);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, pad);
        root.setBackgroundColor(Color.rgb(247, 244, 255));

        TextView title = text("娜娜手机端", 28);
        title.setTextColor(Color.rgb(65, 48, 130));
        root.addView(title);
        root.addView(text("让电脑上的娜娜可靠读取和操作这部手机。建议通过 Tailscale 连接，不要把端口暴露到公网。", 15));

        status = text("", 17);
        root.addView(status, margins());
        endpoint = text("", 15);
        root.addView(endpoint, margins());

        portInput = new EditText(this);
        portInput.setHint("监听端口");
        portInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        root.addView(portInput, margins());

        Button start = button("启动 / 重启手机服务");
        start.setOnClickListener(v -> startServer());
        root.addView(start, margins());

        Button stop = button("停止手机服务");
        stop.setOnClickListener(v -> {
            stopService(new Intent(this, PhoneServerService.class));
            refresh();
        });
        root.addView(stop, margins());

        Button accessibility = button("打开无障碍权限设置");
        accessibility.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        root.addView(accessibility, margins());

        root.addView(text("配对密钥（只复制到 Dream 配置，不要发给别人）", 14), margins());
        tokenView = text("", 13);
        tokenView.setTextIsSelectable(true);
        root.addView(tokenView, margins());

        Button copy = button("复制配对密钥");
        copy.setOnClickListener(v -> {
            ClipboardManager clipboard = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
            clipboard.setPrimaryClip(ClipData.newPlainText("NanaPhone token", PhoneSettings.token(this)));
            Toast.makeText(this, "已复制", Toast.LENGTH_SHORT).show();
        });
        root.addView(copy, margins());

        Button reset = button("重新生成配对密钥");
        reset.setOnClickListener(v -> {
            tokenView.setText(PhoneSettings.regenerateToken(this));
            startServer();
        });
        root.addView(reset, margins());

        TextView note = text(
                "首版能力：电量、设备信息、网络、存储、打开应用、返回/主页/最近任务、按文字点击、输入和滑动。"
                        + " 点击、输入和滑动需要开启无障碍权限。付款、发送、删除等危险动作仍由电脑端二次确认。",
                14
        );
        root.addView(note, margins());

        ScrollView scroll = new ScrollView(this);
        scroll.addView(root);
        return scroll;
    }

    private void startServer() {
        int port;
        try {
            port = Integer.parseInt(portInput.getText().toString().trim());
        } catch (Exception ignored) {
            port = PhoneSettings.DEFAULT_PORT;
        }
        if (port < 1024 || port > 65535) {
            Toast.makeText(this, "端口必须在 1024 到 65535 之间", Toast.LENGTH_SHORT).show();
            return;
        }
        PhoneSettings.setPort(this, port);
        Intent intent = new Intent(this, PhoneServerService.class);
        intent.setAction(PhoneServerService.ACTION_START);
        startForegroundService(intent);
        refresh();
    }

    private void refresh() {
        if (status == null) return;
        status.setText(getString(
                R.string.service_status,
                getString(PhoneServerService.isRunning() ? R.string.service_running : R.string.service_stopped),
                getString(NanaAccessibilityService.isConnected()
                        ? R.string.accessibility_enabled : R.string.accessibility_disabled)
        ));
        int port = PhoneSettings.port(this);
        portInput.setText(String.valueOf(port));
        endpoint.setText(getString(R.string.endpoint_format, localIp(), port));
        tokenView.setText(PhoneSettings.token(this));
    }

    private String localIp() {
        try {
            for (NetworkInterface nic : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!nic.isUp() || nic.isLoopback()) continue;
                for (java.net.InetAddress address : Collections.list(nic.getInetAddresses())) {
                    if (address instanceof Inet4Address && !address.isLoopbackAddress()) {
                        return address.getHostAddress();
                    }
                }
            }
        } catch (Exception ignored) {}
        return "手机的 Tailscale/IP 地址";
    }

    private TextView text(String value, int sp) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(sp);
        view.setTextColor(Color.rgb(40, 36, 48));
        view.setLineSpacing(0, 1.15f);
        return view;
    }

    private Button button(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setAllCaps(false);
        return button;
    }

    private LinearLayout.LayoutParams margins() {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.topMargin = dp(12);
        return params;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
