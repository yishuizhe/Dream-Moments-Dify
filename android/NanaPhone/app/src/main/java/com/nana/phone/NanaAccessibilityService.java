package com.nana.phone;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.graphics.Rect;
import android.os.Bundle;
import android.content.Intent;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONObject;
import org.json.JSONArray;

import java.util.List;
import java.util.ArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

public class NanaAccessibilityService extends AccessibilityService {
    private static volatile NanaAccessibilityService instance;

    static boolean isConnected() {
        return instance != null;
    }

    static void launch(Intent intent) {
        requireService().startActivity(intent);
    }

    static String currentPackageName() {
        NanaAccessibilityService service = instance;
        if (service == null) return "";
        AccessibilityNodeInfo root = service.getRootInActiveWindow();
        return root == null || root.getPackageName() == null ? "" : root.getPackageName().toString();
    }

    @Override
    protected void onServiceConnected() {
        instance = this;
    }

    @Override
    public void onDestroy() {
        if (instance == this) instance = null;
        super.onDestroy();
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {}

    @Override
    public void onInterrupt() {}

    static JSONObject global(String action) throws Exception {
        NanaAccessibilityService service = requireService();
        int code;
        switch (action) {
            case "back": code = GLOBAL_ACTION_BACK; break;
            case "home": code = GLOBAL_ACTION_HOME; break;
            case "recents": code = GLOBAL_ACTION_RECENTS; break;
            case "notifications": code = GLOBAL_ACTION_NOTIFICATIONS; break;
            default: throw new IllegalArgumentException("不支持的全局动作: " + action);
        }
        boolean ok = service.performGlobalAction(code);
        return new JSONObject().put("performed", ok).put("action", action);
    }

    static JSONObject clickText(String text) throws Exception {
        NanaAccessibilityService service = requireService();
        AccessibilityNodeInfo root = service.getRootInActiveWindow();
        if (root == null) throw new IllegalStateException("当前无法读取屏幕控件");
        List<AccessibilityNodeInfo> nodes = new ArrayList<>(root.findAccessibilityNodeInfosByText(text));
        AccessibilityNodeInfo manual = findByText(root, text);
        if (nodes.isEmpty() && manual != null) nodes.add(manual);
        for (AccessibilityNodeInfo node : nodes) {
            AccessibilityNodeInfo target = node;
            while (target != null && !target.isClickable()) target = target.getParent();
            if (target != null && target.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                return new JSONObject().put("performed", true).put("matchedText", text);
            }
            Rect bounds = new Rect();
            node.getBoundsInScreen(bounds);
            if (!bounds.isEmpty() && performTap(service, bounds.centerX(), bounds.centerY())) {
                return new JSONObject().put("performed", true).put("matchedText", text).put("fallback", "tap");
            }
        }
        return new JSONObject().put("performed", false).put("matchedText", text);
    }

    static JSONObject inputText(String text) throws Exception {
        NanaAccessibilityService service = requireService();
        AccessibilityNodeInfo root = service.getRootInActiveWindow();
        if (root == null) throw new IllegalStateException("当前无法读取屏幕控件");
        AccessibilityNodeInfo focused = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
        if (focused == null || !focused.isEditable()) focused = findEditable(root);
        if (focused == null || !focused.isEditable()) {
            throw new IllegalStateException("当前没有可输入的文本框");
        }
        Bundle args = new Bundle();
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
        boolean ok = focused.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
        return new JSONObject().put("performed", ok).put("characters", text.length());
    }

    private static AccessibilityNodeInfo findByText(AccessibilityNodeInfo node, String wanted) {
        if (node == null) return null;
        String text = node.getText() == null ? "" : node.getText().toString();
        String description = node.getContentDescription() == null ? "" : node.getContentDescription().toString();
        if (text.contains(wanted) || description.contains(wanted)) return node;
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo found = findByText(node.getChild(i), wanted);
            if (found != null) return found;
        }
        return null;
    }

    private static AccessibilityNodeInfo findEditable(AccessibilityNodeInfo node) {
        if (node == null) return null;
        if (node.isEditable() && node.isVisibleToUser()) return node;
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo found = findEditable(node.getChild(i));
            if (found != null) return found;
        }
        return null;
    }

    private static boolean performTap(NanaAccessibilityService service, int x, int y) throws InterruptedException {
        Path path = new Path();
        path.moveTo(x, y);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0, 80))
                .build();
        CountDownLatch latch = new CountDownLatch(1);
        final boolean[] completed = {false};
        service.dispatchGesture(gesture, new GestureResultCallback() {
            @Override public void onCompleted(GestureDescription gestureDescription) {
                completed[0] = true;
                latch.countDown();
            }
            @Override public void onCancelled(GestureDescription gestureDescription) {
                latch.countDown();
            }
        }, null);
        latch.await(2, TimeUnit.SECONDS);
        return completed[0];
    }

    static JSONObject swipe(int x1, int y1, int x2, int y2, long durationMs) throws Exception {
        NanaAccessibilityService service = requireService();
        Path path = new Path();
        path.moveTo(x1, y1);
        path.lineTo(x2, y2);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0, Math.max(100, durationMs)))
                .build();
        CountDownLatch latch = new CountDownLatch(1);
        final boolean[] completed = {false};
        service.dispatchGesture(gesture, new GestureResultCallback() {
            @Override public void onCompleted(GestureDescription gestureDescription) {
                completed[0] = true;
                latch.countDown();
            }
            @Override public void onCancelled(GestureDescription gestureDescription) {
                latch.countDown();
            }
        }, null);
        latch.await(3, TimeUnit.SECONDS);
        return new JSONObject().put("performed", completed[0]);
    }

    static JSONObject snapshot() throws Exception {
        NanaAccessibilityService service = requireService();
        AccessibilityNodeInfo root = service.getRootInActiveWindow();
        if (root == null) throw new IllegalStateException("当前无法读取屏幕控件");
        JSONArray nodes = new JSONArray();
        int[] visited = {0};
        collectNodes(root, nodes, visited, 120);
        return new JSONObject()
                .put("packageName", String.valueOf(root.getPackageName()))
                .put("windowClass", String.valueOf(root.getClassName()))
                .put("nodes", nodes)
                .put("truncated", visited[0] >= 120);
    }

    private static void collectNodes(
            AccessibilityNodeInfo node,
            JSONArray output,
            int[] visited,
            int limit
    ) throws Exception {
        if (node == null || visited[0] >= limit) return;
        visited[0]++;
        CharSequence text = node.getText();
        CharSequence description = node.getContentDescription();
        String viewId = node.getViewIdResourceName();
        boolean useful = (text != null && text.length() > 0)
                || (description != null && description.length() > 0)
                || (viewId != null && !viewId.isEmpty())
                || node.isClickable() || node.isEditable() || node.isScrollable();
        if (useful && node.isVisibleToUser()) {
            Rect bounds = new Rect();
            node.getBoundsInScreen(bounds);
            output.put(new JSONObject()
                    .put("text", text == null ? "" : text.toString())
                    .put("description", description == null ? "" : description.toString())
                    .put("viewId", viewId == null ? "" : viewId)
                    .put("className", String.valueOf(node.getClassName()))
                    .put("bounds", new JSONArray()
                            .put(bounds.left).put(bounds.top).put(bounds.right).put(bounds.bottom))
                    .put("clickable", node.isClickable())
                    .put("editable", node.isEditable())
                    .put("scrollable", node.isScrollable()));
        }
        for (int i = 0; i < node.getChildCount() && visited[0] < limit; i++) {
            collectNodes(node.getChild(i), output, visited, limit);
        }
    }

    private static NanaAccessibilityService requireService() {
        NanaAccessibilityService service = instance;
        if (service == null) throw new IllegalStateException("请先在系统设置中开启娜娜手机控制无障碍权限");
        return service;
    }
}
